"""Transparent discovery ordering, separate from scientific comparison tables.

The featured policies in this module are deliberately small and provisional.
They order already-public catalogue records; they do not decide publication,
moderation, or scientific merit.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from django.db.models import Case, IntegerField, QuerySet, Value, When
from django.db.models.functions import Lower


class CatalogueKind(StrEnum):
    DECODER = "decoder"
    CIRCUIT = "circuit"
    NOISE_MODEL = "noise_model"
    BENCHMARK = "benchmark"


class CatalogueOrderingMode(StrEnum):
    FEATURED = "featured"
    SEARCH_RELEVANCE = "search_relevance"
    MANUAL = "manual"


@dataclass(frozen=True)
class CatalogueOrderingSelection:
    """The ordering mode selected from query and explicit table state."""

    mode: CatalogueOrderingMode
    search_query: str = ""


@dataclass(frozen=True)
class OrderingMetadata:
    """User-visible disclosure for an ordering mode."""

    key: str
    label: str
    explanation: str
    provisional: bool
    policy_key: str | None

    def as_context(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "explanation": self.explanation,
            "provisional": self.provisional,
            "policy_key": self.policy_key,
        }


@dataclass(frozen=True)
class FeaturedReason:
    """User-visible reason for one record's featured position."""

    label: str
    detail: str

    def as_context(self) -> dict[str, str]:
        return {"label": self.label, "detail": self.detail}


@runtime_checkable
class CurationPolicy(Protocol):
    """Named interface implemented by catalogue featured policies."""

    key: str
    kind: CatalogueKind
    label: str
    explanation: str
    provisional: bool

    def apply(self, queryset: QuerySet) -> QuerySet: ...

    def reason(self, record: Any) -> FeaturedReason: ...


@dataclass(frozen=True)
class FeaturedPolicy:
    """A deterministic, disclosed ordering for one catalogue kind."""

    key: str
    kind: CatalogueKind
    label: str
    explanation: str
    required_annotations: tuple[str, ...]
    ordering: tuple[str, ...]
    annotate: Callable[[QuerySet], QuerySet]
    reason_builder: Callable[[Any], FeaturedReason]
    provisional: bool = True

    def apply(self, queryset: QuerySet) -> QuerySet:
        available_annotations = set(queryset.query.annotations)
        missing = set(self.required_annotations) - available_annotations
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise ValueError(
                f"{self.key} requires catalogue annotations: {missing_list}."
            )
        return self.annotate(queryset).order_by(*self.ordering)

    def reason(self, record: Any) -> FeaturedReason:
        return self.reason_builder(record)

    def metadata(self) -> OrderingMetadata:
        return OrderingMetadata(
            key=CatalogueOrderingMode.FEATURED,
            label=self.label,
            explanation=self.explanation,
            provisional=self.provisional,
            policy_key=self.key,
        )


@dataclass(frozen=True)
class SearchRelevancePolicy:
    """Deterministic text relevance kept outside the curation interface."""

    key: str
    kind: CatalogueKind
    exact_fields: tuple[str, ...]
    prefix_fields: tuple[str, ...]
    tie_fields: tuple[str, ...]

    def apply(self, queryset: QuerySet, query: str) -> QuerySet:
        query = query.strip()
        if not query:
            raise ValueError("Search relevance requires a non-empty query.")

        cases = []
        rank = 0
        for field in self.exact_fields:
            cases.append(When(**{f"{field}__iexact": query}, then=Value(rank)))
            rank += 1
        for field in self.prefix_fields:
            cases.append(When(**{f"{field}__istartswith": query}, then=Value(rank)))
            rank += 1

        queryset = queryset.annotate(
            _curation_search_rank=Case(
                *cases,
                default=Value(rank),
                output_field=IntegerField(),
            ),
            _curation_search_name=Lower("name"),
        )
        ordering = ["_curation_search_rank", "_curation_search_name"]
        for field in self.tie_fields:
            annotation = f"_curation_search_{field}"
            queryset = queryset.annotate(**{annotation: Lower(field)})
            ordering.append(annotation)
        ordering.append("id")
        return queryset.order_by(*ordering)

    def metadata(self) -> OrderingMetadata:
        return OrderingMetadata(
            key=CatalogueOrderingMode.SEARCH_RELEVANCE,
            label="Search relevance",
            explanation=(
                "Whole-field name, slug, or version matches appear first where those "
                "fields exist, followed by prefixes and then other matching "
                "metadata; ties use name and record ID."
            ),
            provisional=False,
            policy_key=self.key,
        )


