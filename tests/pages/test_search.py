import pytest
from django.urls import reverse

from registry.demo_plotting import seed_plot_demo_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_plot_demo_data()


def test_home_search_posts_to_a_real_registry_search(client):
    home = client.get(reverse("pages:home")).content.decode()

    assert f'action="{reverse("pages:search")}"' in home
    response = client.get(reverse("pages:search"), {"q": "rotated"})

    assert response.status_code == 200
    assert response.context["match_count"] >= 1
    assert "Rotated surface-code memory d=5" in response.content.decode()
    assert (
        reverse("circuits:detail", args=["rotated-memory-d5"])
        in response.content.decode()
    )


def test_search_groups_public_registry_kinds_and_handles_no_matches(client):
    response = client.get(reverse("pages:search"), {"q": "no-such-record"})

    assert response.status_code == 200
    assert response.context["match_count"] == 0
    content = response.content.decode()
    for heading in ("Circuits", "Decoders", "Benchmarks", "Noise models"):
        assert f"<h2>{heading}</h2>" in content
    assert content.count("No matches.") == 4
