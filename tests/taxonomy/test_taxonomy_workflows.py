import pytest
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.forms_submissions import DecoderSubmissionForm
from registry.forms_taxonomy import TagPromotionForm
from registry.models import NoiseModel, RecordEvent, RecordHistory, Tag
from registry.services.circuits import noise_model_catalogue
from registry.services.taxonomy import (
    CUSTOM_VOCABULARY_ROUTE,
    CUSTOM_VOCABULARY_SYSTEM,
    TaxonomyConflictError,
    TaxonomyPermissionError,
    TaxonomyStateError,
    TaxonomyValidationError,
    approve_and_publish_noise_model,
    create_custom_tag,
    deprecate_noise_model,
    deprecate_tag,
    promote_noise_model_official,
    promote_tag_official,
    submit_noise_model,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def taxonomy_urls(settings):
    settings.ROOT_URLCONF = "tests.taxonomy.urls"


@pytest.fixture
def taxonomy_data():
    seed_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
        "matching": Tag.objects.get(id=demo_id("tag/algorithm/matching")),
        "memory": Tag.objects.get(id=demo_id("tag/experiment/memory")),
        "noise": NoiseModel.objects.get(id=demo_id("noise/fixed-phenomenological")),
    }


def _custom_tag(submitter, *, slug="union-find", namespace="algorithm"):
    return create_custom_tag(
        submitter=submitter,
        namespace=namespace,
        slug=slug,
        label=slug.replace("-", " ").title(),
        description="A community-provided taxonomy term.",
    ).tag


def _pending_noise(submitter, *, slug="biased-circuit-noise", predecessor=None):
    return submit_noise_model(
        submitter=submitter,
        slug=slug,
        name=slug.replace("-", " ").title(),
        short_description="A pending community noise model.",
        paper_url="https://example.org/papers/community-noise",
        randomises_priors=True,
        predecessor=predecessor,
    ).noise_model


def test_custom_tag_is_immediately_usable_with_exact_system_attribution(
    taxonomy_data,
):
    contributor = taxonomy_data["contributor"]
    outcome = create_custom_tag(
        submitter=contributor,
        namespace="algorithm",
        slug="union-find",
        label="Union find",
        description="Uses a union-find decoding stage.",
    )
    tag = outcome.tag

    assert tag.status == Tag.Status.CUSTOM
    assert tag.display_color is None
    assert tag.history.record_kind == "tag"
    assert (
        DecoderSubmissionForm()
        .fields["algorithm_tags"]
        .queryset.filter(id=tag.id)
        .exists()
    )

    events = list(tag.record_events.order_by("sequence"))
    assert [event.action for event in events] == ["submitted", "approved", "published"]
    assert events[0].actor_type == RecordEvent.ActorType.ACCOUNT
    assert events[0].actor_account == contributor
    assert events[0].details["approval_route"] == CUSTOM_VOCABULARY_ROUTE
    assert events[1].actor_type == RecordEvent.ActorType.SYSTEM
    assert events[1].actor_system == CUSTOM_VOCABULARY_SYSTEM
    assert events[2].actor_system == CUSTOM_VOCABULARY_SYSTEM
    assert events[1].caused_by == events[0]
    assert events[2].caused_by == events[1]


def test_duplicate_tag_identity_and_database_race_leave_no_orphan_history(
    taxonomy_data, monkeypatch
):
    contributor = taxonomy_data["contributor"]
    tag = _custom_tag(contributor)
    history_count = RecordHistory.objects.count()

    with pytest.raises(TaxonomyConflictError, match="already present"):
        _custom_tag(contributor)
    assert RecordHistory.objects.count() == history_count

    monkeypatch.setattr(QuerySet, "exists", lambda self: False)
    with pytest.raises(TaxonomyConflictError, match="another request"):
        _custom_tag(contributor)
    assert Tag.objects.filter(namespace="algorithm", slug="union-find").count() == 1
    assert RecordHistory.objects.count() == history_count
    assert tag.history_id is not None