def select_catalogue_ordering(
    *,
    search_query: str,
    raw_sort: str,
) -> CatalogueOrderingSelection:
    """Select manual, search, or featured ordering without mixing their meanings."""

    if raw_sort.strip():
        return CatalogueOrderingSelection(CatalogueOrderingMode.MANUAL)
    query = search_query.strip()
    if query:
        return CatalogueOrderingSelection(
            CatalogueOrderingMode.SEARCH_RELEVANCE,
            search_query=query,
        )
    return CatalogueOrderingSelection(CatalogueOrderingMode.FEATURED)


def featured_policy(kind: CatalogueKind | str) -> FeaturedPolicy:
    """Return the named provisional policy for a catalogue kind."""

    return FEATURED_POLICIES[CatalogueKind(kind)]


def search_relevance_policy(kind: CatalogueKind | str) -> SearchRelevancePolicy:
    return SEARCH_RELEVANCE_POLICIES[CatalogueKind(kind)]


def apply_featured_ordering(
    queryset: QuerySet,
    kind: CatalogueKind | str,
) -> QuerySet:
    return featured_policy(kind).apply(queryset)


def apply_search_relevance(
    queryset: QuerySet,
    kind: CatalogueKind | str,
    query: str,
) -> QuerySet:
    return search_relevance_policy(kind).apply(queryset, query)


def featured_reason(record: Any, kind: CatalogueKind | str) -> FeaturedReason:
    return featured_policy(kind).reason(record)


def ordering_metadata(
    selection: CatalogueOrderingSelection,
    kind: CatalogueKind | str,
) -> OrderingMetadata:
    """Build the disclosure placed beside an overview's current ordering."""

    if selection.mode == CatalogueOrderingMode.FEATURED:
        return featured_policy(kind).metadata()
    if selection.mode == CatalogueOrderingMode.SEARCH_RELEVANCE:
        return search_relevance_policy(kind).metadata()
    return OrderingMetadata(
        key=CatalogueOrderingMode.MANUAL,
        label="Selected table order",
        explanation="The explicit column order recorded in this URL is active.",
        provisional=False,
        policy_key=None,
    )


def _base_featured_annotations(queryset: QuerySet) -> QuerySet:
    return queryset.annotate(_curation_featured_name=Lower("name"))


def _versioned_featured_annotations(queryset: QuerySet) -> QuerySet:
    return _base_featured_annotations(queryset).annotate(
        _curation_featured_version=Lower("version")
    )


