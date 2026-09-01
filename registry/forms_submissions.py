"""Shared structured-form validation for submission and JSON entry."""

import json
import uuid
from decimal import Decimal, InvalidOperation

from django import forms
from django.http import QueryDict

from registry.models import (
    Artifact,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    Result,
    ScoreDefinition,
    Tag,
)
from registry.services.artifact_access import readable_artifacts_for
from registry.submission_policy import SubmissionKind


class ArtifactChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.original_filename} · {obj.sha256[:12]}…"


class ResultChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.decoder_version} on {obj.circuit_revision} · {str(obj.id)[:8]}…"


class WithdrawalForm(forms.Form):
    note = forms.CharField(
        label="Reason for withdrawal",
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="This note is retained in the permanent moderation history.",
    )


class BaseSubmissionForm(forms.Form):
    kind: SubmissionKind

    def __init__(
        self,
        *args,
        record=None,
        allow_withdrawn_lineage=False,
        actor=None,
        **kwargs,
    ):
        self.record = record
        self.allow_withdrawn_lineage = allow_withdrawn_lineage
        self.actor = actor
        super().__init__(*args, **kwargs)

    @property
    def readable_artifacts(self):
        return readable_artifacts_for(self.actor).order_by("original_filename", "id")

    @property
    def lineage_states(self):
        if self.allow_withdrawn_lineage or (
            self.record is not None
            and self.record.state in {"pending_reapproval", "changes_requested"}
        ):
            return ["published", "withdrawn"]
        return ["published"]

    def canonical_payload(self) -> dict:
        if not self.is_valid():
            raise ValueError("Cannot canonicalise an invalid submission form.")
        return {
            name: _json_value(value)
            for name, value in self.cleaned_data.items()
            if not name.endswith("_json")
        }


class DecoderSubmissionForm(BaseSubmissionForm):
    kind = SubmissionKind.DECODER

    slug = forms.SlugField(
        max_length=200,
        help_text="Permanent URL name, for example clear-matcher-0-3.",
    )
    name = forms.CharField(max_length=200)
    version = forms.CharField(max_length=100)
    previous_version = forms.ModelChoiceField(
        queryset=DecoderVersion.objects.none(), required=False
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Required for the first version; later versions may inherit it.",
    )
    revision_description = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="What this exact version introduced or changed.",
    )
    circuit_skeleton_preparation = forms.ChoiceField(choices=DecoderVersion.Preparation)
    circuit_priors_preparation = forms.ChoiceField(choices=DecoderVersion.Preparation)
    provides_failure_probability = forms.BooleanField(required=False)
    hyperparameter_definitions = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 4})
    )
    hyperparameter_schema_artifact = ArtifactChoiceField(
        queryset=Artifact.objects.none(),
        required=False,
        label="Hyperparameter JSON Schema",
        widget=forms.HiddenInput(),
    )
    algorithm_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        previous_versions = (
            DecoderVersion.objects.filter(state__in=self.lineage_states)
            .select_related("hyperparameter_schema_artifact")
            .order_by("name", "version")
        )
        self.fields["previous_version"].queryset = previous_versions
        self.fields["hyperparameter_schema_artifact"].queryset = self.readable_artifacts
        self.previous_schema_choices = {
            str(version.id): {
                "identifier": str(version.hyperparameter_schema_artifact_id),
                "label": version.hyperparameter_schema_artifact.original_filename,
            }
            for version in previous_versions
            if version.hyperparameter_schema_artifact_id
        }
        self.fields["algorithm_tags"].queryset = (
            Tag.objects.filter(namespace=Tag.Namespace.ALGORITHM)
            .exclude(status=Tag.Status.DEPRECATED)
            .order_by("status", "label", "id")
        )

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        matches = DecoderVersion.objects.filter(slug=slug)
        if self.record is not None:
            matches = matches.exclude(id=self.record.id)
        if matches.exists():
            raise forms.ValidationError("That decoder slug is already in use.")
        return slug

    def clean(self):
        cleaned = super().clean()
        if (
            not cleaned.get("previous_version")
            and not cleaned.get("description", "").strip()
        ):
            self.add_error("description", "The first version needs a description.")
        return cleaned


