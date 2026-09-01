import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id
from registry.demo_submissions import seed_submission_demo_data
from registry.management.commands.validate_histories import BaseHistoryValidator
from registry.models import DecoderVersion, RecordEvent
from registry.services.histories import (
    append_history_event,
    history_view,
    submission_snapshot,
)
from registry.services.review_decisions import (
    ReviewDecisionError,
    reject_submission,
    request_changes,
    resubmit_for_review,
)
from registry.services.submissions import (
    SubmissionStateError,
    create_submission,
    create_successor_submission,
    submission_payload_for_record,
    update_pending_submission,
    withdraw_submission,
)
from registry.submission_collections import collect_submission_rows
from registry.submission_policy import SubmissionKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def workflow_data(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    seed_submission_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
        "pending": DecoderVersion.objects.get(
            id=demo_id("submission/decoder/window-cluster/0.1")
        ),
    }


def test_request_changes_records_private_note_and_keeps_edit_in_place(workflow_data):
    pending = workflow_data["pending"]
    contributor = workflow_data["contributor"]
    request_changes(
        SubmissionKind.DECODER,
        pending.id,
        reviewer=workflow_data["admin"],
        note="Please state the clustering radius.",
    )

    pending.refresh_from_db()
    assert pending.state == "changes_requested"
    event = pending.record_events.get(action="requested_changes")
    assert event.note == "Please state the clustering radius."
    assert event.visibility == RecordEvent.Visibility.UPLOADER
    assert event.details["previous_state"] == "pending_review"
    assert event.caused_by.action == RecordEvent.Action.SUBMITTED
    assert event.caused_by.decoder_version_id == pending.id

    payload = submission_payload_for_record(SubmissionKind.DECODER, pending)
    payload["description"] = "Now states the clustering radius."
    updated = update_pending_submission(
        SubmissionKind.DECODER,
        pending.id,
        payload,
        actor=contributor,
    )
    assert updated.id == pending.id
    assert updated.state == "changes_requested"


def test_review_note_is_required_and_decisions_are_idempotency_safe(workflow_data):
    pending = workflow_data["pending"]
    admin = workflow_data["admin"]

    with pytest.raises(ReviewDecisionError, match="review note"):
        reject_submission("decoder", pending.id, reviewer=admin, note="  ")
    pending.refresh_from_db()
    assert pending.state == "pending_review"
    assert not pending.record_events.filter(action="rejected").exists()

    reject_submission("decoder", pending.id, reviewer=admin, note="Out of scope.")
    with pytest.raises(SubmissionStateError, match="waiting for review"):
        reject_submission("decoder", pending.id, reviewer=admin, note="Again.")

    pending.refresh_from_db()
    assert pending.state == "rejected"
    assert pending.published_at is None
    rejection = pending.record_events.get(action="rejected")
    assert rejection.caused_by.action == RecordEvent.Action.SUBMITTED
    assert rejection.caused_by.decoder_version_id == pending.id
    payload = submission_payload_for_record("decoder", pending)
    with pytest.raises(SubmissionStateError, match="pending submissions"):
        update_pending_submission(
            "decoder", pending.id, payload, actor=workflow_data["contributor"]
        )
    call_command("validate_histories", verbosity=0)

    client = Client()
    client.force_login(workflow_data["contributor"])
    profile = client.get(reverse("submissions:profile"))
    content = profile.content.decode()
    assert profile.status_code == 200
    assert "Rejected history" in content
    assert pending.name in content
    assert "Out of scope." in content
    assert "Edit" not in content.split(pending.name, 1)[1].split("</tr>", 1)[0]
    filtered = client.get(reverse("submissions:profile"), {"kind": "circuit"})
    assert pending.name not in filtered.content.decode()

    client.force_login(admin)
    review_queue = client.get(reverse("submissions:review")).content.decode()
    assert pending.name not in review_queue


