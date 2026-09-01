import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id
from registry.demo_submissions import seed_submission_demo_data
from registry.models import DecoderVersion, ModerationEvent
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
    event = pending.moderation_events.get(action="requested_changes")
    assert event.note == "Please state the clustering radius."
    assert event.visibility == ModerationEvent.Visibility.UPLOADER
    assert event.details["previous_state"] == "pending_review"

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
    assert not pending.moderation_events.filter(action="rejected").exists()

    reject_submission("decoder", pending.id, reviewer=admin, note="Out of scope.")
    with pytest.raises(SubmissionStateError, match="waiting for review"):
        reject_submission("decoder", pending.id, reviewer=admin, note="Again.")

    pending.refresh_from_db()
    assert pending.state == "rejected"
    assert pending.published_at is None
    assert pending.moderation_events.filter(action="rejected").count() == 1
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

    resubmitted = resubmit_for_review(
        "decoder", pending.id, actor=workflow_data["contributor"]
    )
    assert resubmitted.id == pending.id
    assert resubmitted.state == "pending_review"
    event = resubmitted.moderation_events.order_by("-sequence").first()
    assert event.action == "resubmitted"
    assert event.details == {
        "policy_version": "0.1",
        "previous_state": "changes_requested",
        "projected_state": "pending_review",
    }
    assert event.payload_snapshot["data"] == submission_payload_for_record(
        "decoder", resubmitted
    )

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
    assert successor.supersedes_machine_id == source.id
    assert successor.state == "changes_requested"

    resubmit_for_review("machine", successor.id, actor=contributor)
    successor.refresh_from_db()
    assert successor.state == "pending_reapproval"
    assert (
        successor.moderation_events.order_by("-sequence")
        .first()
        .details["projected_state"]
        == "pending_reapproval"
    )


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
