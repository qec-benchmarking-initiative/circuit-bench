"""Small cross-kind queues for profile and moderation pages.

The registry stores each scientific kind in its own relational table.  These
account-facing queues intentionally issue one bounded query per selected kind,
then merge the lightweight presentation rows for cross-kind sorting and
pagination.  That keeps the scientific models normalized without introducing a
duplicated generic-submission table.
"""

from django.db.models import Prefetch, Q
from django.urls import reverse

from registry.models import (
    BenchmarkAttempt,
    BenchmarkRevision,
    ModerationEvent,
    NoiseModel,
)
from registry.models.common import PROFILE_PENDING_STATES, REVIEW_QUEUE_STATES
from registry.services.submissions import MODEL_BY_KIND
from registry.submission_policy import ENABLED_SUBMISSION_KINDS, SubmissionKind
from registry.submission_presenters import submission_rows

SORT_CHOICES = (
    ("-submitted", "Newest submitted first"),
    ("submitted", "Oldest submitted first"),
    ("record", "Record name A–Z"),
    ("-record", "Record name Z–A"),
    ("kind", "Record kind A–Z"),
    ("state", "State A–Z"),
    ("-withdrawn", "Most recently withdrawn first"),
)
VALID_SORTS = {value for value, _label in SORT_CHOICES}
SPECIALIZED_KINDS = ("noise_model", "benchmark", "benchmark_attempt")


def collect_submission_rows(
    *,
    states,
    actor,
    owner=None,
    admin=False,
    query="",
    kind_filter="",
    sort="-submitted",
    withdrawn_since=None,
):
    sort = sort if sort in VALID_SORTS else "-submitted"
    rows = []
    for kind in ENABLED_SUBMISSION_KINDS:
        if kind_filter and kind.value != kind_filter:
            continue
        queryset = MODEL_BY_KIND[kind].objects.filter(state__in=states)
        if owner is not None:
            queryset = queryset.filter(submitted_by=owner)
        if withdrawn_since is not None:
            queryset = queryset.filter(withdrawn_at__gte=withdrawn_since)
        queryset = _apply_search(queryset, kind, query)
        queryset = queryset.select_related(
            "submitted_by", *_select_related(kind)
        ).prefetch_related(
            Prefetch(
                "moderation_events",
                queryset=ModerationEvent.objects.filter(action="approved")
                .select_related("actor_account")
                .order_by("-sequence", "-id"),
                to_attr="approval_events",
            ),
            Prefetch(
                "moderation_events",
                queryset=ModerationEvent.objects.filter(
                    action__in=(
                        ModerationEvent.Action.REQUESTED_CHANGES,
                        ModerationEvent.Action.REJECTED,
                    )
                )
                .select_related("actor_account")
                .order_by("-sequence", "-id"),
                to_attr="review_decision_events",
            ),
        )
        rows.extend(submission_rows(kind, queryset, admin=admin, actor=actor))
    return sort_submission_rows(rows, sort)


