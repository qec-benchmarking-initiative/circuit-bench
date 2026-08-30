import pytest
from django.urls import reverse

from registry.demo import seed_demo_data

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
    assert 'aria-current="page"' in content


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