def test_review_and_resubmit_permissions_are_enforced(workflow_data):
    pending = workflow_data["pending"]
    contributor = workflow_data["contributor"]
    unrelated = Account.objects.create_user(display_name="Unrelated reviewer")

    with pytest.raises(PermissionError, match="active admins"):
        request_changes(
            "decoder", pending.id, reviewer=contributor, note="Not authorised."
        )
    request_changes(
        "decoder",
        pending.id,
        reviewer=workflow_data["admin"],
        note="Please revise this candidate.",
    )
    with pytest.raises(PermissionError, match="uploader or an admin"):
        resubmit_for_review("decoder", pending.id, actor=unrelated)


def test_resubmit_snapshots_current_record_and_restores_original_queue(workflow_data):
    pending = workflow_data["pending"]
    request_changes(
        "decoder",
        pending.id,
        reviewer=workflow_data["admin"],
        note="Clarify preparation requirements.",
    )
    edited_payload = submission_payload_for_record("decoder", pending)
    edited_payload["description"] = "Clarified preparation requirements."
    update_pending_submission(
        "decoder",
        pending.id,
        edited_payload,
        actor=workflow_data["contributor"],
    )

    resubmitted = resubmit_for_review(
        "decoder", pending.id, actor=workflow_data["contributor"]
    )
    assert resubmitted.id == pending.id
    assert resubmitted.state == "pending_review"
    event = resubmitted.record_events.order_by("-sequence").first()
    assert event.action == "resubmitted"
    assert event.details == {
        "policy_version": "0.1",
        "previous_state": "changes_requested",
        "projected_state": "pending_review",
    }
    assert event.payload_snapshot["data"] == submission_payload_for_record(
        "decoder", resubmitted
    )
    assert event.caused_by.action == RecordEvent.Action.EDITED
    assert event.caused_by.decoder_version_id == pending.id

    with pytest.raises(SubmissionStateError, match="requested changes"):
        resubmit_for_review("decoder", pending.id, actor=workflow_data["contributor"])


def test_resubmit_returns_withdrawn_predecessor_successor_to_reapproval(
    workflow_data,
):
    contributor = workflow_data["contributor"]
    admin = workflow_data["admin"]
    source = create_submission(
        "machine",
        {
            "slug": "review-route-source-cpu",
            "machine_class": "cpu",
            "description": "Published source machine.",
            "status": "physical",
            "supersedes_machine": None,
        },
        submitter=contributor,
    ).record
    withdraw_submission(
        "machine", source.id, actor=contributor, note="Replacing this machine."
    )
    successor = create_successor_submission(
        "machine",
        source.id,
        {
            "slug": "review-route-successor-cpu",
            "machine_class": "cpu",
            "description": "Replacement machine.",
            "status": "physical",
            "supersedes_machine": str(source.id),
        },
        actor=contributor,
    ).record
    assert successor.state == "pending_reapproval"

    request_changes(
        "machine", successor.id, reviewer=admin, note="Add the processor model."
    )
    edited_payload = submission_payload_for_record("machine", successor)
    edited_payload["description"] = "Replacement machine with processor model."
    edited_payload["supersedes_machine"] = None
    update_pending_submission(
        "machine", successor.id, edited_payload, actor=contributor
    )
    successor.refresh_from_db()
    assert successor.predecessor_id == source.id
    assert successor.state == "changes_requested"

    resubmit_for_review("machine", successor.id, actor=contributor)
    successor.refresh_from_db()
    assert successor.state == "pending_reapproval"
    assert (
        successor.record_events.order_by("-sequence").first().details["projected_state"]
        == "pending_reapproval"
    )
    call_command("validate_histories", verbosity=0)


