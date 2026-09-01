import pytest
from django.urls import reverse

from registry.demo import seed_demo_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_demo_data()


def test_noise_model_picker_searches_public_records_with_official_first(client):
    response = client.get(
        reverse("pickers:records", args=["noise-models"]),
        {"q": "phenomenological", "page": "1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [record["identifier"] for record in payload["results"]] == [
        "fixed-phenomenological",
        "randomised-phenomenological",
    ]
    assert [record["curation_status"] for record in payload["results"]] == [
        "official",
        "community",
    ]
    assert payload["pagination"] == {
        "page": 1,
        "pages": 1,
        "has_previous": False,
        "has_next": False,
    }


def test_noise_model_picker_searches_name_slug_and_description(client):
    endpoint = reverse("pickers:records", args=["noise-models"])

    by_slug = client.get(endpoint, {"q": "randomised-phenomenological"}).json()
    by_description = client.get(endpoint, {"q": "fixed-prior"}).json()

    assert [record["identifier"] for record in by_slug["results"]] == [
        "randomised-phenomenological"
    ]
    assert [record["identifier"] for record in by_description["results"]] == [
        "fixed-phenomenological"
    ]


def test_unconfigured_record_picker_is_not_exposed(client):
    response = client.get(reverse("pickers:records", args=["accounts"]))
    assert response.status_code == 404


def test_artifact_picker_searches_frozen_identity_and_paginates(client):
    response = client.get(
        reverse("pickers:records", args=["artifacts"]),
        {"q": "demo-memory.stim"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 1
    record = payload["results"][0]
    assert record["label"] == "demo-memory.stim"
    assert record["curation_status"] == "frozen"
    assert "bytes" in record["secondary_label"]
    assert record["detail_url"].startswith("/artifacts/")
