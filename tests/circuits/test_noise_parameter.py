from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import QueryDict
from django.urls import reverse

from registry.demo import seed_demo_data
from registry.forms_submissions import CircuitSubmissionForm
from registry.models import CircuitRevision, EczTerm
from registry.result_plots import build_result_scatter_plot
from registry.result_query import (
    execute_result_query,
    parse_result_query,
    result_record,
)
from registry.services.circuit_batches import batch_schema
from registry.services.ecz_sync import (
    apply_prepared_sync,
    prepare_sync,
    source_for_directory,
)
from registry.services.submissions import (
    create_submission,
    submission_payload_for_record,
    validate_submission_payload,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def circuit(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    seed_demo_data()
    fixture = Path(__file__).parents[1] / "fixtures" / "eczoo" / "snapshot_a"
    apply_prepared_sync(
        prepare_sync(source=source_for_directory(fixture), source_directory=fixture)
    )
    circuit = CircuitRevision.objects.get(slug="rotated-memory-d5")
    circuit.ecz_terms.add(EczTerm.objects.get(ecz_code_id="surface"))
    return circuit


def test_noise_parameter_submission_roundtrip(circuit):
    payload = submission_payload_for_record("circuit", circuit)
    payload.update(slug="noise-parameter-test", noise_parameter=0.002)
    actor = circuit.submitted_by
    cleaned = validate_submission_payload("circuit", payload, actor=actor)
    assert cleaned["noise_parameter"] == 0.002
    created = create_submission("circuit", payload, submitter=actor).record
    assert created.noise_parameter == 0.002
    assert submission_payload_for_record("circuit", created)["noise_parameter"] == 0.002
    payload.pop("noise_parameter")
    payload["slug"] = "legacy-parameter-omitted"
    assert (
        validate_submission_payload("circuit", payload, actor=actor)["noise_parameter"]
        is None
    )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf"), -float("inf")])
def test_invalid_parameter_rejected(circuit, value):
    with pytest.raises(ValidationError):
        CircuitSubmissionForm.base_fields["noise_parameter"].clean(value)
    with pytest.raises(IntegrityError), transaction.atomic():
        CircuitRevision.objects.filter(pk=circuit.pk).update(noise_parameter=value)


def test_parameter_query_plot_and_summary(client, circuit):
    query = parse_result_query(
        QueryDict("$filter=noise_parameter eq 0.001&$orderby=noise_parameter desc")
    )
    results = list(execute_result_query(query))
    assert results
    assert result_record(results[0], ("noise_parameter",))["noise_parameter"] == 0.001
    plot = build_result_scatter_plot(results, x_field="noise_parameter")
    assert plot
    response = client.get(reverse("circuits:detail", args=[circuit.slug]))
    html = response.content.decode()
    assert "<dt>Noise parameter</dt>" in html
    assert "<dt>Rounds</dt>" not in html
    assert "<dt>X only</dt>" not in html
    assert "<dt>Z only</dt>" not in html
    assert "Yes (X only)" in html
    listing = client.get(reverse("circuits:list"), {"sort": "noise_parameter"})
    assert listing.status_code == 200
    assert b'data-column="noise_parameter"' in listing.content


@pytest.mark.parametrize(
    "css,x,z,label",
    [
        (False, False, False, "No"),
        (True, False, False, "Yes"),
        (True, True, False, "Yes (X only)"),
        (True, False, True, "Yes (Z only)"),
    ],
)
def test_css_summary(css, x, z, label):
    assert (
        CircuitRevision(
            is_css=css, dem_x_detectors_only=x, dem_z_detectors_only=z
        ).css_display
        == label
    )


def test_batch_schema_exposes_noise_parameter():
    assert "noise_parameter" in str(batch_schema())
