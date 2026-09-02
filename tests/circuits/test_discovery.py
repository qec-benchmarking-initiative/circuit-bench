import pytest
from django.urls import reverse
from django.utils import timezone

from registry.demo import seed_demo_data
from registry.models import (
    CircuitRevision,
    EczSyncRun,
    EczTerm,
    Machine,
    NoiseModel,
    RecordHistory,
    Tag,
    TagEczParent,
    TagParent,
)


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


def test_circuit_explorer_combines_scientific_filters_and_column_state(
    client, demo_registry
):
    response = client.get(
        reverse("circuits:list"),
        {
            "experiment_tag": "memory",
            "css": "yes",
            "detector_min": "1",
            "columns": "name,detectors,errors",
            "sort": "-detectors,name",
        },
    )

    assert response.status_code == 200
    assert len(response.context["circuits"]) == 1
    assert [column["key"] for column in response.context["table_columns"]] == [
        "name",
        "detectors",
        "errors",
    ]
    assert "Table view options (3/14)" in response.content.decode()
    content = response.content.decode()
    assert 'id="circuit-filters"' in content
    assert "data-filter-tag-cell" in content
    assert "Detector count" in content


def test_any_child_code_match_crosses_from_ecz_to_native_children(
    client, demo_registry
):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    native_child = Tag.objects.get(
        namespace=Tag.Namespace.CODE,
        slug="bivariate-bicycle-162",
    )
    now = timezone.now()
    sync_run = EczSyncRun.objects.create(
        started_at=now,
        finished_at=now,
        status=EczSyncRun.Status.APPLIED,
        source_repository="https://github.com/errorcorrectionzoo/eczoo_data",
    )
    ecz_parent = EczTerm.objects.create(
        ecz_code_id="qcga-test-parent",
        raw_name="QCGA test parent",
        display_name="QCGA test parent",
        first_seen_run=sync_run,
        last_seen_run=sync_run,
    )
    TagEczParent.objects.create(tag=native_child, ecz_term=ecz_parent)
    circuit.code_tags.add(native_child)

    exact = client.get(
        reverse("circuits:list"),
        {"code_tag": "ecz:qcga-test-parent", "code_tag_match": "any"},
    )
    descendants = client.get(
        reverse("circuits:list"),
        {
            "code_tag": "ecz:qcga-test-parent",
            "code_tag_match": "children",
        },
    )

    assert circuit not in exact.context["circuits"]
    assert circuit in descendants.context["circuits"]


def test_any_child_experiment_match_is_recursive_and_includes_root(
    client, demo_registry
):
    memory = Tag.objects.get(namespace=Tag.Namespace.EXPERIMENT, slug="memory")
    stability = Tag.objects.create(
        schema_release=memory.schema_release,
        history=RecordHistory.objects.create(record_kind="tag"),
        namespace=Tag.Namespace.EXPERIMENT,
        slug="stability-parent-test",
        label="Stability parent test",
        description="Test-only parent for experiment-filter coverage.",
        status=Tag.Status.OFFICIAL,
        submitted_by=memory.submitted_by,
    )
    TagParent.objects.create(child=memory, parent=stability)

    exact_slugs = {
        circuit.slug
        for circuit in client.get(
            reverse("circuits:list"),
            {
                "experiment_tag": "stability-parent-test",
                "experiment_tag_match": "any",
            },
        ).context["circuits"]
    }
    descendant_slugs = {
        circuit.slug
        for circuit in client.get(
            reverse("circuits:list"),
            {
                "experiment_tag": "stability-parent-test",
                "experiment_tag_match": "children",
            },
        ).context["circuits"]
    }

    assert exact_slugs == set()
    assert "rotated-memory-d5" in descendant_slugs


def test_circuit_noise_model_picker_uses_repeated_in_filter_parameters(
    client, demo_registry
):
    url = reverse("circuits:list")
    both = client.get(
        url,
        {
            "noise_model": [
                "fixed-phenomenological",
                "randomised-phenomenological",
            ]
        },
    )
    randomised_only = client.get(
        url,
        {"noise_model": "randomised-phenomenological"},
    )

    content = both.content.decode()
    assert len(both.context["circuits"]) == 1
    assert len(randomised_only.context["circuits"]) == 0
    assert content.count('<input type="hidden" name="noise_model"') == 2
    assert "Fixed phenomenological noise +1" in content
    assert "data-filter-related-record-cell" in content
    assert reverse("pickers:records", args=["noise-models"]) in content


