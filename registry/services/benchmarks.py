"""Read-only queries and integrity summaries for public benchmark pages."""

from dataclasses import dataclass

from django.db.models import Count, Prefetch, Q, QuerySet

from registry.models import (
    BenchmarkAttempt,
    BenchmarkAttemptResult,
    BenchmarkRevision,
    BenchmarkRevisionItem,
)

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


@dataclass(frozen=True)
class AttemptItemSummary:
    """One manifest position and the result linked to it by an attempt."""

    item: BenchmarkRevisionItem
    membership: BenchmarkAttemptResult | None
    issue: str | None


@dataclass(frozen=True)
class AttemptSummary:
    """A display-safe validation of one published benchmark attempt."""

    attempt: BenchmarkAttempt
    items: tuple[AttemptItemSummary, ...]
    required_count: int
    required_result_count: int
    is_complete: bool
    issues: tuple[str, ...]
    unexpected_memberships: tuple[BenchmarkAttemptResult, ...]


def public_benchmark_catalogue(
    *,
    query: str = "",
    recognition_status: str = "",
) -> QuerySet[BenchmarkRevision]:
    """Return published exact benchmark revisions for discovery."""

    public_circuit = Q(items__circuit_revision__state__in=PUBLIC_DETAIL_STATES)
    benchmarks = (
        BenchmarkRevision.objects.filter(state="published")
        .annotate(
            item_count=Count(
                "items__circuit_revision_id",
                filter=public_circuit,
                distinct=True,
            ),
            required_item_count=Count(
                "items__circuit_revision_id",
                filter=public_circuit & Q(items__is_required=True),
                distinct=True,
            ),
            optional_item_count=Count(
                "items__circuit_revision_id",
                filter=public_circuit & Q(items__is_required=False),
                distinct=True,
            ),
            published_attempt_count=Count(
                "attempts",
                filter=Q(attempts__state="published"),
                distinct=True,
            ),
        )
        .select_related("schema_release", "submitted_by")
    )

    query = query.strip()
    if query:
        benchmarks = benchmarks.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(version__icontains=query)
            | Q(description__icontains=query)
            | Q(revision_description__icontains=query)
        )
    if recognition_status in BenchmarkRevision.RecognitionStatus.values:
        benchmarks = benchmarks.filter(recognition_status=recognition_status)
    return benchmarks


def public_benchmark_detail() -> QuerySet[BenchmarkRevision]:
    """Return the bounded public graph needed by an exact revision page."""

    public_items = (
        BenchmarkRevisionItem.objects.filter(
            circuit_revision__state__in=PUBLIC_DETAIL_STATES
        )
        .select_related("circuit_revision")
        .order_by("position", "circuit_revision_id")
    )
    public_memberships = (
        BenchmarkAttemptResult.objects.filter(
            circuit_revision__state__in=PUBLIC_DETAIL_STATES,
            result__state__in=PUBLIC_DETAIL_STATES,
        )
        .select_related(
            "circuit_revision",
            "result",
            "result__circuit_revision",
            "result__decoder_version",
            "result__evaluator_version",
            "result__machine",
        )
        .order_by("circuit_revision_id", "result_id")
    )
    public_attempts = (
        BenchmarkAttempt.objects.filter(state="published")
        .select_related("decoder_version", "submitted_by")
        .prefetch_related(
            Prefetch(
                "result_memberships",
                queryset=public_memberships,
                to_attr="public_result_memberships",
            )
        )
        .order_by("-published_at", "id")
    )
    return (
        BenchmarkRevision.objects.filter(state__in=PUBLIC_DETAIL_STATES)
        .annotate(
            manifest_item_count=Count("items__circuit_revision_id", distinct=True),
            manifest_required_item_count=Count(
                "items__circuit_revision_id",
                filter=Q(items__is_required=True),
                distinct=True,
            ),
        )
        .select_related(
            "schema_release",
            "manifest_artifact",
            "submitted_by",
            "previous_revision",
        )
        .prefetch_related(
            Prefetch("items", queryset=public_items, to_attr="public_items"),
            Prefetch("attempts", queryset=public_attempts, to_attr="public_attempts"),
        )
    )