def collect_specialized_submission_rows(
    *,
    states,
    actor,
    owner=None,
    admin=False,
    query="",
    kind_filter="",
    sort="-submitted",
    withdrawn_since=None,
):
    definitions = (
        (
            "noise_model",
            "Noise model",
            NoiseModel,
            lambda record: record.name,
            lambda record: reverse("taxonomy:noise-model-candidate", args=[record.id]),
            lambda record: reverse("taxonomy:noise-model-approve", args=[record.id]),
        ),
        (
            "benchmark",
            "Benchmark revision",
            BenchmarkRevision,
            lambda record: f"{record.name} {record.version}",
            lambda record: reverse("benchmark-submissions:candidate", args=[record.id]),
            lambda record: reverse("benchmark-submissions:approve", args=[record.id]),
        ),
        (
            "benchmark_attempt",
            "Benchmark attempt",
            BenchmarkAttempt,
            lambda record: f"{record.decoder_version} on {record.benchmark_revision}",
            lambda record: reverse(
                "benchmark-submissions:attempt-candidate", args=[record.id]
            ),
            lambda record: reverse(
                "benchmark-submissions:attempt-approve", args=[record.id]
            ),
        ),
    )
    rows = []
    for kind, kind_label, model, labeler, url_for, approve_url_for in definitions:
        if kind_filter and kind_filter != kind:
            continue
        queryset = model.objects.filter(state__in=states).select_related("submitted_by")
        if model is BenchmarkAttempt:
            queryset = queryset.select_related("benchmark_revision", "decoder_version")
        if owner is not None:
            queryset = queryset.filter(submitted_by=owner)
        if withdrawn_since is not None:
            queryset = queryset.filter(withdrawn_at__gte=withdrawn_since)
        if query:
            predicate = Q(submitted_by__display_name__icontains=query)
            if model in {NoiseModel, BenchmarkRevision}:
                predicate |= Q(name__icontains=query) | Q(slug__icontains=query)
            else:
                predicate |= Q(decoder_version__name__icontains=query) | Q(
                    benchmark_revision__name__icontains=query
                )
            queryset = queryset.filter(predicate)
        for record in queryset:
            rows.append(
                {
                    "id": record.id,
                    "kind": kind,
                    "kind_label": kind_label,
                    "label": labeler(record),
                    "url": url_for(record),
                    "state": record.state,
                    "state_label": record.get_state_display(),
                    "submitted_by": record.submitted_by.display_name,
                    "created_at": record.created_at,
                    "withdrawn_at": record.withdrawn_at,
                    "approved_by": None,
                    "latest_review": None,
                    "can_approve": admin and record.state in REVIEW_QUEUE_STATES,
                    "approve_url": approve_url_for(record),
                    "review_actions": [],
                    "actions": [],
                }
            )
    return sort_submission_rows(rows, sort)


def sort_submission_rows(rows, sort):
    sort = sort if sort in VALID_SORTS else "-submitted"
    return sorted(rows, key=lambda row: _sort_key(row, sort), reverse=_reverse(sort))


def normalise_collection_controls(request, *, pending_states=PROFILE_PENDING_STATES):
    kind = request.GET.get("kind", "").strip()
    if kind not in {
        "",
        *(item.value for item in ENABLED_SUBMISSION_KINDS),
        *SPECIALIZED_KINDS,
    }:
        kind = ""
    state = request.GET.get("pending_state", "").strip()
    if state not in {"", *pending_states}:
        state = ""
    sort = request.GET.get("sort", "-submitted").strip()
    if sort not in VALID_SORTS:
        sort = "-submitted"
    return {
        "query": request.GET.get("q", "").strip(),
        "kind": kind,
        "pending_state": state,
        "sort": sort,
    }


def _apply_search(queryset, kind, raw_query):
    query = raw_query.strip()
    if not query:
        return queryset
    submitter = Q(submitted_by__display_name__icontains=query)
    if kind is SubmissionKind.DECODER:
        return queryset.filter(
            submitter
            | Q(name__icontains=query)
            | Q(version__icontains=query)
            | Q(slug__icontains=query)
        )
    if kind is SubmissionKind.CIRCUIT:
        return queryset.filter(
            submitter | Q(name__icontains=query) | Q(slug__icontains=query)
        )
    if kind is SubmissionKind.RESULT:
        return queryset.filter(
            submitter
            | Q(description__icontains=query)
            | Q(decoder_version__name__icontains=query)
            | Q(decoder_version__version__icontains=query)
            | Q(circuit_revision__name__icontains=query)
            | Q(machine__slug__icontains=query)
        ).distinct()
    return queryset.filter(
        submitter | Q(slug__icontains=query) | Q(description__icontains=query)
    )


def _select_related(kind):
    if kind is SubmissionKind.RESULT:
        return ("decoder_version", "circuit_revision", "machine")
    return ()


def _sort_key(row, sort):
    field = sort.lstrip("-")
    stable = str(row["id"])
    if field == "submitted":
        return (row["created_at"], stable)
    if field == "record":
        return (row["label"].casefold(), stable)
    if field == "kind":
        return (row["kind_label"].casefold(), row["label"].casefold(), stable)
    if field == "state":
        return (row["state_label"].casefold(), row["label"].casefold(), stable)
    return (row["withdrawn_at"] or row["created_at"], stable)


def _reverse(sort):
    return sort in {"-submitted", "-record", "-withdrawn"}
