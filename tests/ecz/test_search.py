import pytest

from registry.demo import seed_demo_data
from registry.models import EczTerm, Tag
from registry.services.ecz_sync import (
    apply_prepared_sync,
    prepare_sync,
    source_for_directory,
)
from registry.services.taxonomy_search import search_taxonomy_terms

from .test_sync import FIXTURES

pytestmark = pytest.mark.django_db


@pytest.fixture
def searchable_taxonomy():
    seed_demo_data()
    source = source_for_directory(FIXTURES / "snapshot_a")
    apply_prepared_sync(
        prepare_sync(source=source, source_directory=FIXTURES / "snapshot_a")
    )


def test_search_counts_and_pages_sources_independently(searchable_taxonomy):
    result = search_taxonomy_terms(
        namespace=Tag.Namespace.CODE,
        query="code",
        page_size=1,
    )
    assert result.circuit_bench.total >= 1
    assert len(result.circuit_bench.shown) == 1
    assert result.circuit_bench.remaining == result.circuit_bench.total - 1
    assert result.ecz.total == 3
    assert len(result.ecz.shown) == 1
    assert result.ecz.remaining == 2
    assert result.ecz.next_offset == 1


def test_selected_terms_remain_visible_and_direct_parent_is_separate(
    searchable_taxonomy,
):
    surface = EczTerm.objects.get(ecz_code_id="surface")
    result = search_taxonomy_terms(
        namespace=Tag.Namespace.CODE,
        query="planar",
        selected_keys=[f"ecz:{surface.ecz_code_id}"],
    )
    assert [item.key for item in result.selected] == ["ecz:surface"]
    assert any(item.key == "ecz:planar" for item in result.ecz.shown)
    assert any(item.key == "ecz:root" for item in result.parent_ecz.shown)
    assert result.parent_ecz.total == 1


def test_blank_unselected_search_has_no_parent_section(searchable_taxonomy):
    result = search_taxonomy_terms(
        namespace=Tag.Namespace.CODE,
        query="",
        selected_keys=[],
    )
    assert result.parent_circuit_bench.total == 0
    assert result.parent_ecz.total == 0


def test_http_endpoint_returns_namespaced_blue_dashed_ecz_result(
    client, searchable_taxonomy
):
    response = client.get(
        "/pickers/taxonomy-terms/",
        {"namespace": "code", "q": "surface"},
    )
    assert response.status_code == 200
    payload = response.json()
    item = next(
        item for item in payload["ecz"]["shown"] if item["key"] == "ecz:surface"
    )
    assert item["source_suffix"] == "(ECZ)"
    assert item["border_style"] == "dashed"
    assert item["url"] == "/ecz/surface/"
