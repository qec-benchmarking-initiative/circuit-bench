import json
import uuid

from django import forms

from registry.services.circuit_batches import CircuitBatchError, parse_manifest


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)]


class CircuitBatchUploadForm(forms.Form):
    manifest_file = forms.FileField(
        required=False,
        help_text="A circuit-batch/0.1 JSON manifest.",
    )
    manifest_json = forms.CharField(
        required=False,
        label="Or paste the manifest JSON",
        widget=forms.Textarea(attrs={"rows": 24, "spellcheck": "false"}),
    )
    circuit_files = MultipleFileField(
        widget=MultipleFileInput(attrs={"accept": ".stim,.zip"}),
        help_text="Select .stim files, one or more zip files, or both.",
    )
    idempotency_key = forms.CharField(
        required=False,
        max_length=200,
        initial=uuid.uuid4,
        help_text="Repeating this key returns the same validated batch.",
    )

    def clean(self):
        cleaned = super().clean()
        uploaded = cleaned.get("manifest_file")
        pasted = (cleaned.get("manifest_json") or "").strip()
        if bool(uploaded) == bool(pasted):
            raise forms.ValidationError(
                "Provide either one manifest file or pasted manifest JSON."
            )
        raw = uploaded.read() if uploaded else pasted
        try:
            cleaned["manifest"] = parse_manifest(raw)
        except CircuitBatchError as error:
            self.add_error("manifest_json", str(error))
        return cleaned


def example_batch_manifest() -> str:
    value = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "visibility": "private",
            "noise_model": "NOISE-MODEL-UUID",
            "is_css": True,
            "code_tags": ["CODE-TAG-UUID"],
            "experiment_tags": ["EXPERIMENT-TAG-UUID"],
            "dem_arguments": {"decompose_errors": True},
        },
        "circuits": {
            "distance-3.stim": {
                "client_id": "distance-3",
                "slug": "example-family-distance-3",
                "name": "Example family, distance 3",
                "description": "Describe this circuit family.",
                "revision_description": "First submitted revision.",
                "code_distance_upper_bound": 3,
                "collections": ["new:example-family"],
            }
        },
        "new_tags": [],
        "new_collections": [
            {
                "client_id": "example-family",
                "slug": "example-family",
                "name": "Example family",
                "visibility": "private",
                "code_tags": ["CODE-TAG-UUID"],
                "experiment_tags": ["EXPERIMENT-TAG-UUID"],
                "children": [],
            }
        ],
    }
    return json.dumps(value, indent=2)
