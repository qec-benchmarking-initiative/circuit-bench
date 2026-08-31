import pytest
from django.urls import reverse

from registry.demo import seed_demo_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_demo_data()


@pytest.mark.parametrize(
    "route_name",
    (
        "decoders:list",
        "circuits:list",
        "noise-models:list",
        "benchmarks:list",
    ),
)
def test_unfiltered_catalogues_disclose_provisional_featured_policy(client, route_name):
    response = client.get(reverse(route_name))

    assert response.status_code == 200
    assert response.context["discovery_ordering"]["key"] == "featured"
    assert response.context["discovery_ordering"]["provisional"] is True
    assert (
        "not a scientific ranking"
        in response.context["discovery_ordering"]["explanation"]
    )
    assert "disclosed provisional policy" in response.content.decode()


def test_search_relevance_and_explicit_sort_remain_separate(client):
    searched = client.get(reverse("decoders:list"), {"q": "clear"})
    manually_sorted = client.get(
        reverse("decoders:list"), {"q": "clear", "sort": "name"}
    )

    assert searched.context["discovery_ordering"]["key"] == "search_relevance"
    assert searched.context["sort_summary"] == "Search relevance"
    assert manually_sorted.context["discovery_ordering"]["key"] == "manual"
    assert manually_sorted.context["sort_summary"] == "Decoder ascending"