class CircuitSubmissionForm(BaseSubmissionForm):
    kind = SubmissionKind.CIRCUIT

    slug = forms.SlugField(max_length=200)
    name = forms.CharField(max_length=200)
    previous_revision = forms.ModelChoiceField(
        queryset=CircuitRevision.objects.none(), required=False
    )
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Required for the first revision; later revisions may inherit it.",
    )
    revision_description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    noise_model = forms.ModelChoiceField(queryset=NoiseModel.objects.none())
    is_css = forms.BooleanField(required=False, label="CSS circuit")
    code_distance_upper_bound = forms.IntegerField(min_value=1, required=False)
    circuit_distance_upper_bound = forms.IntegerField(min_value=1, required=False)
    rounds = forms.IntegerField(min_value=1, required=False)
    num_detectors = forms.IntegerField(min_value=0)
    num_errors = forms.IntegerField(min_value=0)
    num_observables = forms.IntegerField(min_value=1)
    dem_x_detectors_only = forms.BooleanField(required=False, label="X detectors only")
    dem_z_detectors_only = forms.BooleanField(required=False, label="Z detectors only")
    stim_version = forms.CharField()
    dem_decompose_errors = forms.BooleanField(required=False)
    dem_flatten_loops = forms.BooleanField(required=False)
    dem_allow_gauge_detectors = forms.BooleanField(required=False)
    dem_approximate_disjoint_errors = forms.BooleanField(
        label="Approximate disjoint errors",
        required=False,
    )
    dem_ignore_decomposition_failures = forms.BooleanField(required=False)
    dem_block_decomposition_from_introducing_remnant_edges = forms.BooleanField(
        required=False
    )
    sampling_circuit_artifact = ArtifactChoiceField(
        queryset=Artifact.objects.none(),
        label="Sampling circuit file",
        widget=forms.HiddenInput(),
    )
    detector_error_model_artifact = ArtifactChoiceField(
        queryset=Artifact.objects.none(),
        label="Detector error model file",
        widget=forms.HiddenInput(),
    )
    manifest_artifact = ArtifactChoiceField(
        queryset=Artifact.objects.none(),
        label="Manifest file",
        widget=forms.HiddenInput(),
    )
    code_tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.none())
    experiment_tags = forms.ModelMultipleChoiceField(queryset=Tag.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["previous_revision"].queryset = CircuitRevision.objects.filter(
            state__in=self.lineage_states
        ).order_by("name", "created_at")
        self.fields["noise_model"].queryset = (
            NoiseModel.objects.filter(state="published")
            .exclude(curation_status=NoiseModel.CurationStatus.DEPRECATED)
            .order_by("name")
        )
        artifacts = self.readable_artifacts
        for name in (
            "sampling_circuit_artifact",
            "detector_error_model_artifact",
            "manifest_artifact",
        ):
            self.fields[name].queryset = artifacts
        self.fields["code_tags"].queryset = (
            Tag.objects.filter(namespace=Tag.Namespace.CODE)
            .exclude(status=Tag.Status.DEPRECATED)
            .order_by("status", "label", "id")
        )
        self.fields["experiment_tags"].queryset = (
            Tag.objects.filter(namespace=Tag.Namespace.EXPERIMENT)
            .exclude(status=Tag.Status.DEPRECATED)
            .order_by("status", "label", "id")
        )

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        matches = CircuitRevision.objects.filter(slug=slug)
        if self.record is not None:
            matches = matches.exclude(id=self.record.id)
        if matches.exists():
            raise forms.ValidationError("That circuit slug is already in use.")
        return slug

    def clean(self):
        cleaned = super().clean()
        if (
            not cleaned.get("previous_revision")
            and not cleaned.get("description", "").strip()
        ):
            self.add_error("description", "The first revision needs a description.")
        if (
            cleaned.get("dem_x_detectors_only") or cleaned.get("dem_z_detectors_only")
        ) and not cleaned.get("is_css"):
            self.add_error(
                "is_css", "Detector-basis restrictions require a CSS circuit."
            )
        if (
            cleaned.get("num_detectors")
            and cleaned.get("dem_x_detectors_only")
            and cleaned.get("dem_z_detectors_only")
        ):
            self.add_error(
                "dem_z_detectors_only",
                "A non-empty DEM cannot be both X-detectors-only and Z-detectors-only.",
            )
        return cleaned


class ResultSubmissionForm(BaseSubmissionForm):
    kind = SubmissionKind.RESULT

    decoder_version = forms.ModelChoiceField(queryset=DecoderVersion.objects.none())
    circuit_revision = forms.ModelChoiceField(queryset=CircuitRevision.objects.none())
    evaluator_version = forms.ModelChoiceField(queryset=EvaluatorRelease.objects.none())
    machine = forms.ModelChoiceField(
        queryset=Machine.objects.none(),
        help_text=(
            "Machines publish separately and must exist before a result is submitted."
        ),
    )
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    hyperparameter_values = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    hyperparameter_values_artifact = ArtifactChoiceField(
        queryset=Artifact.objects.none(),
        required=False,
        label="Hyperparameter values JSON file",
        widget=forms.HiddenInput(),
    )
    shots_total = forms.IntegerField(min_value=1)
    successful_shots = forms.IntegerField(min_value=0)
    logical_failure_shots = forms.IntegerField(min_value=0)
    timeout_shots = forms.IntegerField(min_value=0)
    decoder_error_shots = forms.IntegerField(min_value=0)
    failure_probability_shots = forms.IntegerField(min_value=0)
    latency_shots = forms.IntegerField(min_value=0)
    preparation_duration_seconds = forms.DecimalField(
        min_value=0, max_digits=24, decimal_places=9, required=False
    )
    training_workload_description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    software_environment = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    t_1000_ns = forms.IntegerField(min_value=1, required=False, label="t₁₀₀₀ (ns)")
    supersedes_result = ResultChoiceField(
        queryset=Result.objects.none(), required=False
    )
    scores_json = forms.CharField(
        label="Evaluator scores",
        widget=forms.Textarea(attrs={"rows": 12, "spellcheck": "false"}),
        help_text=(
            "JSON array. Each item needs score_definition and value; uncertainty, "
            "counts, and details are optional."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decoder_version"].queryset = DecoderVersion.objects.filter(
            state="published"
        ).order_by("name", "version")
        self.fields["circuit_revision"].queryset = CircuitRevision.objects.filter(
            state="published"
        ).order_by("name", "created_at")
        self.fields["evaluator_version"].queryset = EvaluatorRelease.objects.filter(
            state="published"
        ).order_by("version")
        self.fields["machine"].queryset = Machine.objects.filter(
            state="published"
        ).order_by("slug")
        self.fields["hyperparameter_values_artifact"].queryset = self.readable_artifacts
        self.fields["supersedes_result"].queryset = Result.objects.filter(
            state__in=self.lineage_states
        ).order_by("-created_at", "id")

    def clean_scores_json(self):
        raw = self.cleaned_data["scores_json"]
        try:
            scores = json.loads(raw)
        except json.JSONDecodeError as error:
            raise forms.ValidationError(f"Invalid JSON: {error.msg}.") from error
        if not isinstance(scores, list) or not scores:
            raise forms.ValidationError("Provide at least one score object.")
        return scores

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get("shots_total")
        outcome_fields = (
            "successful_shots",
            "logical_failure_shots",
            "timeout_shots",
            "decoder_error_shots",
        )
        if total is not None and all(
            cleaned.get(name) is not None for name in outcome_fields
        ):
            if sum(cleaned[name] for name in outcome_fields) != total:
                self.add_error(
                    "shots_total",
                    (
                        "Total shots must equal successful + logical failure + timeout "
                        "+ decoder error."
                    ),
                )
        completed = (cleaned.get("successful_shots") or 0) + (
            cleaned.get("logical_failure_shots") or 0
        )
        for field in ("failure_probability_shots", "latency_shots"):
            if cleaned.get(field) is not None and cleaned[field] > completed:
                self.add_error(
                    field, "This count cannot exceed completed outcome shots."
                )

        evaluator = cleaned.get("evaluator_version")
        scores = cleaned.get("scores_json")
        if evaluator and scores:
            try:
                cleaned["scores_json"] = _normalise_scores(scores, evaluator)
            except forms.ValidationError as error:
                self.add_error("scores_json", error)
        predecessor = cleaned.get("supersedes_result")
        if predecessor and (
            predecessor.decoder_version_id
            != getattr(cleaned.get("decoder_version"), "id", None)
            or predecessor.circuit_revision_id
            != getattr(cleaned.get("circuit_revision"), "id", None)
        ):
            self.add_error(
                "supersedes_result",
                "A successor must use the predecessor's exact decoder and circuit.",
            )
        return cleaned

    def canonical_payload(self) -> dict:
        payload = super().canonical_payload()
        payload["scores"] = self.cleaned_data["scores_json"]
        return payload


class MachineSubmissionForm(BaseSubmissionForm):
    kind = SubmissionKind.MACHINE

    slug = forms.SlugField(max_length=200)
    machine_class = forms.ChoiceField(choices=Machine.MachineClass)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}))
    status = forms.ChoiceField(choices=Machine.EvidenceStatus)
    supersedes_machine = forms.ModelChoiceField(
        queryset=Machine.objects.none(), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["supersedes_machine"].queryset = Machine.objects.filter(
            state__in=self.lineage_states
        ).order_by("slug")

    def clean_slug(self):
        slug = self.cleaned_data["slug"]
        matches = Machine.objects.filter(slug=slug)
        if self.record is not None:
            matches = matches.exclude(id=self.record.id)
        if matches.exists():
            raise forms.ValidationError("That machine slug is already in use.")
        return slug


FORM_CLASSES = {
    SubmissionKind.DECODER: DecoderSubmissionForm,
    SubmissionKind.CIRCUIT: CircuitSubmissionForm,
    SubmissionKind.RESULT: ResultSubmissionForm,
    SubmissionKind.MACHINE: MachineSubmissionForm,
}


def submission_form(kind: SubmissionKind | str, *args, **kwargs) -> BaseSubmissionForm:
    return FORM_CLASSES[SubmissionKind(kind)](*args, **kwargs)


def submission_form_for_payload(
    kind: SubmissionKind | str,
    payload: dict,
    *,
    record=None,
    allow_withdrawn_lineage=False,
    actor=None,
) -> BaseSubmissionForm:
    kind = SubmissionKind(kind)
    data = QueryDict("", mutable=True)
    for name, value in _payload_to_form_values(kind, payload).items():
        if isinstance(value, list):
            data.setlist(name, [str(item) for item in value])
        elif value is None:
            data[name] = ""
        elif isinstance(value, bool):
            data[name] = "true" if value else "false"
        else:
            data[name] = str(value)
    return submission_form(
        kind,
        data=data,
        record=record,
        allow_withdrawn_lineage=allow_withdrawn_lineage,
        actor=actor,
    )


def submission_initial(kind: SubmissionKind | str, payload: dict) -> dict:
    return _payload_to_form_values(SubmissionKind(kind), payload)


def _payload_to_form_values(kind: SubmissionKind, payload: dict) -> dict:
    values = dict(payload)
    if kind is SubmissionKind.RESULT:
        values["scores_json"] = json.dumps(
            values.pop("scores", []), indent=2, sort_keys=True
        )
    return values


def _json_value(value):
    if hasattr(value, "all"):
        return [str(item.pk) for item in value]
    if hasattr(value, "pk"):
        return str(value.pk)
    if isinstance(value, Decimal):
        return format(value, "f")
    if value == "":
        return None
    return value


def _normalise_scores(scores: list, evaluator: EvaluatorRelease) -> list[dict]:
    allowed = {
        "score_definition",
        "value",
        "point_estimate",
        "lower_bound",
        "upper_bound",
        "confidence_level",
        "sample_count",
        "event_count",
        "details",
    }
    normalised = []
    seen = set()
    for index, score in enumerate(scores, 1):
        if not isinstance(score, dict):
            raise forms.ValidationError(f"Score {index} must be an object.")
        unknown = set(score) - allowed
        if unknown:
            raise forms.ValidationError(
                f"Score {index} has unknown fields: {', '.join(sorted(unknown))}."
            )
        try:
            definition_id = uuid.UUID(str(score["score_definition"]))
            definition = ScoreDefinition.objects.get(
                id=definition_id, evaluator_release=evaluator
            )
        except KeyError as error:
            raise forms.ValidationError(
                f"Score {index} needs score_definition."
            ) from error
        except (ValueError, ScoreDefinition.DoesNotExist) as error:
            raise forms.ValidationError(
                f"Score {index} does not name a definition from the selected evaluator."
            ) from error
        if definition.id in seen:
            raise forms.ValidationError("Each score definition may appear only once.")
        seen.add(definition.id)

        item = {"score_definition": str(definition.id)}
        for name in ("value", "point_estimate", "lower_bound", "upper_bound"):
            required = name == "value"
            item[name] = _decimal_value(score.get(name), index, name, required=required)
        confidence = _decimal_value(
            score.get("confidence_level"), index, "confidence_level", required=False
        )
        if confidence is not None and not (
            Decimal("0") < Decimal(confidence) < Decimal("1")
        ):
            raise forms.ValidationError(
                f"Score {index} confidence_level must be between 0 and 1."
            )
        item["confidence_level"] = confidence
        for name in ("sample_count", "event_count"):
            value = score.get(name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise forms.ValidationError(
                    f"Score {index} {name} must be a non-negative integer or null."
                )
            item[name] = value
        details = score.get("details", {})
        if not isinstance(details, dict):
            raise forms.ValidationError(f"Score {index} details must be an object.")
        item["details"] = details
        normalised.append(item)
    return normalised


def _decimal_value(value, index: int, name: str, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise forms.ValidationError(f"Score {index} needs {name}.")
        return None
    if isinstance(value, bool):
        raise forms.ValidationError(f"Score {index} {name} must be a finite number.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise forms.ValidationError(
            f"Score {index} {name} must be a finite number."
        ) from error
    if not parsed.is_finite():
        raise forms.ValidationError(f"Score {index} {name} must be finite.")
    return format(parsed, "f")
