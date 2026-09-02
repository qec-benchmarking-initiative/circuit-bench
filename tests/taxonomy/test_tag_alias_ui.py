import pytest
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import RecordEvent, Tag, TagAlias
from registry.services.taxonomy import (
    TaxonomyPermissionError,
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
        label="Union find",
        description="Uses disjoint-set merging.",
        aliases=("UF", "Disjoint set"),
    ).tag

    assert tag.slug == "union-find"
    assert set(tag.aliases.filter(is_active=True).values_list("alias", flat=True)) == {
        "UF",
        "Disjoint set",
    }
    assert set(
        tag.record_events.filter(action=RecordEvent.Action.ADDED_ALIAS).values_list(
            "details__alias", flat=True
        )
    ) == {"UF", "Disjoint set"}

    update_tag(
        tag.id,
        actor=contributor,
        label="Union–find",
        description="Uses a disjoint-set data structure.",
        aliases=("Disjoint set", "Union find decoder"),
    )

    assert set(tag.aliases.filter(is_active=True).values_list("alias", flat=True)) == {
        "Disjoint set",
        "Union find decoder",
    }
    removed = TagAlias.objects.get(tag=tag, alias="UF")
    assert not removed.is_active
    assert removed.removed_by == contributor
    assert removed.removed_at is not None
    assert tag.record_events.filter(
        action=RecordEvent.Action.REMOVED_ALIAS,
        details__alias="UF",
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
    response = client.post(
        reverse("taxonomy:tag-create-json"),
        {
            "namespace": "algorithm",
            "label": "Peeling decoder",
            "description": "Iteratively removes degree-one checks.",
            "aliases": "leaf removal\npeeling",
        },
    )

    assert response.status_code == 201
    payload = response.json()["tag"]
    assert payload["aliases"] == ["leaf removal", "peeling"]
    assert payload["url"] == "/tags/algorithm/peeling-decoder/"

    form_page = client.get(reverse("submissions:create", args=["decoder"]))
    content = form_page.content.decode()
    assert 'data-tag-alias="leaf removal"' in content
    assert "Please check carefully if there is an existing tag" in content
    assert reverse("taxonomy:tag-create-json") in content

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
    assert "Submission history" in content
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