def test_tag_promotion_requires_admin_and_valid_colour(taxonomy_data):
    tag = _custom_tag(taxonomy_data["contributor"])

    with pytest.raises(TaxonomyPermissionError):
        promote_tag_official(
            tag.id, curator=taxonomy_data["contributor"], display_color="#123456"
        )
    with pytest.raises(TaxonomyValidationError):
        promote_tag_official(
            tag.id, curator=taxonomy_data["admin"], display_color="rgb(1,2,3)"
        )
    assert not TagPromotionForm({"display_color": "#12345"}).is_valid()

    promoted = promote_tag_official(
        tag.id, curator=taxonomy_data["admin"], display_color="#a1b2c3"
    )
    assert promoted.status == Tag.Status.OFFICIAL
    assert promoted.display_color == "#A1B2C3"
    event = promoted.record_events.get(action="promoted_official")
    assert event.actor_account == taxonomy_data["admin"]
    assert event.details["display_color"] == "#A1B2C3"


def test_tag_deprecation_requires_namespace_correct_canonical_target(taxonomy_data):
    tag = _custom_tag(taxonomy_data["contributor"])

    with pytest.raises(TaxonomyValidationError, match="same namespace"):
        deprecate_tag(
            tag.id,
            curator=taxonomy_data["admin"],
            canonical_tag_id=taxonomy_data["memory"].id,
        )
    tag.refresh_from_db()
    assert tag.status == Tag.Status.CUSTOM
    assert tag.canonical_tag is None

    deprecated = deprecate_tag(
        tag.id,
        curator=taxonomy_data["admin"],
        canonical_tag_id=taxonomy_data["matching"].id,
    )
    assert deprecated.status == Tag.Status.DEPRECATED
    assert deprecated.canonical_tag == taxonomy_data["matching"]
    events = list(deprecated.record_events.order_by("sequence"))
    assert [event.action for event in events[-2:]] == ["deprecated", "merged"]
    assert events[-1].caused_by == events[-2]
    assert events[-1].details["canonical_identity"] == "algorithm:matching"


def test_deprecated_alias_cannot_be_used_as_a_canonical_replacement(taxonomy_data):
    first = _custom_tag(taxonomy_data["contributor"], slug="old-clustering")
    second = _custom_tag(taxonomy_data["contributor"], slug="older-clustering")
    deprecate_tag(
        first.id,
        curator=taxonomy_data["admin"],
        canonical_tag_id=taxonomy_data["matching"].id,
    )

    with pytest.raises(TaxonomyConflictError, match="active canonical"):
        deprecate_tag(
            second.id,
            curator=taxonomy_data["admin"],
            canonical_tag_id=first.id,
        )


def test_noise_model_submission_is_community_pending_and_not_public(taxonomy_data):
    contributor = taxonomy_data["contributor"]
    outcome = submit_noise_model(
        submitter=contributor,
        slug="biased-circuit-noise",
        name="Biased circuit noise",
        short_description="A pending community noise model.",
        paper_url="https://example.org/papers/community-noise",
        randomises_priors=True,
    )
    noise_model = outcome.noise_model

    assert noise_model.state == "pending_review"
    assert noise_model.published_at is None
    assert noise_model.curation_status == NoiseModel.CurationStatus.COMMUNITY
    assert not noise_model_catalogue().filter(id=noise_model.id).exists()
    event = noise_model.record_events.get(action="submitted")
    assert event.actor_account == contributor
    assert event.actor_system is None
    assert event.details["approval_route"] == "admin_review"
    assert not noise_model.record_events.filter(action="approved").exists()


def test_noise_model_lineage_reuses_history_and_allows_one_successor(
    taxonomy_data,
):
    predecessor = taxonomy_data["noise"]
    successor = _pending_noise(
        taxonomy_data["contributor"],
        slug="fixed-phenomenological-v2",
        predecessor=predecessor,
    )

    assert successor.predecessor == predecessor
    assert successor.history_id == predecessor.history_id
    events = list(successor.record_events.order_by("sequence"))
    revision = next(
        event
        for event in events
        if event.noise_model_id == successor.id and event.action == "revision_created"
    )
    assert revision.details["predecessor_id"] == str(predecessor.id)

    with pytest.raises(TaxonomyConflictError, match="already has a successor"):
        _pending_noise(
            taxonomy_data["contributor"],
            slug="fixed-phenomenological-competing-v2",
            predecessor=predecessor,
        )


