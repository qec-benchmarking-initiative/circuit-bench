import json
from pathlib import Path

import yaml
from django.conf import settings

from registry.forms_batches import CircuitBatchUploadForm
from registry.forms_benchmark_submissions import BenchmarkRevisionSubmissionForm
from registry.forms_collections import CircuitCollectionForm
from registry.forms_common import auxiliary_guidance
from registry.forms_submissions import FORM_CLASSES
from registry.forms_taxonomy import CustomTagForm, NoiseModelSubmissionForm


def test_every_core_field_has_a_meaningful_current_summary():
    root = Path(settings.BASE_DIR)
    current = json.loads((root / "schemas/current.json").read_text())[
        "current_submission_schemas"
    ]
    for kind, form in FORM_CLASSES.items():
        path = root / f"schemas/{kind}/{current[kind]}.schema.json"
        schema = json.loads(path.read_text())
        document = yaml.safe_load(
            (path.parent / schema["x-definitions"]["path"]).read_text()
        )
        for name, field in form.base_fields.items():
            key = schema["x-form-definitions"][name]
            summary = document["definitions"][key]["summary"]
            assert len(summary.split()) >= 4, (kind, name, summary)
            assert (
                summary.casefold()
                != str(field.label or name.replace("_", " ")).casefold()
            )


def test_auxiliary_submission_fields_have_guidance():
    document = auxiliary_guidance()
    for form in (
        BenchmarkRevisionSubmissionForm,
        CircuitBatchUploadForm,
        CircuitCollectionForm,
        NoiseModelSubmissionForm,
        CustomTagForm,
    ):
        summaries = {**document["common"], **document["forms"].get(form.__name__, {})}
        for name in form.base_fields:
            assert len(summaries.get(name, "").split()) >= 4, (form.__name__, name)


def test_software_guidance_does_not_include_neighbouring_timing_definitions():
    root = Path(settings.BASE_DIR)
    current = json.loads((root / "schemas/current.json").read_text())
    version = current["current_submission_schemas"]["result"]
    path = root / f"schemas/result/{version}.schema.json"
    schema = json.loads(path.read_text())
    document = yaml.safe_load(
        (path.parent / schema["x-definitions"]["path"]).read_text()
    )
    key = schema["x-form-definitions"]["software_environment"]
    text = document["definitions"][key]["expanded"]
    assert "software versions" in text
    assert "preparation_duration_seconds" not in text
    assert "t_1000_ns" not in text
