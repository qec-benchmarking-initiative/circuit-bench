import pytest
from django.urls import reverse

from registry.demo import seed_demo_data
from registry.models import Machine

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def demo_registry():
    seed_demo_data()


def test_machine_detail_is_a_scientific_record_with_reverse_results(client):
    machine = Machine.objects.get(slug="demo-eight-core-cpu")
    response = client.get(reverse("machines:detail", args=[machine.slug]))

    assert response.status_code == 200
    assert response.context["result_count"] == 1
    content = response.content.decode()
    assert "Synthetic eight-core CPU environment" in content
    assert "Physical evidence" in content
    assert "Clear Matcher" in content
    assert "Rotated surface-code memory d=5" in content
    assert "10<sup>7</sup>" in content
    assert "probability" in content
    assert "0.15 probability" in content
    assert "02300000000000000000" not in content


def test_machine_result_table_state_is_url_backed(client):
    machine = Machine.objects.get(slug="demo-eight-core-cpu")
    response = client.get(
        reverse("machines:detail", args=[machine.slug]),
        {"columns": "decoder,circuit,shots", "sort": "-shots,decoder"},
    )

    assert [column["key"] for column in response.context["table_columns"]] == [
        "decoder",
        "circuit",
        "shots",
    ]
    assert response.context["sort_summary"] == "Shots descending, Decoder ascending"


def test_draft_machine_is_not_public(client):
    machine = Machine.objects.get(slug="demo-eight-core-cpu")
    machine.state = "draft"
    machine.published_at = None
    machine.save(update_fields=["state", "published_at"])

    response = client.get(reverse("machines:detail", args=[machine.slug]))

    assert response.status_code == 404