def test_admin_and_profile_rows_expose_actions_and_latest_note(workflow_data):
    pending = workflow_data["pending"]
    admin = workflow_data["admin"]
    contributor = workflow_data["contributor"]
    request_changes(
        "decoder", pending.id, reviewer=admin, note="Please expand the description."
    )

    owner_rows = collect_submission_rows(
        states=["changes_requested"], actor=contributor, owner=contributor
    )
    assert owner_rows[0]["latest_review"]["note"] == "Please expand the description."
    assert [action["label"] for action in owner_rows[0]["actions"]] == [
        "Edit",
        "Resubmit",
    ]

    client = Client()
    client.force_login(admin)
    forged_review_filter = client.get(
        reverse("submissions:review"), {"pending_state": "changes_requested"}
    )
    assert forged_review_filter.status_code == 200
    assert pending.name not in forged_review_filter.content.decode()

    resubmit_for_review("decoder", pending.id, actor=contributor)
    review_rows = collect_submission_rows(
        states=["pending_review"], actor=admin, admin=True
    )
    row = next(item for item in review_rows if item["id"] == pending.id)
    assert [action["label"] for action in row["review_actions"]] == [
        "Request changes",
        "Reject",
    ]


def test_review_forms_are_private_csrf_safe_and_show_latest_note(workflow_data):
    pending = workflow_data["pending"]
    contributor = workflow_data["contributor"]
    admin = workflow_data["admin"]
    request_url = reverse(
        "review-decisions:request-changes", args=["decoder", pending.id]
    )

    client = Client(enforce_csrf_checks=True)
    client.force_login(contributor)
    assert client.get(request_url).status_code == 403

    client.force_login(admin)
    page = client.get(request_url)
    assert page.status_code == 200
    assert b"Review note" in page.content
    assert client.post(request_url, {"note": "Missing token"}).status_code == 403
    token = client.cookies["csrftoken"].value
    response = client.post(
        request_url,
        {"note": "Document the stopping condition.", "csrfmiddlewaretoken": token},
    )
    assert response.status_code == 302

    client.force_login(contributor)
    record_page = client.get(
        reverse("submissions:record", args=["decoder", pending.id])
    )
    assert record_page.status_code == 200
    assert b"Latest review note" in record_page.content
    assert b"Document the stopping condition." in record_page.content
    assert b"Resubmit for review" in record_page.content


def test_history_validator_derives_review_decision_states(workflow_data):
    pending = workflow_data["pending"]
    request_changes(
        "decoder",
        pending.id,
        reviewer=workflow_data["admin"],
        note="Please revise this candidate.",
    )
    resubmit_for_review("decoder", pending.id, actor=workflow_data["contributor"])
    call_command("validate_histories", verbosity=0)


def test_uploader_notes_are_visible_only_to_the_exact_subject_uploader(workflow_data):
    source = workflow_data["pending"]
    source_owner = workflow_data["contributor"]
    other_owner = Account.objects.create_user(display_name="Other revision uploader")
    successor = DecoderVersion.objects.create(
        schema_release=source.schema_release,
        history=source.history,
        slug="mixed-uploader-successor",
        name=source.name,
        version="0.2",
        predecessor=source,
        description="A successor submitted by another account.",
        revision_description="Mixed-uploader visibility fixture.",
        circuit_skeleton_preparation=source.circuit_skeleton_preparation,
        circuit_priors_preparation=source.circuit_priors_preparation,
        provides_failure_probability=source.provides_failure_probability,
        submitted_by=other_owner,
        state="pending_review",
    )
    append_history_event(
        kind="decoder",
        record=successor,
        actor=other_owner,
        action=RecordEvent.Action.REVISION_CREATED,
        note="Created a mixed-uploader successor.",
        details={"predecessor_id": str(source.id)},
    )
    append_history_event(
        kind="decoder",
        record=successor,
        actor=other_owner,
        action=RecordEvent.Action.SUBMITTED,
        note="Submitted the successor.",
        details={"projected_state": "pending_review"},
        payload_snapshot=submission_snapshot(
            "decoder", {"record_id": str(successor.id)}
        ),
    )
    request_changes(
        "decoder",
        source.id,
        reviewer=workflow_data["admin"],
        note="Private note for the source uploader.",
    )
    request_changes(
        "decoder",
        successor.id,
        reviewer=workflow_data["admin"],
        note="Private note for the successor uploader.",
    )

    source_notes = {
        event.note for event in history_view("decoder", source, source_owner).events
    }
    assert "Private note for the source uploader." in source_notes
    assert "Private note for the successor uploader." not in source_notes

    successor_notes = {
        event.note for event in history_view("decoder", successor, other_owner).events
    }
    assert "Private note for the successor uploader." in successor_notes
    assert "Private note for the source uploader." not in successor_notes


