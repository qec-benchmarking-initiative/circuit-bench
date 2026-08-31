import csv
import json
from io import StringIO

import pytest
from django.urls import reverse

from registry.demo import seed_demo_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_demo_data()


def test_json_api_returns_versioned_exact_projection(client):
    response = client.get(
        reverse("results:api-json"),
        {
            "$filter": "machine_class eq 'cpu'",
            "$orderby": "score_ler_upper_95_at_5pct_acceptance_v0_1 asc",
            "$select": (
                "id,decoder_name,circuit_name,"
                "score_ler_upper_95_at_5pct_acceptance_v0_1,t_1000_ns"
            ),
            "$count": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "result-record/0.1"
    assert payload["live"] is True
    assert payload["count"] == 1
    assert len(payload["ordered_result_ids"]) == 1
    assert payload["records"][0]["decoder_name"] == "Clear Matcher"
    assert payload["records"][0]["t_1000_ns"] == 25_000_000
    assert (
        payload["records"][0]["score_ler_upper_95_at_5pct_acceptance_v0_1"]
        == "0.15000000000000000000"
    )
    assert payload["selected_fields"][-2]["unit"] == "probability"
    assert "%24filter=" in payload["links"]["csv"]


def test_csv_api_has_same_order_and_exact_values(client):
    options = {
        "$orderby": "t_1000_ns asc",
        "$select": "id,decoder_name,t_1000_ns",
    }
    json_response = client.get(reverse("results:api-json"), options).json()
    csv_response = client.get(reverse("results:api-csv"), options)
    rows = list(csv.DictReader(StringIO(csv_response.content.decode())))

    assert csv_response.status_code == 200
    assert [row["id"] for row in rows] == json_response["ordered_result_ids"]
    assert rows[0]["t_1000_ns"] == "25000000"
    assert csv_response["X-Circuit-Bench-Schema"] == "result-record/0.1"
    assert csv_response["X-Total-Count"] == "1"


def test_api_schema_publishes_metric_units_and_definition_links(client):
    response = client.get(reverse("results:api-schema"))
    fields = {field["name"]: field for field in response.json()["fields"]}

    assert response.status_code == 200
    assert fields["t_1000_ns"]["unit"] == "ns"
    assert (
        fields["score_ler_upper_95_at_5pct_acceptance_v0_1"]["direction"]
        == "lower_is_better"
    )


def test_invalid_api_query_is_stable_json_error(client):
    response = client.get(
        reverse("results:api-json"),
        {"$filter": "invented_metric lt 1"},
    )

    assert response.status_code == 400
    assert response["Content-Type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "unknown_field",
            "message": "Unknown filterable field: invented_metric",
            "position": 0,
        }
    }


def test_json_is_valid_without_selected_id(client):
    response = client.get(
        reverse("results:api-json"), {"$select": "decoder_name", "$top": "1"}
    )

    json.loads(response.content)
    assert response.json()["ordered_result_ids"] == []


def test_api_reuses_browser_filter_parameters(client):
    manual = client.get(
        reverse("results:api-json"),
        {"machine_class": "cpu", "$orderby": "published_at desc"},
    ).json()
    scripted = client.get(
        reverse("results:api-json"),
        {
            "$filter": "machine_class eq 'cpu'",
            "$orderby": "published_at desc",
        },
    ).json()

    assert manual["ordered_result_ids"] == scripted["ordered_result_ids"]
    assert "machine_class=cpu" in manual["links"]["self"]
