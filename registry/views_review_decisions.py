"""HTTP forms for review decisions and explicit contributor resubmission."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from registry.forms_review_decisions import ResubmissionForm, ReviewNoteForm
from registry.models.common import REVIEW_QUEUE_STATES, LifecycleState
from registry.services.review_decisions import (
    ReviewDecisionError,
    reject_submission,
    request_changes,
    resubmit_for_review,
)
from registry.services.submissions import (
    MODEL_BY_KIND,
    SubmissionStateError,
    record_label,
)
from registry.submission_policy import ENABLED_SUBMISSION_KINDS, SubmissionKind
from registry.submission_specs import get_submission_spec


@login_required
@require_http_methods(["GET", "POST"])
def request_changes_view(request, kind, record_id):
    return _review_decision_view(
        request,
        kind,
        record_id,
        decision="request_changes",
    )


@login_required
@require_http_methods(["GET", "POST"])
def reject_view(request, kind, record_id):
    return _review_decision_view(request, kind, record_id, decision="reject")


@login_required
@require_http_methods(["GET", "POST"])
def resubmit_view(request, kind, record_id):
    kind = _kind_or_404(kind)
    record = _managed_record(request, kind, record_id)
    if record.state != LifecycleState.CHANGES_REQUESTED:
        raise PermissionDenied(
            "Only a candidate with requested changes can be resubmitted."
        )
    form = ResubmissionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            record = resubmit_for_review(kind, record.id, actor=request.user)
        except (ReviewDecisionError, SubmissionStateError) as error:
            messages.error(request, f"Could not resubmit candidate: {error}")
        else:
            messages.success(
                request,
                f"{record_label(kind, record)} returned to the review queue.",
            )
            return redirect("submissions:record", kind=kind.value, record_id=record.id)
    return render(
        request,
        "submissions/resubmit.html",
        {
            "kind": kind.value,
            "record": record,
            "record_label": record_label(kind, record),
            "spec": get_submission_spec(kind),
            "form": form,
        },
    )


def _review_decision_view(request, kind, record_id, *, decision):
    if not request.user.is_admin:
        raise PermissionDenied
    kind = _kind_or_404(kind)
    model = MODEL_BY_KIND[kind]
    record = get_object_or_404(
        model.objects.select_related("submitted_by"), id=record_id
    )
    if record.state not in REVIEW_QUEUE_STATES:
        raise PermissionDenied("This candidate is not waiting for review.")

    form = ReviewNoteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = (
            request_changes if decision == "request_changes" else reject_submission
        )
        try:
            record = service(
                kind,
                record.id,
                reviewer=request.user,
                note=form.cleaned_data["note"],
            )
        except (ReviewDecisionError, SubmissionStateError) as error:
            messages.error(request, f"Could not record review decision: {error}")
        else:
            label = "Changes requested" if decision == "request_changes" else "Rejected"
            messages.success(request, f"{label}: {record_label(kind, record)}.")
            return redirect("submissions:review")

    return render(
        request,
        "submissions/review_decision.html",
        {
            "decision": decision,
            "decision_label": (
                "Request changes" if decision == "request_changes" else "Reject"
            ),
            "kind": kind.value,
            "record": record,
            "record_label": record_label(kind, record),
            "spec": get_submission_spec(kind),
            "form": form,
        },
    )


def _kind_or_404(raw):
    from django.http import Http404

    try:
        kind = SubmissionKind(raw)
        if kind not in ENABLED_SUBMISSION_KINDS:
            raise ValueError
        return kind
    except ValueError as error:
        raise Http404("Unknown submission kind") from error


def _managed_record(request, kind, record_id):
    model = MODEL_BY_KIND[kind]
    record = get_object_or_404(
        model.objects.select_related("submitted_by"), id=record_id
    )
    if record.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return record