def test_validator_rejects_cross_revision_and_stale_snapshot_causes(workflow_data):
    source = workflow_data["pending"]
    admin = workflow_data["admin"]
    contributor = workflow_data["contributor"]
    source_submission = source.record_events.get(action=RecordEvent.Action.SUBMITTED)
    request_changes(
        "decoder",
        source.id,
        reviewer=admin,
        note="Make a snapshot-bearing edit.",
    )
    payload = submission_payload_for_record("decoder", source)
    payload["description"] = "Edited after review."
    update_pending_submission("decoder", source.id, payload, actor=contributor)
    resubmit_for_review("decoder", source.id, actor=contributor)
    resubmission = source.record_events.get(action=RecordEvent.Action.RESUBMITTED)
    RecordEvent.objects.filter(id=resubmission.id).update(caused_by=source_submission)

    errors = BaseHistoryValidator().validate()
    assert any("does not cite the latest exact snapshot" in error for error in errors)

    other_owner = Account.objects.create_user(display_name="Cross-revision uploader")
    other = DecoderVersion.objects.create(
        schema_release=source.schema_release,
        history=source.history,
        slug="invalid-cross-revision-cause",
        name=source.name,
        version="0.3",
        description="Cross-revision cause fixture.",
        revision_description="Invalid cause fixture.",
        circuit_skeleton_preparation=source.circuit_skeleton_preparation,
        circuit_priors_preparation=source.circuit_priors_preparation,
        provides_failure_probability=source.provides_failure_probability,
        submitted_by=other_owner,
        state="pending_review",
    )
    append_history_event(
        kind="decoder",
        record=other,
        actor=other_owner,
        action=RecordEvent.Action.SUBMITTED,
        note="Submitted a second exact record.",
        details={"projected_state": "pending_review"},
        payload_snapshot=submission_snapshot("decoder", {"record_id": str(other.id)}),
    )
    decision = append_history_event(
        kind="decoder",
        record=other,
        actor=admin,
        action=RecordEvent.Action.REQUESTED_CHANGES,
        note="Invalid cross-revision cause.",
        details={
            "previous_state": "pending_review",
            "projected_state": "changes_requested",
        },
        caused_by=source_submission,
        visibility=RecordEvent.Visibility.UPLOADER,
    )
    other.state = "changes_requested"
    other.save(update_fields=["state"])

    errors = BaseHistoryValidator().validate()
    assert any(
        f"event {decision.id} has a cause for another exact record" in error
        for error in errors
    )

    source_approval = append_history_event(
        kind="decoder",
        record=source,
        actor=admin,
        action=RecordEvent.Action.APPROVED,
        note="Approval used as an invalid cross-revision publication cause.",
        caused_by=resubmission,
    )
    publication = append_history_event(
        kind="decoder",
        record=other,
        actor=admin,
        action=RecordEvent.Action.PUBLISHED,
        note="Invalid cross-revision publication.",
        caused_by=source_approval,
    )
    other.state = "published"
    other.published_at = publication.occurred_at
    other.save(update_fields=["state", "published_at"])

    errors = BaseHistoryValidator().validate()
    assert any(
        f"event {publication.id} has a cause for another exact record" in error
        for error in errors
    )


def test_validator_rejects_stale_transition_projection(workflow_data):
    pending = workflow_data["pending"]
    request_changes(
        "decoder",
        pending.id,
        reviewer=workflow_data["admin"],
        note="Review transition fixture.",
    )
    decision = pending.record_events.get(action=RecordEvent.Action.REQUESTED_CHANGES)
    decision.details = {
        **decision.details,
        "previous_state": "pending_reapproval",
    }
    decision.save(update_fields=["details"])

    errors = BaseHistoryValidator().validate()
    assert any(
        f"changes-request event {decision.id} has a stale previous state" in error
        for error in errors
    )