def inherited_benchmark_description(
    benchmark: BenchmarkRevision,
) -> BenchmarkRevision | None:
    """Return the closest public revision at or before this one with a description."""

    current: BenchmarkRevision | None = benchmark
    visited: set[object] = set()
    while current is not None and current.pk not in visited:
        visited.add(current.pk)
        if current.description and current.description.strip():
            return current
        predecessor = current.previous_revision
        current = (
            predecessor
            if predecessor is not None and predecessor.state in PUBLIC_DETAIL_STATES
            else None
        )
    return None


def public_benchmark_predecessor(
    benchmark: BenchmarkRevision,
) -> BenchmarkRevision | None:
    predecessor = benchmark.previous_revision
    if predecessor is not None and predecessor.state in PUBLIC_DETAIL_STATES:
        return predecessor
    return None


def public_benchmark_successor(
    benchmark: BenchmarkRevision,
) -> BenchmarkRevision | None:
    return (
        BenchmarkRevision.objects.filter(
            previous_revision=benchmark,
            state__in=PUBLIC_DETAIL_STATES,
        )
        .order_by("id")
        .first()
    )


def summarise_attempts(benchmark: BenchmarkRevision) -> tuple[AttemptSummary, ...]:
    """Validate public attempt membership against the frozen ordered manifest.

    This deliberately checks only membership and provenance. It never pools result
    data and never derives an aggregate benchmark score.
    """

    manifest_items = tuple(benchmark.public_items)
    manifest_by_circuit = {item.circuit_revision_id: item for item in manifest_items}
    hidden_item_count = benchmark.manifest_item_count - len(manifest_items)
    summaries: list[AttemptSummary] = []

    for attempt in benchmark.public_attempts:
        memberships_by_circuit: dict[object, list[BenchmarkAttemptResult]] = {}
        for membership in attempt.public_result_memberships:
            memberships_by_circuit.setdefault(
                membership.circuit_revision_id, []
            ).append(membership)

        issues: list[str] = []
        if hidden_item_count:
            issues.append(
                "The manifest contains a circuit revision that is not public."
            )
        item_summaries: list[AttemptItemSummary] = []
        required_count = benchmark.manifest_required_item_count
        required_result_count = 0

        for item in manifest_items:
            memberships = memberships_by_circuit.get(item.circuit_revision_id, [])
            membership = memberships[0] if len(memberships) == 1 else None
            item_issue: str | None = None
            if len(memberships) != 1:
                if item.is_required:
                    item_issue = "Required circuit does not have exactly one result."
                    issues.append(
                        f"Manifest position {item.position} does not have exactly "
                        "one public result."
                    )
                elif len(memberships) > 1:
                    item_issue = "Optional circuit has more than one result."
                    issues.append(
                        f"Manifest position {item.position} has multiple results."
                    )
            else:
                result = membership.result
                if result.circuit_revision_id != item.circuit_revision_id:
                    item_issue = "Result circuit does not match this manifest item."
                    issues.append(
                        f"Manifest position {item.position} links a result for a "
                        "different circuit."
                    )
                elif result.decoder_version_id != attempt.decoder_version_id:
                    item_issue = "Result decoder does not match the attempt decoder."
                    issues.append(
                        f"Manifest position {item.position} links a result for a "
                        "different decoder."
                    )
                elif item.is_required:
                    required_result_count += 1

            item_summaries.append(
                AttemptItemSummary(
                    item=item,
                    membership=membership,
                    issue=item_issue,
                )
            )

        unexpected = tuple(
            membership
            for membership in attempt.public_result_memberships
            if membership.circuit_revision_id not in manifest_by_circuit
        )
        if unexpected:
            issues.append(
                f"The attempt contains {len(unexpected)} result"
                f"{'s' if len(unexpected) != 1 else ''} outside the manifest."
            )

        summaries.append(
            AttemptSummary(
                attempt=attempt,
                items=tuple(item_summaries),
                required_count=required_count,
                required_result_count=required_result_count,
                is_complete=not issues and required_result_count == required_count,
                issues=tuple(issues),
                unexpected_memberships=unexpected,
            )
        )
    return tuple(summaries)
