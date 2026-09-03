import pytest
from django.core.management import CommandError, call_command
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import RecordEvent, Tag, TagAlias, TagParent
from registry.services.taxonomy import (
    TaxonomyPermissionError,
    TaxonomyValidationError,
    create_custom_tag,
    promote_tag_official,
    update_tag,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def production_urls(settings):
    settings.ROOT_URLCONF = "config.urls"


@pytest.fixture
def accounts():
    seed_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
    }


def test_alias_changes_are_durable_and_audited(accounts):
    contributor = accounts["contributor"]
    tag = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Parity forest",
        description="Uses disjoint-set merging.",
        aliases=("PF", "Forest method"),
    ).tag

    assert tag.slug == "parity-forest"
    assert set(tag.aliases.filter(is_active=True).values_list("alias", flat=True)) == {
        "PF",
        "Forest method",
    }
    assert set(
        tag.record_events.filter(action=RecordEvent.Action.ADDED_ALIAS).values_list(
            "details__alias", flat=True
        )
    ) == {"PF", "Forest method"}

    update_tag(
        tag.id,
        actor=contributor,
        label="Parity forest method",
        description="Uses a disjoint-set data structure.",
        aliases=("Forest method", "Parity forest decoder"),
    )

    assert set(tag.aliases.filter(is_active=True).values_list("alias", flat=True)) == {
        "Forest method",
        "Parity forest decoder",
    }
    removed = TagAlias.objects.get(tag=tag, alias="PF")
    assert not removed.is_active
    assert removed.removed_by == contributor
    assert removed.removed_at is not None
    assert tag.record_events.filter(
        action=RecordEvent.Action.REMOVED_ALIAS,
        details__alias="PF",
    ).exists()


def test_custom_owner_loses_edit_permission_after_official_promotion(accounts):
    contributor = accounts["contributor"]
    tag = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.CODE,
        label="Tiny code",
        description="A custom code family.",
    ).tag
    promote_tag_official(tag.id, curator=accounts["admin"], display_color="#315F7D")

    with pytest.raises(TaxonomyPermissionError):
        update_tag(
            tag.id,
            actor=contributor,
            label=tag.label,
            description="Contributor edit after promotion.",
            aliases=(),
        )

    update_tag(
        tag.id,
        actor=accounts["admin"],
        label=tag.label,
        description="Administrator edit after promotion.",
        aliases=("Small code",),
    )
    tag.refresh_from_db()
    assert tag.description == "Administrator edit after promotion."


def test_inline_creation_api_and_alias_aware_picker(accounts, client):
    client.force_login(accounts["contributor"])
    parent = Tag.objects.get(slug="matching")
    response = client.post(
        reverse("taxonomy:tag-create-json"),
        {
            "namespace": "algorithm",
            "label": "Peeling decoder",
            "visibility": "private",
            "description": "Iteratively removes degree-one checks.",
            "aliases": "leaf removal\npeeling",
            "parents": [str(parent.id)],
        },
    )

    assert response.status_code == 201
    payload = response.json()["tag"]
    assert payload["aliases"] == ["leaf removal", "peeling"]
    assert payload["parents"][0]["id"] == str(parent.id)
    assert payload["url"] == "/tags/algorithm/peeling-decoder/"
    assert Tag.objects.get(id=payload["id"]).visibility == "private"

    form_page = client.get(reverse("submissions:create", args=["decoder"]))
    content = form_page.content.decode()
    assert "Please check carefully if there is an existing tag" in content
    assert "data-tag-create-visibility" in content
    assert reverse("taxonomy:tag-create-json") in content
    search = client.get(
        reverse("pickers:taxonomy-terms"),
        {"namespace": "algorithm", "q": "leaf removal"},
    ).json()
    assert search["circuit_bench"]["shown"][0]["matched_alias"] == "leaf removal"

    conflict = client.post(
        reverse("taxonomy:tag-create-json"),
        {
            "namespace": "algorithm",
            "label": "leaf removal",
            "description": "Would collide with an alias.",
        },
    )
    assert conflict.status_code == 409


def test_tag_detail_links_usage_history_and_owner_edit(accounts, client):
    contributor = accounts["contributor"]
    tag = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.EXPERIMENT,
        label="Repeated memory",
        description="A repeated memory experiment.",
        aliases=("memory repetition",),
    ).tag

    detail = client.get(tag.get_absolute_url())
    assert detail.status_code == 200
    content = detail.content.decode()
    assert "memory repetition" in content
    assert "Record history" in content
    assert "Circuit revisions using this tag" in content
    assert "Edit tag" not in content

    client.force_login(contributor)
    owner_detail = client.get(tag.get_absolute_url())
    assert "Edit tag" in owner_detail.content.decode()
    edit = client.post(
        reverse(
            "taxonomy:tag-edit",
            kwargs={"namespace": tag.namespace, "slug": tag.slug},
        ),
        {
            "label": "Repeated-memory experiment",
            "description": "Updated description.",
            "aliases": "memory repetition\nrepeated storage",
        },
    )
    assert edit.status_code == 302
    tag.refresh_from_db()
    assert tag.label == "Repeated-memory experiment"
    assert set(tag.aliases.filter(is_active=True).values_list("alias", flat=True)) == {
        "memory repetition",
        "repeated storage",
    }


def test_native_tag_usage_defaults_to_selected_tag_and_descendants(accounts, client):
    message_passing = Tag.objects.get(
        namespace=Tag.Namespace.ALGORITHM,
        slug="message-passing",
    )

    default = client.get(message_passing.get_absolute_url())
    exact = client.get(
        message_passing.get_absolute_url(),
        {"include_descendants": "0"},
    )

    assert default.context["include_descendants"] is True
    assert default.context["result_count"] == 1
    assert "Clear Matcher" in default.content.decode()
    assert "Show decoder versions tagged with this tag or any child of it" in (
        default.content.decode()
    )
    assert exact.context["include_descendants"] is False
    assert exact.context["result_count"] == 0


