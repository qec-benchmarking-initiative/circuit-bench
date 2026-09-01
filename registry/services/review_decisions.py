"""Transactional review decisions for unpublished exact candidates."""

from django.db import transaction

from accounts.models import Account
from registry.models import ModerationEvent
from registry.models.common import REVIEW_QUEUE_STATES, LifecycleState
from registry.services.histories import (
    append_history_event,
    latest_snapshot_event,
    submission_snapshot,
)
from registry.services.submissions import (
    MODEL_BY_KIND,
    SubmissionStateError,
    candidate_review_route,
    submission_payload_for_record,
)
from registry.submission_policy import SubmissionKind


class ReviewDecisionError(Exception):
    """A moderation decision could not be applied."""


@transaction.atomic
def request_changes(
    kind: SubmissionKind | str,
    record_id,
    *,
    reviewer: Account,
    note: str,
):
    """Return a queued candidate to its uploader with a review note."""

    kind = SubmissionKind(kind)
    record = _locked_review_candidate(kind, record_id, reviewer=reviewer)
    note = _required_note(note)
    previous_state = record.state
    reviewed_snapshot = latest_snapshot_event(kind.value, record)
    append_history_event(
        kind=kind.value,
        record=record,
        actor=reviewer,
        action=ModerationEvent.Action.REQUESTED_CHANGES,
        note=note,
        details={
            "policy_version": "0.1",
            "previous_state": previous_state,
            "projected_state": LifecycleState.CHANGES_REQUESTED,
        },
        caused_by=reviewed_snapshot,
        visibility=ModerationEvent.Visibility.UPLOADER,
    )
    record.state = LifecycleState.CHANGES_REQUESTED
    record.save(update_fields=["state"])
    return record


@transaction.atomic
def reject_submission(
    kind: SubmissionKind | str,
    record_id,
    *,
    reviewer: Account,
    note: str,
):
    """Reject a queued exact candidate as a terminal, private record."""

    kind = SubmissionKind(kind)
    record = _locked_review_candidate(kind, record_id, reviewer=reviewer)
    note = _required_note(note)
    previous_state = record.state
    reviewed_snapshot = latest_snapshot_event(kind.value, record)
    append_history_event(
        kind=kind.value,
        record=record,
        actor=reviewer,
        action=ModerationEvent.Action.REJECTED,
        note=note,
        details={
            "policy_version": "0.1",
            "previous_state": previous_state,
            "projected_state": LifecycleState.REJECTED,
        },
        caused_by=reviewed_snapshot,
        visibility=ModerationEvent.Visibility.UPLOADER,
    )
    record.state = LifecycleState.REJECTED
    record.save(update_fields=["state"])
    return record


@transaction.atomic
def resubmit_for_review(
    kind: SubmissionKind | str,
    record_id,
    *,
    actor: Account,
):
    """Return a changes-requested candidate to its original review route."""

    kind = SubmissionKind(kind)
    record = _locked_managed_candidate(kind, record_id, actor=actor)
    if record.state != LifecycleState.CHANGES_REQUESTED:
        raise SubmissionStateError(
            "Only a candidate with requested changes can be resubmitted."
        )

    projected_state = candidate_review_route(kind, record)
    payload = submission_payload_for_record(kind, record)
    previous_snapshot = latest_snapshot_event(kind.value, record)
    append_history_event(
        kind=kind.value,
        record=record,
        actor=actor,
        action=ModerationEvent.Action.RESUBMITTED,
        note="Resubmitted after responding to the latest review note.",
        details={
            "policy_version": "0.1",
            "previous_state": LifecycleState.CHANGES_REQUESTED,
            "projected_state": projected_state,
        },
        payload_snapshot=submission_snapshot(kind.value, payload),
        caused_by=previous_snapshot,
        visibility=ModerationEvent.Visibility.UPLOADER,
    )
    record.state = projected_state
    record.save(update_fields=["state"])
    return record


def _locked_review_candidate(kind, record_id, *, reviewer):
    if not reviewer.is_active or not reviewer.is_admin:
        raise PermissionError("Only active admins may review submissions.")
    model = MODEL_BY_KIND[kind]
    try:
        record = model.objects.select_for_update().get(id=record_id)
    except model.DoesNotExist as error:
        raise SubmissionStateError("Submission not found.") from error
    if record.state not in REVIEW_QUEUE_STATES:
        raise SubmissionStateError(
            "Only submissions currently waiting for review can receive a decision."
        )
    return record


def _locked_managed_candidate(kind, record_id, *, actor):
    if not actor.is_active:
        raise PermissionError("Inactive accounts cannot manage submissions.")
    model = MODEL_BY_KIND[kind]
    try:
        record = model.objects.select_for_update().get(id=record_id)
    except model.DoesNotExist as error:
        raise SubmissionStateError("Submission not found.") from error
    if record.submitted_by_id != actor.id and not actor.is_admin:
        raise PermissionError("Only the uploader or an admin may manage this record.")
    return record


def _required_note(note):
    note = note.strip()
    if not note:
        raise ReviewDecisionError("A review note is required.")
    return note
