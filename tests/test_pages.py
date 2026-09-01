from collections import Counter
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from pages.daily_quotes import (
    UNIX_EPOCH_DATE,
    load_daily_quotes,
    quote_display_parts,
    quote_for_date,
    quote_window_for_date,
)


def test_home_page_uses_shared_shell(client, db):
    response = client.get(reverse("pages:home"))
    assert response.status_code == 200
    assert b"Circuit Bench" in response.content
    assert b"Search the registry" in response.content
    assert b'class="home-title-logo"' in response.content
    assert b'class="home-daily-quote"' in response.content
    assert b"Copyright Stasiu Wolanski 2026" in response.content
    assert response.context["daily_quote"] == quote_for_date(timezone.localdate())
    assert (
        f'href="{response.context["daily_quote"].source_url}"'
        in response.content.decode()
    )
    site_name = response.content.decode().split('<a class="site-name"', 1)[1]
    site_name = site_name.split("</a>", 1)[0]
    assert 'href="/"' in site_name
    assert 'class="site-name-logo"' in site_name
    assert "Circuit Bench" in site_name
    search_row = response.content.decode().split('<div class="input-row">', 1)[1]
    search_row = search_row.split("</div>", 1)[0]
    assert search_row.index('id="site-search"') < search_row.index(">Search</button>")


def test_daily_quote_collection_is_large_and_well_formed():
    quotes = load_daily_quotes()
    words_by_source = Counter()
    for item in quotes:
        words_by_source[item.source_url] += len(item.quote_original.split())

    assert len(quotes) >= 100
    assert len(
        {(item.quote_original, item.speaker, item.work) for item in quotes}
    ) == len(quotes)
    assert {item.speaker_kind for item in quotes} <= {"character", "person"}
    assert all(len(item.quote_original.split()) <= 25 for item in quotes)
    assert all(word_count <= 25 for word_count in words_by_source.values())
    assert Counter(item.decision for item in quotes) == {
        "accepted": 111,
        "weak_accepted": 26,
    }
    assert all(
        item.id and item.selected_variant and item.source_file for item in quotes
    )


def test_daily_quote_rotates_in_collection_order(monkeypatch):
    quotes = load_daily_quotes()[:3]
    monkeypatch.setattr("pages.daily_quotes.load_daily_quotes", lambda: quotes)

    assert quote_for_date(UNIX_EPOCH_DATE) == quotes[0]
    assert quote_for_date(UNIX_EPOCH_DATE + timedelta(days=1)) == quotes[1]
    assert quote_for_date(UNIX_EPOCH_DATE, day_offset=2) == quotes[2]
    assert quote_for_date(UNIX_EPOCH_DATE, day_offset=3) == quotes[0]


def test_daily_quote_window_has_three_previous_and_five_following(monkeypatch):
    quotes = load_daily_quotes()[:12]
    monkeypatch.setattr("pages.daily_quotes.load_daily_quotes", lambda: quotes)

    window = quote_window_for_date(UNIX_EPOCH_DATE, day_offset=4)

    assert [item.relative_day for item in window] == list(range(-3, 6))
    assert [item.collection_index for item in window] == list(range(1, 10))
    assert [item.quote for item in window] == list(quotes[1:10])
    assert [item.relative_label for item in window] == [
        "-3 days",
        "-2 days",
        "-1 day",
        "Current",
        "+1 day",
        "+2 days",
        "+3 days",
        "+4 days",
        "+5 days",
    ]


def test_stored_quote_kets_receive_structured_display_parts():
    parts = quote_display_parts("This isn't a democracy, mother|1010⟩r!")

    assert "".join(part.text for part in parts) == (
        "This isn't a democracy, mother|1010⟩r!"
    )
    assert [part.text for part in parts if part.is_ket] == ["|1010⟩"]


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