def test_native_experiment_parent_usage_uses_same_descendant_control(accounts, client):
    memory = Tag.objects.get(namespace=Tag.Namespace.EXPERIMENT, slug="memory")
    parent = create_custom_tag(
        submitter=accounts["contributor"],
        namespace=Tag.Namespace.EXPERIMENT,
        label="Storage experiment",
        description="A broad test-only experiment family.",
    ).tag
    TagParent.objects.create(child=memory, parent=parent)

    default = client.get(parent.get_absolute_url())
    exact = client.get(
        parent.get_absolute_url(),
        {"include_descendants": "0"},
    )

    assert default.context["result_count"] == 1
    assert "Show circuits tagged with this tag or any child of it" in (
        default.content.decode()
    )
    assert exact.context["result_count"] == 0


def test_multiple_parents_are_durable_and_cycles_are_rejected(accounts):
    contributor = accounts["contributor"]
    broad_a = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Broad method A",
        description="A broad method.",
    ).tag
    broad_b = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Broad method B",
        description="Another broad method.",
    ).tag
    child = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Narrow method",
        description="A narrower method.",
        parents=(broad_a, broad_b.id),
    ).tag

    assert set(child.parents.values_list("id", flat=True)) == {
        broad_a.id,
        broad_b.id,
    }

    with pytest.raises(TaxonomyValidationError, match="cycle"):
        update_tag(
            broad_a.id,
            actor=contributor,
            label=broad_a.label,
            description=broad_a.description,
            aliases=(),
            parents=(child,),
        )
    assert not broad_a.parents.exists()


def test_parent_tags_must_share_the_child_namespace(accounts):
    contributor = accounts["contributor"]
    code_parent = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.CODE,
        label="Example code family",
        description="A code-family parent.",
    ).tag
    algorithm = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Example decoder method",
        description="A decoder-method tag.",
    ).tag

    with pytest.raises(TaxonomyValidationError, match="same tag type"):
        create_custom_tag(
            submitter=contributor,
            namespace=Tag.Namespace.ALGORITHM,
            label="Invalid decoder child",
            description="This parent relationship crosses namespaces.",
            parents=(code_parent,),
        )
    with pytest.raises(TaxonomyValidationError, match="same tag type"):
        update_tag(
            algorithm.id,
            actor=contributor,
            label=algorithm.label,
            description=algorithm.description,
            aliases=(),
            parents=(code_parent,),
        )
    assert not algorithm.parents.exists()


def test_parent_edit_family_tree_and_contextual_picker(accounts, client):
    contributor = accounts["contributor"]
    grandparent = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Decoder family",
        description="A broad family.",
    ).tag
    parent = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Graph decoder",
        description="A graph-based family.",
        parents=(grandparent,),
    ).tag
    child = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Leaf decoder",
        description="A leaf family.",
        parents=(parent,),
    ).tag
    unrelated = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Unrelated decoder",
        description="No family relationships.",
    ).tag

    child_response = client.get(child.get_absolute_url())
    child_page = child_response.content.decode()
    assert child_response.context["tag_graph"]["open_by_default"]
    assert "Local graph" in child_page
    assert "Graph decoder" in child_page
    assert "Decoder family" not in child_page

    root_response = client.get(grandparent.get_absolute_url())
    assert root_response.context["tag_graph"]["open_by_default"]
    assert "Graph decoder" in root_response.content.decode()
    assert "Leaf decoder" not in root_response.content.decode()

    unrelated_response = client.get(unrelated.get_absolute_url())
    assert unrelated_response.context["tag_graph"]["is_trivial"]
    assert not unrelated_response.context["tag_graph"]["open_by_default"]

    client.force_login(contributor)
    submission_page = client.get(reverse("submissions:create", args=["decoder"]))
    content = submission_page.content.decode()
    assert "Parent tags" in content
    assert "Unselected parent tags" in content
    assert "(recommended)" not in content
    assert "data-dynamic-tag-parent-selector" in content
    assert "Search possible parent tags" in content

    edit = client.post(
        reverse(
            "taxonomy:tag-edit",
            kwargs={"namespace": child.namespace, "slug": child.slug},
        ),
        {
            "label": child.label,
            "description": child.description,
            "aliases": "",
            "parents": [str(grandparent.id), str(parent.id)],
        },
    )
    assert edit.status_code == 302
    assert set(child.parents.values_list("id", flat=True)) == {
        grandparent.id,
        parent.id,
    }
    assert child.record_events.filter(
        action=RecordEvent.Action.EDITED,
        details__changed_fields__contains=["parents"],
    ).exists()

    ordinary_picker = client.get(reverse("decoders:list")).content.decode()
    assert "Unselected parent tags" in ordinary_picker
    assert "(recommended)" not in ordinary_picker

    creation_page = client.get(reverse("taxonomy:tag-create")).content.decode()
    assert "Unselected parent tags" in creation_page
    assert "(recommended)" in creation_page


def test_taxonomy_validator_detects_out_of_band_cycle(accounts):
    contributor = accounts["contributor"]
    first = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="First cycle node",
        description="First node.",
    ).tag
    second = create_custom_tag(
        submitter=contributor,
        namespace=Tag.Namespace.ALGORITHM,
        label="Second cycle node",
        description="Second node.",
    ).tag
    TagParent.objects.create(child=first, parent=second)
    TagParent.objects.create(child=second, parent=first)

    with pytest.raises(CommandError, match="cycle"):
        call_command("validate_tag_taxonomy")