def _noise_model_featured_annotations(queryset: QuerySet) -> QuerySet:
    return _base_featured_annotations(queryset).annotate(
        _curation_featured_recognition=Case(
            When(curation_status="official", then=Value(0)),
            When(curation_status="community", then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
    )


def _benchmark_featured_annotations(queryset: QuerySet) -> QuerySet:
    return _versioned_featured_annotations(queryset).annotate(
        _curation_featured_recognition=Case(
            When(recognition_status="official", then=Value(0)),
            When(recognition_status="admin_approved", then=Value(1)),
            When(recognition_status="community_submitted", then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    )


def _activity_reason(record: Any, noun: str) -> FeaturedReason:
    count = record.published_result_count
    return FeaturedReason(
        label=f"{count} published result{'s' if count != 1 else ''}",
        detail=(
            f"This provisional {noun} order uses published-result activity; "
            "equal counts use publication date, name, then record ID."
        ),
    )


def _decoder_reason(record: Any) -> FeaturedReason:
    return _activity_reason(record, "decoder")


def _circuit_reason(record: Any) -> FeaturedReason:
    return _activity_reason(record, "circuit")


def _noise_model_reason(record: Any) -> FeaturedReason:
    count = record.circuit_count
    return FeaturedReason(
        label=(
            f"{record.get_curation_status_display()} · {count} published "
            f"circuit{'s' if count != 1 else ''}"
        ),
        detail=(
            "This provisional noise-model order uses disclosed curation standing, "
            "then published-circuit usage, name, and record ID."
        ),
    )


def _benchmark_reason(record: Any) -> FeaturedReason:
    count = record.published_attempt_count
    return FeaturedReason(
        label=(
            f"{record.get_recognition_status_display()} · {count} published "
            f"attempt{'s' if count != 1 else ''}"
        ),
        detail=(
            "This provisional benchmark order uses disclosed recognition, then "
            "published-attempt activity, publication date, name, and record ID."
        ),
    )


FEATURED_POLICIES: dict[CatalogueKind, FeaturedPolicy] = {
    CatalogueKind.DECODER: FeaturedPolicy(
        key="provisional-featured-decoders-0.1",
        kind=CatalogueKind.DECODER,
        label="Featured decoders (provisional)",
        explanation=(
            "Discovery order uses published-result activity, then publication "
            "date, name, version, and record ID. It is not a scientific ranking."
        ),
        required_annotations=("published_result_count",),
        ordering=(
            "-published_result_count",
            "-published_at",
            "_curation_featured_name",
            "_curation_featured_version",
            "id",
        ),
        annotate=_versioned_featured_annotations,
        reason_builder=_decoder_reason,
    ),
    CatalogueKind.CIRCUIT: FeaturedPolicy(
        key="provisional-featured-circuits-0.1",
        kind=CatalogueKind.CIRCUIT,
        label="Featured circuits (provisional)",
        explanation=(
            "Discovery order uses published-result activity, then publication "
            "date, name, and record ID. It is not a scientific ranking."
        ),
        required_annotations=("published_result_count",),
        ordering=(
            "-published_result_count",
            "-published_at",
            "_curation_featured_name",
            "id",
        ),
        annotate=_base_featured_annotations,
        reason_builder=_circuit_reason,
    ),
    CatalogueKind.NOISE_MODEL: FeaturedPolicy(
        key="provisional-featured-noise-models-0.1",
        kind=CatalogueKind.NOISE_MODEL,
        label="Featured noise models (provisional)",
        explanation=(
            "Discovery order uses disclosed curation standing, then the number "
            "of published circuits, name, and record ID. It is not a scientific "
            "ranking."
        ),
        required_annotations=("circuit_count",),
        ordering=(
            "_curation_featured_recognition",
            "-circuit_count",
            "_curation_featured_name",
            "id",
        ),
        annotate=_noise_model_featured_annotations,
        reason_builder=_noise_model_reason,
    ),
    CatalogueKind.BENCHMARK: FeaturedPolicy(
        key="provisional-featured-benchmarks-0.1",
        kind=CatalogueKind.BENCHMARK,
        label="Featured benchmarks (provisional)",
        explanation=(
            "Discovery order uses disclosed recognition, then published-attempt "
            "activity, publication date, name, version, and record ID. It is not "
            "a scientific ranking."
        ),
        required_annotations=("published_attempt_count",),
        ordering=(
            "_curation_featured_recognition",
            "-published_attempt_count",
            "-published_at",
            "_curation_featured_name",
            "_curation_featured_version",
            "id",
        ),
        annotate=_benchmark_featured_annotations,
        reason_builder=_benchmark_reason,
    ),
}


SEARCH_RELEVANCE_POLICIES: dict[CatalogueKind, SearchRelevancePolicy] = {
    CatalogueKind.DECODER: SearchRelevancePolicy(
        key="decoder-name-slug-version-relevance-0.1",
        kind=CatalogueKind.DECODER,
        exact_fields=("name", "slug", "version"),
        prefix_fields=("name", "slug", "version"),
        tie_fields=("version",),
    ),
    CatalogueKind.CIRCUIT: SearchRelevancePolicy(
        key="circuit-name-slug-relevance-0.1",
        kind=CatalogueKind.CIRCUIT,
        exact_fields=("name", "slug"),
        prefix_fields=("name", "slug"),
        tie_fields=(),
    ),
    CatalogueKind.NOISE_MODEL: SearchRelevancePolicy(
        key="noise-model-name-slug-relevance-0.1",
        kind=CatalogueKind.NOISE_MODEL,
        exact_fields=("name", "slug"),
        prefix_fields=("name", "slug"),
        tie_fields=(),
    ),
    CatalogueKind.BENCHMARK: SearchRelevancePolicy(
        key="benchmark-name-slug-version-relevance-0.1",
        kind=CatalogueKind.BENCHMARK,
        exact_fields=("name", "slug", "version"),
        prefix_fields=("name", "slug", "version"),
        tie_fields=("version",),
    ),
}
