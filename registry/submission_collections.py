"""Small cross-kind queues for profile and moderation pages.

The registry stores each scientific kind in its own relational table.  These
account-facing queues intentionally issue one bounded query per selected kind,
then merge the lightweight presentation rows for cross-kind sorting and
pagination.  That keeps the scientific models normalized without introducing a
duplicated generic-submission table.
"""

from django.db.models import Prefetch, Q

from registry.models import ModerationEvent
from registry.services.submissions import MODEL_BY_KIND
from registry.submission_policy import SubmissionKind
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
    for kind in SubmissionKind:
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
            )
        )
        rows.extend(submission_rows(kind, queryset, admin=admin, actor=actor))
    return sorted(rows, key=lambda row: _sort_key(row, sort), reverse=_reverse(sort))


def normalise_collection_controls(request):
    kind = request.GET.get("kind", "").strip()
    if kind not in {"", *(item.value for item in SubmissionKind)}:
        kind = ""
    state = request.GET.get("pending_state", "").strip()
    if state not in {"", "pending_review", "pending_reapproval"}:
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
