"""Forms for benchmark revisions and attempts."""

import json

from django import forms

from registry.models import BenchmarkRevision, DecoderVersion, Result
from registry.services.benchmark_submissions import (
    BenchmarkValidationError,
    canonical_benchmark_payload,
)


class BenchmarkRevisionSubmissionForm(forms.Form):
    slug = forms.SlugField(max_length=200)
    name = forms.CharField(max_length=200)
    version = forms.CharField(max_length=100)
    previous_revision = forms.ModelChoiceField(
        queryset=BenchmarkRevision.objects.none(), required=False
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    revision_description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    items_json = forms.CharField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["previous_revision"].queryset = BenchmarkRevision.objects.filter(
            state__in=["published", "withdrawn"]
        ).order_by("name", "version", "id")

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        if BenchmarkRevision.objects.filter(slug=slug).exists():
            raise forms.ValidationError("That benchmark slug is already in use.")
        return slug

    def clean_items_json(self):
        try:
            value = json.loads(self.cleaned_data["items_json"])
        except json.JSONDecodeError as error:
            raise forms.ValidationError(
                "The ordered circuit list is invalid."
            ) from error
        if not isinstance(value, list):
            raise forms.ValidationError("The ordered circuit list must be an array.")
        return value

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        payload = {
            "slug": cleaned.get("slug"),
            "name": cleaned.get("name"),
            "version": cleaned.get("version"),
            "previous_revision": (
                str(cleaned["previous_revision"].id)
                if cleaned.get("previous_revision")
                else None
            ),
            "description": cleaned.get("description"),
            "revision_description": cleaned.get("revision_description"),
            "items": cleaned.get("items_json"),
        }
        try:
            cleaned["payload"] = canonical_benchmark_payload(payload)
        except BenchmarkValidationError as error:
            raise forms.ValidationError(str(error)) from error
        return cleaned


class BenchmarkAttemptSelectionForm(forms.Form):
    benchmark_revision = forms.ModelChoiceField(
        queryset=BenchmarkRevision.objects.none(), label="Benchmark revision"
    )
    decoder_version = forms.ModelChoiceField(
        queryset=DecoderVersion.objects.none(), label="Decoder version"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["benchmark_revision"].queryset = BenchmarkRevision.objects.filter(
            state="published"
        ).order_by("name", "version", "id")
        self.fields["decoder_version"].queryset = DecoderVersion.objects.filter(
            state="published"
        ).order_by("name", "version", "id")


class ResultForManifestField(forms.ModelChoiceField):
    def label_from_instance(self, result):
        machine = result.machine.slug if result.machine_id else "no machine"
        return f"{str(result.id)[:8]}… · {machine} · {result.evaluator_version.version}"


class BenchmarkAttemptResultsForm(forms.Form):
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, benchmark, decoder, **kwargs):
        self.benchmark = benchmark
        self.decoder = decoder
        super().__init__(*args, **kwargs)
        self.manifest_items = list(
            benchmark.items.select_related("circuit_revision").order_by("position")
        )
        for item in self.manifest_items:
            self.fields[self.field_name(item.circuit_revision_id)] = (
                ResultForManifestField(
                    queryset=Result.objects.filter(
                        state="published",
                        decoder_version=decoder,
                        circuit_revision=item.circuit_revision,
                    ).select_related("machine", "evaluator_version"),
                    required=item.is_required,
                    label=(
                        f"{item.position}. {item.circuit_revision.name} "
                        f"({'required' if item.is_required else 'optional'})"
                    ),
                )
            )

    @staticmethod
    def field_name(circuit_id):
        return f"result_{str(circuit_id).replace('-', '_')}"

    def result_ids_by_circuit(self):
        if not self.is_valid():
            raise ValueError("Cannot read results from an invalid attempt form.")
        return {
            str(item.circuit_revision_id): (
                str(result.id)
                if (
                    result := self.cleaned_data.get(
                        self.field_name(item.circuit_revision_id)
                    )
                )
                else None
            )
            for item in self.manifest_items
        }
