"""Allow-listed definitions for searchable related-record pickers.

Pickers construct reproducible URL state.  They deliberately do not own the
scientific filtering predicates, which remain in the domain query services.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.urls import reverse

from registry.models import NoiseModel


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
        getattr(record, spec.identifier_field): record
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
) -> dict[str, Any]:
    spec = get_picker_spec(key)
    return {
        "key": spec.key,
        "singular_label": spec.singular_label,
        "plural_label": spec.plural_label,
        "input_name": spec.parameter_name,
        "search_url": reverse("pickers:records", args=[spec.key]),
        "selected_records": selected_picker_records(spec, selected_identifiers),
    }