def test_noise_model_explorer_filters_derived_priors_and_circuit_count(
    client, demo_registry
):
    response = client.get(
        reverse("noise-models:list"),
        {"priors": "yes", "circuit_min": "0", "sort": "-circuits"},
    )

    assert response.status_code == 200
    assert [item.slug for item in response.context["noise_models"]] == [
        "randomised-phenomenological"
    ]
    assert response.context["sort_summary"] == "Circuits descending"
    content = response.content.decode()
    assert 'id="noise-model-filters"' in content
    assert "data-control-choice-cell" in content
    assert "Published circuits" in content


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


def test_circuit_leaderboard_uses_reusable_algorithm_and_machine_grids(
    client, demo_registry
):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    response = client.get(reverse("circuits:detail", args=[circuit.slug]))
    content = response.content.decode()

    assert 'id="circuit-result-algorithm-filters"' in content
    assert 'id="circuit-result-machine-filters"' in content
    assert content.count("data-filter-grid") == 2
    assert "Decoding algorithm filters" in content
    assert "Machine filters" in content
    assert "selected values shown in the theme colour" not in content
    assert ">active<" not in content
    assert "Table view options (11/15)" in content
    assert "LER upper 95% @ 5%" in content
    assert "t₁₀₀₀ (ns)" in content
    assert response.context["result_count"] == 1
    machine = Machine.objects.get(slug="demo-eight-core-cpu")
    assert reverse("machines:detail", args=[machine.slug]) in content
    assert "10<sup>7</sup>" in content
    assert "probability" in content


def test_circuit_leaderboard_filters_results_by_algorithm_and_machine(
    client, demo_registry
):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    url = reverse("circuits:detail", args=[circuit.slug])

    matching_cpu = client.get(
        url,
        {"tag": "matching", "skeleton": "not_required", "machine_class": "cpu"},
    )
    incompatible_machine = client.get(url, {"machine_class": "gpu"})
    incompatible_preparation = client.get(url, {"skeleton": "required"})

    assert matching_cpu.context["result_count"] == 1
    assert matching_cpu.context["selected_machine_class"] == "cpu"
    assert incompatible_machine.context["result_count"] == 0
    assert incompatible_preparation.context["result_count"] == 0
    assert b"No results yet" in incompatible_machine.content


def test_circuit_leaderboard_table_state_is_url_backed(client, demo_registry):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    response = client.get(
        reverse("circuits:detail", args=[circuit.slug]),
        {
            "columns": "decoder,machine_class,shots",
            "sort": "-shots,decoder",
        },
    )

    assert [column["key"] for column in response.context["table_columns"]] == [
        "decoder",
        "machine_class",
        "shots",
    ]
    assert response.context["sort_summary"] == "Shots descending, Decoder ascending"


def test_circuit_tag_filter_keeps_namespace(client, demo_registry):
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    Tag = circuit.code_tags.model
    source = circuit.experiment_tags.get(slug="memory")
    Tag.objects.create(
        schema_release=source.schema_release,
        history=RecordHistory.objects.create(record_kind="tag"),
        namespace="code",
        slug="memory",
        label="Memory code",
        description="A deliberately colliding slug for filter isolation.",
        status="custom",
        submitted_by=circuit.submitted_by,
    )

    experiment = client.get(reverse("circuits:list"), {"tag": "experiment:memory"})
    code = client.get(reverse("circuits:list"), {"tag": "code:memory"})

    assert len(experiment.context["circuits"]) > 0
    assert len(code.context["circuits"]) == 0


def test_circuit_code_filter_accepts_exact_ecz_identities(client, demo_registry):
    sync_run = EczSyncRun.objects.create(
        started_at=timezone.now(),
        finished_at=timezone.now(),
        status=EczSyncRun.Status.APPLIED,
        source_repository="https://github.com/errorcorrectionzoo/eczoo_data",
    )
    term = EczTerm.objects.create(
        ecz_code_id="rotated_surface",
        raw_name="Rotated surface code",
        display_name="Rotated surface code",
        first_seen_run=sync_run,
        last_seen_run=sync_run,
    )
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    circuit.ecz_terms.add(term)
    response = client.get(reverse("circuits:list"), {"code_tag": "ecz:rotated_surface"})

    assert response.context["result_count"] == 1
    assert response.context["circuits"][0] == circuit


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
    circuit.noise_model = NoiseModel.objects.get(slug="randomised-phenomenological")
    circuit.save(update_fields=["noise_model"])

    response = client.get(reverse("circuits:detail", args=[circuit.slug]))

    assert response.context["circuit"].noise_model.randomises_priors is True
    assert b"Priors randomised" in response.content
