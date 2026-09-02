import pytest
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import CircuitRevision, EczTerm, Tag
from registry.services.ecz_sync import (
    apply_prepared_sync,
    prepare_sync,
    source_for_directory,
)

from .test_sync import FIXTURES

pytestmark = pytest.mark.django_db


@pytest.fixture
def ecz_pages():
    seed_demo_data()
    source = source_for_directory(FIXTURES / "snapshot_a")
    apply_prepared_sync(
        prepare_sync(source=source, source_directory=FIXTURES / "snapshot_a")
    )
    surface = EczTerm.objects.get(ecz_code_id="surface")
    root = EczTerm.objects.get(ecz_code_id="root")
    circuit = CircuitRevision.objects.filter(state="published").first()
    circuit.ecz_terms.add(surface)
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
        "surface": surface,
        "root": root,
        "circuit": circuit,
        "code_tag": Tag.objects.filter(namespace=Tag.Namespace.CODE).first(),
    }


def test_ecz_stub_links_authority_provenance_graph_and_circuits(client, ecz_pages):
    response = client.get(ecz_pages["surface"].get_absolute_url())
    assert response.status_code == 200
    content = response.content.decode()
    assert "Error Correction Zoo is the source of truth" in content
    assert "https://errorcorrectionzoo.org/c/surface" in content
    assert "Combined local graph" in content
    assert "data-taxonomy-graph-viewport" in content
    assert content.count("data-taxonomy-graph-overflow=") == 2
    assert "CC BY-SA 4.0" in content
    assert ecz_pages["circuit"].name in content
    assert "Create equivalence mapping" not in content


def test_ecz_usage_table_defaults_to_descendants_and_has_complete_controls(
    client, ecz_pages
):
    response = client.get(ecz_pages["root"].get_absolute_url())
    content = response.content.decode()

    assert response.context["include_descendants"] is True
    assert response.context["result_count"] == 1
    assert ecz_pages["circuit"].name in content
    assert "Show circuits tagged with this tag or any child of it" in content
    assert 'name="include_descendants"' in content
    assert 'value="1"' in content
    assert "checked" in content
    assert 'data-raw="1"' in content
    assert "record" in content
    assert "Sort: Circuit ascending" in content
    assert "Table view options (10/10)" in content
    assert 'data-sort-key="name"' in content
    assert 'data-sort-key="detectors"' in content
    assert "Circuits tagged with Root code" in content
    assert "using this ECZ identity" not in content
    assert "Imported identity" not in content

    exact = client.get(
        ecz_pages["root"].get_absolute_url(),
        {"include_descendants": "0"},
    )
    assert exact.context["include_descendants"] is False
    assert exact.context["result_count"] == 0


def test_ecz_usage_search_sort_and_column_state_are_url_backed(client, ecz_pages):
    circuit = ecz_pages["circuit"]
    response = client.get(
        ecz_pages["root"].get_absolute_url(),
        {
            "q": circuit.name.split()[0],
            "sort": "-detectors,name",
            "columns": "name,detectors,results",
        },
    )
    content = response.content.decode()

    assert response.context["result_count"] == 1
    assert response.context["sort_summary"] == (
        "Detectors descending, Circuit ascending"
    )
    assert [column["key"] for column in response.context["table_columns"]] == [
        "name",
        "detectors",
        "results",
    ]
    assert "Table view options (3/10)" in content
    assert "1↓" in content
    assert "2↑" in content
    assert "noise_model" not in response.context["visible_column_keys"]

    no_match = client.get(
        ecz_pages["root"].get_absolute_url(),
        {"q": "no-such-circuit", "include_descendants": "1"},
    )
    assert no_match.context["result_count"] == 0
    no_match_content = no_match.content.decode()
    assert 'data-raw="0"' in no_match_content
    assert "records" in no_match_content


def test_ecz_graph_edges_use_renderable_code_ids_and_ecz_source(client, ecz_pages):
    response = client.get(ecz_pages["surface"].get_absolute_url())
    edges = response.context["tag_graph"]["payload"]["edges"]

    assert {
        "child": "ecz:surface",
        "parent": "ecz:root",
        "source": "ecz",
    } in edges
    assert {
        "child": "ecz:planar",
        "parent": "ecz:surface",
        "source": "ecz",
    } in edges
    assert "tag-taxonomy-graph.js?v=0.1.20260902q" in response.content.decode()


def test_sync_status_is_admin_only(client, ecz_pages):
    client.force_login(ecz_pages["contributor"])
    assert client.get(reverse("taxonomy:ecz-status")).status_code == 403
    client.force_login(ecz_pages["admin"])
    response = client.get(reverse("taxonomy:ecz-status"))
    assert response.status_code == 200
    assert "3" in response.content.decode()
    assert "Synchronisation runs" in response.content.decode()


def test_admin_can_create_and_revoke_mapping_through_ui(client, ecz_pages):
    client.force_login(ecz_pages["admin"])
    create = client.post(
        reverse("taxonomy:ecz-mapping-create"),
        {
            "tag": str(ecz_pages["code_tag"].id),
            "ecz_term": str(ecz_pages["surface"].id),
            "note": "The native term is equivalent to this ECZ identity.",
        },
    )
    assert create.status_code == 302
    mapping = ecz_pages["code_tag"].ecz_mappings.get(status="active")
    revoke = client.post(
        reverse("taxonomy:ecz-mapping-revoke", args=[mapping.id]),
        {"note": "The concepts are not exactly equivalent."},
    )
    assert revoke.status_code == 302
    mapping.refresh_from_db()
    assert mapping.status == "revoked"
