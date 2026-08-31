import pytest
from django.urls import reverse

from registry.demo import seed_demo_data
from registry.models import Machine

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_demo_data()


def test_result_explorer_uses_all_three_reusable_filter_grids(client):
    response = client.get(reverse("results:list"))

    assert response.status_code == 200
    assert response.context["result_count"] == 1
    content = response.content.decode()
    assert 'id="result-algorithm-filters"' in content
    assert 'id="result-circuit-filters"' in content
    assert 'id="result-machine-filters"' in content
    assert content.count('class="filter-grid"') == 3
    assert 'name="decoder_priors"' in content
    assert 'name="circuit_priors"' in content
    assert 'aria-label="Clear Prior preparation filter"' in content
    assert 'aria-label="Clear Noise model filter"' in content
    assert 'aria-current="page"' in content
    machine = Machine.objects.get(slug="demo-eight-core-cpu")
    assert reverse("machines:detail", args=[machine.slug]) in content
    result_url = reverse(
        "results:detail", args=[response.context["ordered_result_ids"][0]]
    )
    assert result_url in content
    assert "0.15 probability" in content
    assert "2.5e7 ns" in content
    assert "02300000000000000000" not in content


def test_result_metrics_are_independent_sortable_columns(client):
    response = client.get(
        reverse("results:list"),
        {
            "sort": "score_ler_upper_95_at_5pct_acceptance_v0_1,t_1000_ns",
            "columns": ("decoder,score_ler_upper_95_at_5pct_acceptance_v0_1,t_1000_ns"),
        },
    )

    assert response.status_code == 200
    assert response.context["sort_summary"] == (
        "LER upper 95% @ 5% ascending, t₁₀₀₀ (ns) ascending"
    )
    content = response.content.decode()
    assert 'data-sort-key="score_ler_upper_95_at_5pct_acceptance_v0_1"' in content
    assert 'data-sort-key="t_1000_ns"' in content


def test_result_explorer_combines_algorithm_circuit_and_machine_filters(client):
    url = reverse("results:list")
    matching = client.get(
        url,
        {
            "algorithm_tag": "matching",
            "decoder_priors": "not_required",
            "code_tag": "rotated-surface-code",
            "circuit_priors": "no",
            "machine_class": "cpu",
        },
    )
    wrong_decoder = client.get(url, {"decoder_priors": "required"})
    wrong_circuit = client.get(url, {"circuit_priors": "yes"})
    wrong_machine = client.get(url, {"machine_class": "gpu"})

    assert matching.context["result_count"] == 1
    assert wrong_decoder.context["result_count"] == 0
    assert wrong_circuit.context["result_count"] == 0
    assert wrong_machine.context["result_count"] == 0
    assert matching.context["algorithm_filter_grid"]["applied_count"] == 2
    assert matching.context["circuit_filter_grid"]["applied_count"] == 2
    assert matching.context["machine_filter_grid"]["applied_count"] == 1
    matching_content = matching.content.decode()
    assert matching_content.count(", 2 applied") == 2
    assert matching_content.count(", 1 applied") == 1


def test_result_explorer_accepts_multiple_noise_models_as_scalar_in_filter(client):
    url = reverse("results:list")
    both = client.get(
        url,
        {
            "noise_model": [
                "randomised-phenomenological",
                "fixed-phenomenological",
            ]
        },
    )
    randomised_only = client.get(
        url,
        {"noise_model": "randomised-phenomenological"},
    )

    assert both.context["result_count"] == 1
    assert randomised_only.context["result_count"] == 0
    assert "Randomised phenomenological noise +1" in both.content.decode()


def test_result_explorer_table_sort_and_columns_are_url_backed(client):
    response = client.get(
        reverse("results:list"),
        {"columns": "decoder,circuit,shots", "sort": "-shots,decoder"},
    )

    assert [column["key"] for column in response.context["table_columns"]] == [
        "decoder",
        "circuit",
        "shots",
    ]
    assert response.context["sort_summary"] == "Shots descending, Decoder ascending"
    assert b"Clear Matcher" in response.content
    assert b"Rotated surface-code memory d=5" in response.content


def test_raw_odata_query_updates_table_status_and_export_urls(client):
    raw = (
        "$filter=machine_class eq 'cpu'&"
        "$orderby=score_ler_upper_95_at_5pct_acceptance_v0_1 asc"
    )
    response = client.get(reverse("results:list"), {"odata": raw})

    assert response.status_code == 200
    assert response.context["result_count"] == 1
    assert response.context["scripted_query_status"]["kind"] == "success"
    assert response.context["last_valid_scripted_query"] == raw
    assert "%24filter=machine_class+eq+%27cpu%27" in response.context["json_url"]
    assert "Syntax and field reference" in response.content.decode()


def test_invalid_raw_query_keeps_last_valid_population_visible(client):
    previous = "$filter=machine_class eq 'cpu'&$orderby=t_1000_ns asc"
    response = client.get(
        reverse("results:list"),
        {
            "odata": "$filter=invented_metric lt 1",
            "last_odata": previous,
        },
    )

    assert response.status_code == 200
    assert response.context["result_count"] == 1
    status = response.context["scripted_query_status"]
    assert status["kind"] == "error"
    assert "Unknown filterable field" in status["message"]
    assert "character 0" in status["message"]
    assert "Last valid results remain visible" in status["message"]
    assert response.context["last_valid_scripted_query"] == previous


def test_browser_and_json_links_return_same_ordered_ids(client):
    browser = client.get(
        reverse("results:list"),
        {"machine_class": "cpu", "sort": "t_1000_ns"},
    )
    api = client.get(browser.context["json_url"])

    assert api.status_code == 200
    assert api.json()["ordered_result_ids"] == browser.context["ordered_result_ids"]
