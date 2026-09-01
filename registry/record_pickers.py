"""Allow-listed definitions for searchable related-record pickers.

Pickers construct reproducible URL state.  They deliberately do not own the
scientific filtering predicates, which remain in the domain query services.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.urls import reverse

from registry.models import (
    Artifact,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    Result,
)


@dataclass(frozen=True)
class RecordPickerSpec:
    key: str
    singular_label: str
    plural_label: str
    parameter_name: str
    identifier_field: str
    public_queryset: Callable[[], QuerySet]
    search_fields: tuple[str, ...]
    serialize_record: Callable[[Any], dict[str, Any]]


def _public_noise_models() -> QuerySet:
    return (
        NoiseModel.objects.filter(state="published")
        .annotate(
            picker_curation_order=Case(
                When(curation_status="official", then=Value(0)),
                When(curation_status="community", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("picker_curation_order", "name", "slug")
    )


def _serialize_noise_model(record: NoiseModel) -> dict[str, Any]:
    return {
        "identifier": record.slug,
        "label": record.name,
        "secondary_label": record.slug,
        "description": record.short_description,
        "curation_status": record.curation_status,
        "curation_label": record.get_curation_status_display(),
        "detail_url": reverse("noise-models:detail", args=[record.slug]),
    }


def _published(model, *ordering) -> QuerySet:
    return model.objects.filter(state="published").order_by(*ordering)


def _published_decoders() -> QuerySet:
    return _published(DecoderVersion, "name", "version", "id")


def _published_circuits() -> QuerySet:
    return _published(CircuitRevision, "name", "created_at", "id")


def _published_machines() -> QuerySet:
    return _published(Machine, "slug", "id")


def _published_evaluators() -> QuerySet:
    return _published(EvaluatorRelease, "version", "id")


def _published_results() -> QuerySet:
    return _published(Result, "-published_at", "id").select_related(
        "decoder_version", "circuit_revision"
    )


def _artifacts() -> QuerySet:
    return Artifact.objects.order_by("original_filename", "sha256", "id")


def _submission_noise_models() -> QuerySet:
    return _public_noise_models()


def _record_status(record) -> tuple[str, str]:
    return getattr(record, "state", "published"), getattr(
        record, "get_state_display", lambda: "Published"
    )()


def _serialize_decoder(record: DecoderVersion) -> dict[str, Any]:
    status, status_label = _record_status(record)
    return {
        "identifier": str(record.id),
        "label": f"{record.name} {record.version}",
        "secondary_label": record.slug,
        "description": record.description or record.revision_description,
        "curation_status": status,
        "curation_label": status_label,
        "detail_url": reverse("decoders:detail", args=[record.slug]),
    }


def _serialize_circuit(record: CircuitRevision) -> dict[str, Any]:
    status, status_label = _record_status(record)
    return {
        "identifier": str(record.id),
        "label": record.name,
        "secondary_label": record.slug,
        "description": record.description or record.revision_description,
        "curation_status": status,
        "curation_label": status_label,
        "detail_url": reverse("circuits:detail", args=[record.slug]),
    }


def _serialize_machine(record: Machine) -> dict[str, Any]:
    status, status_label = _record_status(record)
    return {
        "identifier": str(record.id),
        "label": record.slug,
        "secondary_label": record.get_machine_class_display(),
        "description": record.description,
        "curation_status": status,
        "curation_label": status_label,
        "detail_url": reverse("machines:detail", args=[record.slug]),
    }


def _serialize_evaluator(record: EvaluatorRelease) -> dict[str, Any]:
    status, status_label = _record_status(record)
    return {
        "identifier": str(record.id),
        "label": f"Evaluator {record.version}",
        "secondary_label": record.source_revision[:12],
        "description": record.source_url,
        "curation_status": status,
        "curation_label": status_label,
        "detail_url": "",
    }


def _serialize_result(record: Result) -> dict[str, Any]:
    status, status_label = _record_status(record)
    return {
        "identifier": str(record.id),
        "label": f"{record.decoder_version} on {record.circuit_revision}",
        "secondary_label": str(record.id)[:12],
        "description": record.description or "Exact published result",
        "curation_status": status,
        "curation_label": status_label,
        "detail_url": reverse("results:detail", args=[record.id]),
    }


def _serialize_artifact(record: Artifact) -> dict[str, Any]:
    return {
        "identifier": str(record.id),
        "label": record.original_filename,
        "secondary_label": f"{record.sha256[:12]}… · {record.byte_size} bytes",
        "description": record.media_type,
        "curation_status": "frozen",
        "curation_label": "Frozen file",
        "detail_url": reverse("artifacts:detail", args=[record.id]),
    }


def _serialize_submission_noise_model(record: NoiseModel) -> dict[str, Any]:
    serialized = _serialize_noise_model(record)
    serialized["identifier"] = str(record.id)
    return serialized


PICKER_SPECS = {
    "noise-models": RecordPickerSpec(
        key="noise-models",
        singular_label="noise model",
        plural_label="noise models",
        parameter_name="noise_model",
        identifier_field="slug",
        public_queryset=_public_noise_models,
        search_fields=("name", "slug", "short_description"),
        serialize_record=_serialize_noise_model,
    ),
    "submission-noise-models": RecordPickerSpec(
        key="submission-noise-models",
        singular_label="noise model",
        plural_label="noise models",
        parameter_name="noise_model",
        identifier_field="id",
        public_queryset=_submission_noise_models,
        search_fields=("name", "slug", "short_description"),
        serialize_record=_serialize_submission_noise_model,
    ),
    "decoder-versions": RecordPickerSpec(
        key="decoder-versions",
        singular_label="decoder version",
        plural_label="decoder versions",
        parameter_name="decoder_version",
        identifier_field="id",
        public_queryset=_published_decoders,
        search_fields=("name", "version", "slug", "description"),
        serialize_record=_serialize_decoder,
    ),
    "circuit-revisions": RecordPickerSpec(
        key="circuit-revisions",
        singular_label="circuit revision",
        plural_label="circuit revisions",
        parameter_name="circuit_revision",
        identifier_field="id",
        public_queryset=_published_circuits,
        search_fields=("name", "slug", "description"),
        serialize_record=_serialize_circuit,
    ),
    "machines": RecordPickerSpec(
        key="machines",
        singular_label="machine",
        plural_label="machines",
        parameter_name="machine",
        identifier_field="id",
        public_queryset=_published_machines,
        search_fields=("slug", "description", "machine_class"),
        serialize_record=_serialize_machine,
    ),
    "evaluator-releases": RecordPickerSpec(
        key="evaluator-releases",
        singular_label="evaluator release",
        plural_label="evaluator releases",
        parameter_name="evaluator_version",
        identifier_field="id",
        public_queryset=_published_evaluators,
        search_fields=("version", "source_url", "source_revision"),
        serialize_record=_serialize_evaluator,
    ),
    "results": RecordPickerSpec(
        key="results",
        singular_label="result",
        plural_label="results",
        parameter_name="supersedes_result",
        identifier_field="id",
        public_queryset=_published_results,
        search_fields=(
            "id",
            "description",
            "decoder_version__name",
            "circuit_revision__name",
        ),
        serialize_record=_serialize_result,
    ),
    "artifacts": RecordPickerSpec(
        key="artifacts",
        singular_label="frozen file",
        plural_label="frozen files",
        parameter_name="artifact",
        identifier_field="id",
        public_queryset=_artifacts,
        search_fields=("original_filename", "sha256", "media_type"),
        serialize_record=_serialize_artifact,
    ),
}


def get_picker_spec(key: str) -> RecordPickerSpec:
    """Return an explicitly permitted picker definition."""

    try:
        return PICKER_SPECS[key]
    except KeyError as error:
        raise LookupError(key) from error


def search_picker_records(spec: RecordPickerSpec, query: str) -> QuerySet:
    records = spec.public_queryset()
    if not query:
        return records
    predicate = Q()
    for field in spec.search_fields:
        predicate |= Q(**{f"{field}__icontains": query})
    return records.filter(predicate)


def selected_picker_records(
    spec: RecordPickerSpec,
    identifiers: Sequence[str],
) -> list[dict[str, Any]]:
    """Resolve selected public records while preserving URL parameter order."""

    normalized = tuple(dict.fromkeys(value for value in identifiers if value))
    records = {
        str(getattr(record, spec.identifier_field)): record
        for record in spec.public_queryset().filter(
            **{f"{spec.identifier_field}__in": normalized}
        )
    }
    return [
        serialize_picker_record(spec, records[value])
        for value in normalized
        if value in records
    ]


def serialize_picker_record(
    spec: RecordPickerSpec,
    record: Any,
) -> dict[str, Any]:
    return spec.serialize_record(record)


def record_picker_context(
    key: str,
    selected_identifiers: Sequence[str],
    *,
    input_name: str | None = None,
) -> dict[str, Any]:
    spec = get_picker_spec(key)
    return {
        "key": spec.key,
        "singular_label": spec.singular_label,
        "plural_label": spec.plural_label,
        "input_name": input_name or spec.parameter_name,
        "search_url": reverse("pickers:records", args=[spec.key]),
        "selected_records": selected_picker_records(spec, selected_identifiers),
    }
