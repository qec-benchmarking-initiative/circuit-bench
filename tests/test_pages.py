import pytest
from django.urls import reverse


def test_home_page_uses_shared_shell(client):
    response = client.get(reverse("pages:home"))
    assert response.status_code == 200
    assert b"Circuit Bench" in response.content
    assert b"Search the registry" in response.content
    assert b"Copyright Stasiu Wolanski 2026" in response.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_name", "search_id"),
    [
        ("pages:home", "site-search"),
        ("circuits:list", "circuit-search"),
        ("decoders:list", "decoder-search"),
        ("benchmarks:list", "benchmark-search"),
        ("noise-models:list", "noise-search"),
        ("results:list", "result-query"),
    ],
)
def test_primary_search_is_autofocused(client, route_name, search_id):
    content = client.get(reverse(route_name)).content.decode()
    search_input = content.split(f'id="{search_id}"', 1)[1].split(">", 1)[0]

    assert "autofocus" in search_input


def test_primary_navigation_has_the_reference_work_order(client, db):
    content = client.get(reverse("pages:home")).content.decode()

    nav = content.split('<nav aria-label="Primary navigation">', 1)[1].split(
        "</nav>", 1
    )[0]
    assert nav.index(">Circuits</a>") < nav.index(">Decoders</a>")
    assert nav.index(">Decoders</a>") < nav.index(">Benchmarks</a>")
    assert nav.index(">Benchmarks</a>") < nav.index(">Noise models</a>")
    assert nav.index(">Noise models</a>") < nav.index(">All results</a>")
    assert 'class="nav-secondary" href="/noise-models/"' in nav
    assert 'class="nav-secondary" href="/results/"' in nav

    noise_content = client.get("/noise-models/").content.decode()
    noise_nav = noise_content.split('<nav aria-label="Primary navigation">', 1)[
        1
    ].split("</nav>", 1)[0]
    assert 'class="nav-secondary active"' in noise_nav
    assert 'aria-current="page">Noise models</a>' in noise_nav

    results_content = client.get("/results/").content.decode()
    results_nav = results_content.split('<nav aria-label="Primary navigation">', 1)[
        1
    ].split("</nav>", 1)[0]
    assert 'class="nav-secondary active" href="/results/"' in results_nav
    assert 'aria-current="page">All results</a>' in results_nav


def test_component_gallery_renders_difficult_states(client, settings):
    settings.DEBUG = True
    response = client.get(reverse("pages:component-gallery"))
    assert response.status_code == 200
    assert b"Component gallery" in response.content
    assert b"Valid query" in response.content
    assert b"No matching results" in response.content


def test_component_gallery_is_not_available_in_production(client, settings):
    settings.DEBUG = False
    assert client.get(reverse("pages:component-gallery")).status_code == 404