def test_withdrawn_noise_model_successor_enters_reapproval(taxonomy_data):
    predecessor = taxonomy_data["noise"]
    predecessor.state = "withdrawn"
    predecessor.withdrawn_at = timezone.now()
    predecessor.save(update_fields=["state", "withdrawn_at"])

    successor = _pending_noise(
        taxonomy_data["contributor"],
        slug="fixed-phenomenological-replacement",
        predecessor=predecessor,
    )

    assert successor.state == "pending_reapproval"
    event = successor.record_events.get(action="resubmitted")
    assert event.details["projected_state"] == "pending_reapproval"


def test_noise_model_approval_and_official_promotion_are_separate(taxonomy_data):
    noise_model = _pending_noise(taxonomy_data["contributor"])

    with pytest.raises(TaxonomyPermissionError):
        approve_and_publish_noise_model(
            noise_model.id, reviewer=taxonomy_data["contributor"]
        )
    published = approve_and_publish_noise_model(
        noise_model.id, reviewer=taxonomy_data["admin"]
    )
    assert published.state == "published"
    assert published.published_at is not None
    assert published.curation_status == NoiseModel.CurationStatus.COMMUNITY
    assert noise_model_catalogue().filter(id=published.id).exists()
    approval, publication = published.record_events.filter(
        action__in=("approved", "published")
    ).order_by("sequence")
    assert approval.actor_account == taxonomy_data["admin"]
    assert publication.actor_account == taxonomy_data["admin"]
    assert publication.caused_by == approval

    official = promote_noise_model_official(
        published.id, curator=taxonomy_data["admin"]
    )
    assert official.curation_status == NoiseModel.CurationStatus.OFFICIAL
    promoted = official.record_events.get(action="promoted_official")
    assert promoted.actor_account == taxonomy_data["admin"]


def test_noise_model_deprecation_is_audited_and_requires_publication(taxonomy_data):
    pending = _pending_noise(taxonomy_data["contributor"])
    with pytest.raises(TaxonomyStateError, match="published"):
        deprecate_noise_model(
            pending.id, curator=taxonomy_data["admin"], note="Superseded."
        )

    approve_and_publish_noise_model(pending.id, reviewer=taxonomy_data["admin"])
    deprecated = deprecate_noise_model(
        pending.id,
        curator=taxonomy_data["admin"],
        note="The assumptions were replaced.",
    )
    assert deprecated.curation_status == NoiseModel.CurationStatus.DEPRECATED
    event = deprecated.record_events.get(action="deprecated")
    assert event.actor_account == taxonomy_data["admin"]
    assert event.note == "The assumptions were replaced."


def test_preview_flow_and_admin_queue_permissions(client, taxonomy_data):
    curation_url = reverse("taxonomy:curation")
    assert client.get(reverse("taxonomy:tag-create")).status_code == 302
    assert client.get(curation_url).status_code == 302

    client.force_login(taxonomy_data["contributor"])
    assert client.get(curation_url).status_code == 403
    response = client.post(
        reverse("taxonomy:tag-create"),
        {
            "namespace": "code",
            "slug": "honeycomb-code",
            "label": "Honeycomb code",
            "description": "A code-family term submitted from the compact form.",
        },
    )
    assert response.status_code == 302
    assert "/preview/" in response.url
    preview = client.get(response.url)
    assert preview.status_code == 200
    assert b"Preview custom tag" in preview.content
    assert b"provisional custom-vocabulary route" in preview.content
    confirmed = client.post(response.url)
    assert confirmed.status_code == 200
    assert b"Custom tag created" in confirmed.content
    assert Tag.objects.filter(namespace="code", slug="honeycomb-code").exists()

    client.force_login(taxonomy_data["admin"])
    queue = client.get(curation_url)
    assert queue.status_code == 200
    assert b"Taxonomy curation" in queue.content
    assert b"Honeycomb code" in queue.content


def test_database_namespace_slug_constraint_remains_last_line_of_defence(
    taxonomy_data,
):
    source = _custom_tag(taxonomy_data["contributor"])
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Tag.objects.create(
                schema_release=source.schema_release,
                history=RecordHistory.objects.create(record_kind="tag"),
                namespace=source.namespace,
                slug=source.slug,
                label="Competing label",
                description="A direct conflicting write.",
                status=Tag.Status.CUSTOM,
                submitted_by=taxonomy_data["contributor"],
            )
