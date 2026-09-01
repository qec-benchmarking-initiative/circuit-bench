import pytest
from django.urls import reverse

from registry.demo import seed_demo_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_demo_data()


@pytest.mark.parametrize(
    ("route_name", "route_args"),
    [
        ("decoders:list", ()),
        ("circuits:list", ()),
        ("noise-models:list", ()),
        ("results:list", ()),
        ("circuits:detail", ("rotated-memory-d5",)),
        ("decoders:detail", ("clear-matcher-0-2",)),
    ],
)
def test_filter_forms_share_autoquery_controls(client, route_name, route_args):
    response = client.get(reverse(route_name, args=route_args))
    content = response.content.decode()

    assert response.status_code == 200
    assert content.count("data-autoquery-toggle") == 1
    assert content.count("data-filter-apply") == 1
    assert 'data-manual-label="Apply filters"' in content
    assert "/static/js/filter-query.js" in content
