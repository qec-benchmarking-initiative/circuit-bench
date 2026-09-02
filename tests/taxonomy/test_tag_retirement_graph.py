import pytest
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import RecordEvent, Tag, TagParent
from registry.services.tags import active_tag_queryset
from registry.services.taxonomy import (
    TaxonomyPermissionError,
    can_retire_tag,
    create_custom_tag,
    promote_tag_official,
    retire_tag,
)
from registry.tag_taxonomy_graph import build_local_tag_graph

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def production_urls(settings):
    settings.ROOT_URLCONF = "config.urls"


@pytest.fixture
def actors():
    seed_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "owner": Account.objects.get(id=demo_id("account/contributor")),
        "outsider": Account.objects.create_user(display_name="Other Taxonomist"),
    }


def _tag(owner, label, *, parents=()):
    return create_custom_tag(
        submitter=owner,
        namespace=Tag.Namespace.ALGORITHM,
        label=label,
        description=f"Description for {label}.",
        parents=parents,
    ).tag


def test_custom_owner_and_official_admin_have_distinct_delete_authority(actors):
    owner = actors["owner"]
    admin = actors["admin"]
    outsider = actors["outsider"]
    community = _tag(owner, "Community deletion test")

    assert can_retire_tag(community, owner)
    assert not can_retire_tag(community, outsider)
    assert not can_retire_tag(community, admin)
    with pytest.raises(TaxonomyPermissionError):
        retire_tag(community.id, actor=outsider)

    retired = retire_tag(community.id, actor=owner)
    assert retired.status == Tag.Status.RETIRED
    assert not can_retire_tag(retired, owner)
    assert not active_tag_queryset().filter(id=retired.id).exists()
    event = retired.record_events.get(action=RecordEvent.Action.RETIRED)
    assert event.actor_account == owner
    assert event.details == {
        "policy_version": "0.1",
        "previous_status": "custom",
        "new_status": "retired",
        "public_action": "deleted",
    }

    official = _tag(owner, "Official deletion test")
    promote_tag_official(official.id, curator=admin, display_color="#315F7D")
    official.refresh_from_db()
    assert not can_retire_tag(official, owner)
    assert can_retire_tag(official, admin)
    with pytest.raises(TaxonomyPermissionError):
        retire_tag(official.id, actor=owner)
    assert retire_tag(official.id, actor=admin).status == Tag.Status.RETIRED


def test_delete_confirmation_preserves_edges_and_marks_deleted_parent(actors, client):
    owner = actors["owner"]
    parent = _tag(owner, "Disposable parent")
    child = _tag(owner, "Durable child", parents=(parent,))
    relationship_pk = TagParent.objects.get(child=child, parent=parent).pk

    delete_url = reverse(
        "taxonomy:tag-delete",
        kwargs={"namespace": parent.namespace, "slug": parent.slug},
    )
    client.force_login(actors["outsider"])
    assert client.get(delete_url).status_code == 403

    client.force_login(owner)
    confirmation = client.get(delete_url)
    assert confirmation.status_code == 200
    assert "existing uses, and taxonomy relationships will remain" in (
        confirmation.content.decode()
    )
    response = client.post(delete_url)
    assert response.status_code == 302
    parent.refresh_from_db()
    assert parent.status == Tag.Status.RETIRED
    assert TagParent.objects.filter(pk=relationship_pk).exists()

    detail = client.get(child.get_absolute_url())
    graph_nodes = detail.context["tag_graph"]["payload"]["nodes"]
    deleted_parent = next(node for node in graph_nodes if node["id"] == str(parent.id))
    assert deleted_parent["deleted"]
    retired_detail = client.get(parent.get_absolute_url()).content.decode()
    assert "Delete tag" not in retired_detail
    assert "Edit tag" not in retired_detail
    assert "Deleted" in retired_detail

    edit = client.get(
        reverse(
            "taxonomy:tag-edit",
            kwargs={"namespace": child.namespace, "slug": child.slug},
        )
    ).content.decode()
    assert "tag-deleted-label" in edit
    assert "(Deleted)" in edit


def test_local_graph_contains_all_displayed_edges_and_boundary_counts(actors):
    owner = actors["owner"]
    grandparent = _tag(owner, "Grandparent")
    parent_b = _tag(owner, "Parent B")
    parent_a = _tag(owner, "Parent A", parents=(grandparent, parent_b))
    focus = _tag(owner, "Focus", parents=(parent_a, parent_b))
    child_a = _tag(owner, "Child A", parents=(focus, parent_b))
    child_b = _tag(owner, "Child B", parents=(focus,))
    _tag(owner, "Grandchild", parents=(child_a,))
    _tag(owner, "Hidden sibling", parents=(parent_a,))

    graph = build_local_tag_graph(focus)
    payload = graph["payload"]
    assert graph["open_by_default"]
    assert not graph["is_trivial"]
    assert {(node["label"], node["layer"]) for node in payload["nodes"]} == {
        ("Parent A", "parent"),
        ("Parent B", "parent"),
        ("Focus", "current"),
        ("Child A", "child"),
        ("Child B", "child"),
    }
    assert {(edge["child"], edge["parent"]) for edge in payload["edges"]} == {
        (str(parent_a.id), str(parent_b.id)),
        (str(focus.id), str(parent_a.id)),
        (str(focus.id), str(parent_b.id)),
        (str(child_a.id), str(focus.id)),
        (str(child_a.id), str(parent_b.id)),
        (str(child_b.id), str(focus.id)),
    }
    by_label = {node["label"]: node for node in payload["nodes"]}
    assert by_label["Parent A"]["hidden_parent_count"] == 1
    assert by_label["Parent A"]["hidden_child_count"] == 1
    assert by_label["Child A"]["hidden_child_count"] == 1

    trivial = build_local_tag_graph(_tag(owner, "Trivial"))
    assert trivial["is_trivial"]
    assert not trivial["open_by_default"]
    assert trivial["payload"]["edges"] == []
