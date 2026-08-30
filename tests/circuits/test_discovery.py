import pytest
from django.urls import reverse

from registry.demo import seed_demo_data
from registry.models import CircuitRevision, NoiseModel


@pytest.fixture
def demo_registry(db):
    seed_demo_data()


def test_circuit_catalogue_searches_code_and_experiment_tags(client, demo_registry):
    response = client.get(reverse("circuits:list"), {"q": "rotated surface"})
    assert response.status_code == 200
    assert b"Rotated surface-code memory d=5" in response.content

    response = client.get(reverse("circuits:list"), {"tag": "experiment:memory"})
    assert response.status_code == 200
    assert b"Rotated surface-code memory d=5" in response.content


def test_circuit_detail_shows_exact_dem_provenance(client, demo_registry):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    response = client.get(reverse("circuits:detail", args=[circuit.slug]))
    assert response.status_code == 200
    assert circuit.detector_error_model_artifact.sha256.encode() in response.content
    assert b"stim.Circuit.detector_error_model" in response.content
    assert b"Code distance upper bound" in response.content
    assert b"Priors randomised" in response.content


def test_noise_model_detail_has_reverse_circuit_list(client, demo_registry):
    noise_model = NoiseModel.objects.get(slug="fixed-phenomenological")
    response = client.get(reverse("noise-models:detail", args=[noise_model.slug]))
    assert response.status_code == 200
    assert b"Rotated surface-code memory d=5" in response.content
    assert b"Randomises priors" in response.content


def test_noise_model_filters_are_strict_and_searchable(client, demo_registry):
    response = client.get(
        reverse("noise-models:list"),
        {"q": "phenomenological", "status": "community"},
    )
    assert response.status_code == 200
    assert b"Randomised phenomenological noise" in response.content
    assert b"Fixed phenomenological noise" not in response.content

    response = client.get(reverse("noise-models:list"), {"status": "not-a-state"})
    assert len(response.context["noise_models"]) == 2


def test_circuit_detail_exposes_only_published_results(client, demo_registry):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    result = circuit.results.get()
    result.state = "pending_review"
    result.published_at = None
    result.save(update_fields=["state", "published_at"])

    response = client.get(reverse("circuits:detail", args=[circuit.slug]))

    assert response.status_code == 200
    assert b"Clear Matcher" not in response.content
    assert b"No results yet" in response.content


def test_circuit_tag_filter_keeps_namespace(client, demo_registry):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    Tag = circuit.code_tags.model
    Tag.objects.create(
        schema_release=circuit.code_tags.get(slug="rotated-surface-code").schema_release,
        namespace="code",
        slug="memory",
        label="Memory code",
        description="A deliberately colliding slug for filter isolation.",
        status="custom",
        submitted_by=circuit.submitted_by,
    )

    experiment = client.get(
        reverse("circuits:list"), {"tag": "experiment:memory"}
    )
    code = client.get(reverse("circuits:list"), {"tag": "code:memory"})

    assert len(experiment.context["circuits"]) == 1
    assert len(code.context["circuits"]) == 0


def test_withdrawn_noise_model_retains_exact_historical_url(client, demo_registry):
    noise_model = NoiseModel.objects.get(slug="fixed-phenomenological")
    from django.utils import timezone

    noise_model.state = "withdrawn"
    noise_model.withdrawn_at = timezone.now()
    noise_model.save(update_fields=["state", "withdrawn_at"])

    detail = client.get(reverse("noise-models:detail", args=[noise_model.slug]))
    catalogue = client.get(reverse("noise-models:list"))

    assert detail.status_code == 200
    assert noise_model.name.encode() in detail.content
    assert noise_model not in catalogue.context["noise_models"]


def test_randomised_priors_are_derived_from_noise_model(client, demo_registry):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    circuit.noise_model = NoiseModel.objects.get(
        slug="randomised-phenomenological"
    )
    circuit.save(update_fields=["noise_model"])

    response = client.get(reverse("circuits:detail", args=[circuit.slug]))

    assert b"Priors randomised: <strong>Yes</strong>" in response.content
