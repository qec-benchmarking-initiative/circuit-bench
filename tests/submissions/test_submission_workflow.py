import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from pages.daily_quotes import quote_for_date
from pages.models import DailyQuoteSchedule
from registry.demo import DEMO_ACCOUNT_ID, demo_id
from registry.demo_submissions import (
    seed_submission_demo_data,
    submission_demo_counts,
)
from registry.models import (
    Artifact,
    CircuitRevision,
    Credit,
    DecoderVersion,
    Machine,
    RecordEvent,
    RecordHistory,
    Result,
    Tag,
)
from registry.services.artifacts import store_artifact_chunks
from registry.services.submissions import (
    SubmissionValidationError,
    create_submission,
    create_successor_submission,
    submission_payload_for_record,
    update_pending_submission,
)
from registry.submission_policy import SubmissionKind, approval_decision

pytestmark = pytest.mark.django_db


@pytest.fixture
def workflow_data(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    seed_submission_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
    }


def test_policy_explicitly_routes_machine_around_review(workflow_data):
    admin = workflow_data["admin"]
    contributor = workflow_data["contributor"]

    for account in (admin, contributor):
        assert approval_decision(SubmissionKind.DECODER, account).requires_review
        assert approval_decision(SubmissionKind.CIRCUIT, account).requires_review
        assert approval_decision(SubmissionKind.RESULT, account).requires_review
        machine = approval_decision(SubmissionKind.MACHINE, account)
        assert not machine.requires_review
        assert machine.initial_state == "published"
        machine_reapproval = approval_decision(
            SubmissionKind.MACHINE, account, reapproval=True
        )
        assert machine_reapproval.requires_review
        assert machine_reapproval.initial_state == "pending_reapproval"


def test_normal_create_ignores_a_forged_predecessor(workflow_data):
    predecessor = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    payload = submission_payload_for_record(SubmissionKind.DECODER, predecessor)
    payload.update(
        {
            "slug": "independent-decoder-root-0-1",
            "name": "Independent decoder root",
            "version": "0.1",
            "previous_version": str(predecessor.id),
            "description": "A distinct decoder lineage.",
            "revision_description": "First revision.",
        }
    )

    created = create_submission(
        SubmissionKind.DECODER,
        payload,
        submitter=workflow_data["contributor"],
    ).record

    assert created.predecessor is None
    assert created.history_id != predecessor.history_id


def test_only_uploader_or_admin_can_create_successor(workflow_data):
    predecessor = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    payload = submission_payload_for_record(SubmissionKind.DECODER, predecessor)
    payload.update(
        {
            "slug": "unauthorised-decoder-successor",
            "version": "0.3",
            "description": None,
            "revision_description": "An unauthorised revision attempt.",
        }
    )

    with pytest.raises(PermissionError, match="uploader or an admin"):
        create_successor_submission(
            SubmissionKind.DECODER,
            predecessor.id,
            payload,
            actor=workflow_data["contributor"],
        )


def test_pending_edit_preserves_root_lineage(workflow_data):
    pending = DecoderVersion.objects.get(
        id=demo_id("submission/decoder/window-cluster/0.1")
    )
    forged_predecessor = DecoderVersion.objects.get(
        id=demo_id("decoder/clear-matcher/0.2")
    )
    original_history_id = pending.history_id
    payload = submission_payload_for_record(SubmissionKind.DECODER, pending)
    payload["previous_version"] = str(forged_predecessor.id)
    payload["revision_description"] = "Edited without changing its lineage."

    updated = update_pending_submission(
        SubmissionKind.DECODER,
        pending.id,
        payload,
        actor=workflow_data["contributor"],
    )

    assert updated.predecessor is None
    assert updated.history_id == original_history_id


def test_private_file_from_another_account_is_rejected_by_submission_service(
    workflow_data,
):
    private_file, _created = store_artifact_chunks(
        [b'{"type":"object"}\n'],
        uploaded_by=workflow_data["admin"],
        media_type="application/schema+json",
        original_filename="private-schema.json",
    )
    predecessor = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    payload = submission_payload_for_record(SubmissionKind.DECODER, predecessor)
    payload.update(
        {
            "slug": "foreign-file-decoder-0-1",
            "name": "Foreign file decoder",
            "version": "0.1",
            "previous_version": None,
            "description": "A candidate with an inaccessible file UUID.",
            "revision_description": "First revision.",
            "hyperparameter_schema_artifact": str(private_file.id),
        }
    )

    with pytest.raises(SubmissionValidationError, match="registry rules"):
        create_submission(
            SubmissionKind.DECODER,
            payload,
            submitter=workflow_data["contributor"],
        )


def test_review_dashboard_is_admin_only_and_header_link_is_conditional(
    client, workflow_data
):
    review_url = reverse("submissions:review")
    assert client.get(review_url).status_code == 302

    client.force_login(workflow_data["contributor"])
    assert client.get(review_url).status_code == 403
    contributor_profile = client.get(reverse("submissions:profile")).content.decode()
    assert ">Admin</a>" not in contributor_profile

    client.force_login(workflow_data["admin"])
    response = client.get(review_url)
    assert response.status_code == 200
    content = response.content.decode()
    assert ">Admin</a>" in content
    assert "Window Cluster" in content
    assert "Rotated surface-code memory d=7" in content
    assert "Synthetic pending independent reproduction" not in content
    assert "Clear Matcher 0.2 on Rotated surface-code memory d=5" in content


def test_admin_can_rotate_daily_quote_and_see_schedule_window(client, workflow_data):
    admin = workflow_data["admin"]
    schedule = DailyQuoteSchedule.objects.get(pk=1)
    client.force_login(admin)

    response = client.get(reverse("submissions:review"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Daily quotation" in content
    assert "Offset integer" in content
    assert ">+0</output>" in content
    assert content.count("Use this quote") == 8
    assert "-3 days" in content
    assert "+5 days" in content

    response = client.post(
        reverse("submissions:rotate-daily-quote"),
        {"delta": "1"},
    )
    schedule.refresh_from_db()
    assert response.status_code == 302
    assert response.url == f"{reverse('submissions:review')}#daily-quote-schedule"
    assert schedule.day_offset == 1
    assert schedule.updated_by == admin

    home = client.get(reverse("pages:home"))
    assert home.context["daily_quote"] == quote_for_date(timezone.localdate(), 1)


def test_daily_quote_rotation_rejects_non_admin_and_invalid_delta(
    client, workflow_data
):
    rotate_url = reverse("submissions:rotate-daily-quote")
    client.force_login(workflow_data["contributor"])
    assert client.post(rotate_url, {"delta": "1"}).status_code == 403

    client.force_login(workflow_data["admin"])
    assert client.post(rotate_url, {"delta": "6"}).status_code == 400
    assert client.post(rotate_url, {"delta": "nonsense"}).status_code == 400


def test_pending_record_has_private_exact_view_for_owner_and_admin(
    client, workflow_data
):
    pending = DecoderVersion.objects.get(
        id=demo_id("submission/decoder/window-cluster/0.1")
    )
    url = reverse("submissions:record", args=["decoder", pending.id])

    client.force_login(workflow_data["contributor"])
    owner_response = client.get(url)
    assert owner_response.status_code == 200
    assert b"Exact decoder version submission" in owner_response.content
    assert b"Algorithm tags" in owner_response.content
    history_tag = (
        owner_response.content.decode()
        .split('<details class="submission-history"', 1)[1]
        .split(">", 1)[0]
    )
    assert " open" not in history_tag

    unrelated = Account.objects.create_user(display_name="Unrelated scientist")
    client.force_login(unrelated)
    assert client.get(url).status_code == 403

    client.force_login(workflow_data["admin"])
    admin_response = client.get(url)
    assert admin_response.status_code == 200
    assert b"Approve and publish" in admin_response.content


def test_structured_decoder_preview_back_and_commit_create_pending_record(
    client, workflow_data
):
    contributor = workflow_data["contributor"]
    client.force_login(contributor)
    tag = Tag.objects.get(id=demo_id("tag/algorithm/matching"))
    before = DecoderVersion.objects.count()

    response = client.post(
        reverse("submissions:create", args=["decoder"]),
        {
            "mode": "structured",
            "slug": "previewed-decoder-0-1",
            "name": "Previewed Decoder",
            "version": "0.1",
            "previous_version": "",
            "description": "A decoder entered through the structured form.",
            "revision_description": "First submitted version.",
            "circuit_skeleton_preparation": "not_required",
            "circuit_priors_preparation": "required",
            "provides_failure_probability": "on",
            "hyperparameter_definitions": "window: integer",
            "hyperparameter_schema_artifact": "",
            "algorithm_tags": [str(tag.id)],
        },
    )

    assert response.status_code == 302
    assert "/submit/preview/" in response.url
    assert DecoderVersion.objects.count() == before
    preview = client.get(response.url)
    assert preview.status_code == 200
    assert b"Previewed Decoder" in preview.content
    assert b"Back and edit" in preview.content
    assert b"submission-preview-sections" in preview.content
    assert b"submission-preview-list" not in preview.content

    committed = client.post(response.url + "submit/")
    assert committed.status_code == 302
    record = DecoderVersion.objects.get(slug="previewed-decoder-0-1")
    assert record.state == "pending_review"
    assert record.published_at is None
    assert record.submitted_by == contributor
    assert Credit.objects.get(decoder_version=record).account == contributor
    assert RecordEvent.objects.filter(
        decoder_version=record, action="submitted"
    ).exists()


def test_submission_forms_use_vertical_sections_and_shared_choosers(
    client, workflow_data
):
    client.force_login(workflow_data["admin"])

    content = client.get(
        reverse("submissions:create", args=["circuit"])
    ).content.decode()

    assert 'class="submission-form-sections"' in content
    assert 'class="submission-field-group submission-field-group-inline"' in content
    assert 'data-search-url="/pickers/submission-noise-models/"' in content
    assert 'data-search-url="/pickers/artifacts/"' not in content
    assert content.count("data-submission-file-upload") == 3
    assert "Sampling circuit file" in content
    assert "Detector error model file" in content
    assert "Manifest file" in content
    assert content.count('data-mode="submission"') == 2
    assert "Use selected tags" in content
    assert "submission-field-grid" not in content
    assert 'name="dem_approximate_disjoint_errors"' in content
    approximate_input = content.split('name="dem_approximate_disjoint_errors"', 1)[
        0
    ].rsplit("<input", 1)[1]
    assert 'type="checkbox"' in approximate_input
    assert "Arguments passed to Stim to compile the detector error model." in content
    assert (
        content.count("/definitions/circuit/0.1/#css-and-detector-basis-classification")
        == 3
    )
    assert "Approval process v0.1" in content
    assert "All circuit submissions are subject to admin review." in content
    assert "Describe one frozen circuit" not in content

    result_content = client.get(
        reverse("submissions:create", args=["result"])
    ).content.decode()
    assert 'name="reproduction_status"' not in result_content


def test_machine_submission_explains_automatic_publication(client, workflow_data):
    client.force_login(workflow_data["contributor"])

    content = client.get(
        reverse("submissions:create", args=["machine"])
    ).content.decode()

    assert "Approval process v0.1" in content
    assert "Machine submissions are validated and published immediately." in content
    assert "Publication is attributed to System." in content


def test_successor_form_prefills_and_locks_exact_predecessor(client, workflow_data):
    predecessor = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    client.force_login(workflow_data["admin"])

    content = client.get(
        reverse("submissions:successor", args=["decoder", predecessor.id])
    ).content.decode()

    assert f'name="previous_version" value="{predecessor.id}"' in content
    assert "Fixed by the immutable predecessor relationship." in content
    assert 'data-search-url="/pickers/decoder-versions/"' in content
    assert (
        "disabled" in content.split("Previous version", 1)[1].split("</button>", 1)[0]
    )
    version_input = content.split('name="version"', 1)[1].split(">", 1)[0]
    assert "value=" not in version_input
    revision_field = content.split('name="revision_description"', 1)[1]
    assert revision_field.split("</textarea>", 1)[0].strip().endswith(">")
    assert "Submit alongside existing published revisions" in content
    assert f"Withdraw {predecessor.name} {predecessor.version} and submit" in content


def test_circuit_successor_requires_fresh_file_uploads(client, workflow_data):
    predecessor = CircuitRevision.objects.get(id=demo_id("circuit/rotated-memory-d5"))
    client.force_login(workflow_data["contributor"])

    content = client.get(
        reverse("submissions:successor", args=["circuit", predecessor.id])
    ).content.decode()

    assert "Current file:" not in content
    assert content.count("data-submission-file-upload") == 3
    assert content.count('type="file"') == 3


def test_decoder_schema_can_only_be_reused_through_previous_revision_control(
    client, workflow_data
):
    predecessor = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    schema_file = Artifact.objects.order_by("created_at").first()
    predecessor.hyperparameter_schema_artifact = schema_file
    predecessor.save(update_fields=["hyperparameter_schema_artifact"])
    client.force_login(workflow_data["admin"])

    first_version = client.get(
        reverse("submissions:create", args=["decoder"])
    ).content.decode()
    first_control = first_version.split("data-use-previous-schema", 1)[1].split(">", 1)[
        0
    ]
    assert "disabled" in first_control
    assert "Choose a previous decoder revision first." in first_version
    assert 'data-search-url="/pickers/artifacts/"' not in first_version
    assert "Upload a new JSON Schema file" in first_version

    successor = client.get(
        reverse("submissions:successor", args=["decoder", predecessor.id])
    ).content.decode()
    successor_control = successor.split("data-use-previous-schema", 1)[1].split(">", 1)[
        0
    ]
    assert "disabled" not in successor_control
    assert f'data-schema-id="{schema_file.id}"' in successor
    assert f"Available: {schema_file.original_filename}." in successor


def test_structured_upload_is_frozen_and_snapshotted_before_preview(
    client, workflow_data
):
    contributor = workflow_data["contributor"]
    tag = Tag.objects.get(id=demo_id("tag/algorithm/matching"))
    payload_bytes = b'{"type":"object","properties":{"window":{"type":"integer"}}}'
    upload = SimpleUploadedFile(
        "hyperparameters.schema.json",
        payload_bytes,
        content_type="application/schema+json",
    )
    client.force_login(contributor)

    response = client.post(
        reverse("submissions:create", args=["decoder"]),
        {
            "mode": "structured",
            "slug": "uploaded-schema-decoder-0-1",
            "name": "Uploaded-schema decoder",
            "version": "0.1",
            "previous_version": "",
            "description": "Tests immutable submission uploads.",
            "revision_description": "First submitted version.",
            "circuit_skeleton_preparation": "not_required",
            "circuit_priors_preparation": "not_required",
            "provides_failure_probability": "on",
            "hyperparameter_definitions": "window: positive integer",
            "hyperparameter_schema_artifact": "",
            "algorithm_tags": [str(tag.id)],
            "upload__hyperparameter_schema_artifact": upload,
        },
    )

    assert response.status_code == 302
    artifact = Artifact.objects.get(original_filename="hyperparameters.schema.json")
    assert artifact.byte_size == len(payload_bytes)
    committed = client.post(response.url + "submit/")
    assert committed.status_code == 302
    record = DecoderVersion.objects.get(slug="uploaded-schema-decoder-0-1")
    assert record.hyperparameter_schema_artifact == artifact
    snapshot = record.record_events.get(action="submitted").payload_snapshot
    assert snapshot["data"]["hyperparameter_schema_artifact"] == str(artifact.id)
    assert snapshot["artifacts"][str(artifact.id)]["sha256"] == artifact.sha256


def test_demo_history_invariants_pass_validator(workflow_data):
    call_command("validate_histories", verbosity=0)


def test_admin_submission_still_enters_review(client, workflow_data):
    client.force_login(workflow_data["admin"])
    payload = {
        "slug": "admin-submitted-machine-comparison-decoder",
        "name": "Admin-submitted decoder",
        "version": "0.1",
        "previous_version": None,
        "description": "An admin does not bypass review.",
        "revision_description": "First submitted version.",
        "circuit_skeleton_preparation": "required",
        "circuit_priors_preparation": "required",
        "provides_failure_probability": True,
        "hyperparameter_definitions": None,
        "hyperparameter_schema_artifact": None,
        "algorithm_tags": [],
    }
    preview = client.post(
        reverse("submissions:create", args=["decoder"]),
        {"mode": "json", "payload": json.dumps(payload)},
    )
    assert preview.status_code == 302
    client.post(preview.url + "submit/")

    record = DecoderVersion.objects.get(slug=payload["slug"])
    assert record.submitted_by.is_admin
    assert record.state == "pending_review"


def test_json_machine_submission_publishes_immediately(client, workflow_data):
    contributor = workflow_data["contributor"]
    client.force_login(contributor)
    payload = {
        "slug": "local-test-cpu",
        "machine_class": "cpu",
        "description": "A machine submitted through JSON.",
        "status": "physical",
        "supersedes_machine": None,
    }
    preview = client.post(
        reverse("submissions:create", args=["machine"]),
        {"mode": "json", "payload": json.dumps(payload)},
    )
    assert preview.status_code == 302
    committed = client.post(preview.url + "submit/")

    machine = Machine.objects.get(slug="local-test-cpu")
    assert machine.state == "published"
    assert machine.published_at is not None
    assert committed.status_code == 302
    assert committed.url == reverse("machines:detail", args=[machine.slug])
    assert [event.action for event in machine.record_events.order_by("sequence")] == [
        "submitted",
        "approved",
        "published",
    ]
    approval = machine.record_events.get(action="approved")
    assert approval.actor_type == "system"
    assert approval.actor_system == "submission_policy"
    assert approval.actor_account is None


def test_json_result_rejects_unpublished_references(client, workflow_data):
    client.force_login(workflow_data["contributor"])
    pending_decoder = DecoderVersion.objects.get(
        id=demo_id("submission/decoder/window-cluster/0.1")
    )
    base_result = Result.objects.get(id=demo_id("result/clear-matcher-rotated-memory"))
    score = base_result.scores.order_by("score_definition_id").first()
    payload = {
        "decoder_version": str(pending_decoder.id),
        "circuit_revision": str(base_result.circuit_revision_id),
        "evaluator_version": str(base_result.evaluator_version_id),
        "machine": str(base_result.machine_id),
        "description": None,
        "hyperparameter_values": None,
        "hyperparameter_values_artifact": None,
        "shots_total": 10,
        "successful_shots": 9,
        "logical_failure_shots": 1,
        "timeout_shots": 0,
        "decoder_error_shots": 0,
        "failure_probability_shots": 10,
        "latency_shots": 10,
        "preparation_duration_seconds": None,
        "training_workload_description": None,
        "software_environment": None,
        "t_1000_ns": None,
        "supersedes_result": None,
        "scores": [
            {"score_definition": str(score.score_definition_id), "value": "0.1"}
        ],
    }

    response = client.post(
        reverse("submissions:create", args=["result"]),
        {"mode": "json", "payload": json.dumps(payload)},
    )

    assert response.status_code == 200
    assert b"Select a valid choice" in response.content
    assert not Result.objects.filter(description__isnull=True, shots_total=10).exists()


def test_result_json_rejects_forged_server_derived_reproduction_status(
    client, workflow_data
):
    client.force_login(workflow_data["contributor"])
    base_result = Result.objects.get(id=demo_id("result/clear-matcher-rotated-memory"))
    payload = submission_payload_for_record(SubmissionKind.RESULT, base_result)
    payload["description"] = "A forged provenance claim."
    payload["supersedes_result"] = None
    payload["reproduction_status"] = "decoder_author_verified"

    response = client.post(
        reverse("submissions:create", args=["result"]),
        {"mode": "json", "payload": json.dumps(payload)},
    )

    assert response.status_code == 200
    assert b"reproduction_status" in response.content
    assert b"not allowed" in response.content
    assert not Result.objects.filter(description="A forged provenance claim.").exists()


def test_admin_approval_publishes_after_revalidating_references(client, workflow_data):
    admin = workflow_data["admin"]
    contributor = workflow_data["contributor"]
    pending = Result.objects.get(
        id=demo_id("submission/result/independent-reproduction")
    )
    approve_url = reverse(
        "submissions:approve", args=[SubmissionKind.RESULT.value, pending.id]
    )

    client.force_login(contributor)
    assert client.post(approve_url).status_code == 403

    client.force_login(admin)
    response = client.post(approve_url)
    pending.refresh_from_db()
    assert response.status_code == 302
    assert pending.state == "published"
    assert pending.published_at is not None
    assert list(
        pending.record_events.order_by("sequence").values_list("action", flat=True)
    ) == ["submitted", "approved", "published"]


def test_approval_refuses_result_if_reference_changed_since_submission(
    client, workflow_data
):
    admin = workflow_data["admin"]
    pending = Result.objects.get(
        id=demo_id("submission/result/independent-reproduction")
    )
    DecoderVersion.objects.filter(id=pending.decoder_version_id).update(
        state="draft", published_at=None
    )
    client.force_login(admin)

    response = client.post(
        reverse("submissions:approve", args=["result", pending.id]), follow=True
    )

    pending.refresh_from_db()
    assert pending.state == "pending_review"
    assert b"referenced decoder version is not published" in response.content


def test_profile_groups_pending_items_and_keeps_accounts_separate(
    client, workflow_data
):
    client.force_login(workflow_data["contributor"])
    contributor_page = client.get(reverse("submissions:profile")).content.decode()
    assert "Window Cluster" in contributor_page
    assert "Clear Matcher 0.2 on Rotated surface-code memory d=5" in contributor_page
    assert "Rotated surface-code memory d=7" not in contributor_page
    assert "demo-simulated-gpu" in contributor_page

    client.force_login(workflow_data["admin"])
    admin_page = client.get(reverse("submissions:profile")).content.decode()
    assert "Rotated surface-code memory d=7" in admin_page
    assert "Window Cluster" not in admin_page


def test_schema_endpoint_and_demo_seed_are_stable(client, workflow_data):
    response = client.get(reverse("submissions:schema", args=["result"]))
    assert response.status_code == 200
    schema = response.json()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert "machine" in schema["required"]
    assert "reproduction_status" not in schema["properties"]
    assert "reproduction_status" not in schema["required"]

    first = submission_demo_counts()
    second = seed_submission_demo_data()
    assert (
        first
        == second
        == {
            "pending_decoders": 1,
            "pending_circuits": 1,
            "pending_results": 1,
            "published_machines": 1,
            "pending_noise_models": 1,
            "pending_benchmarks": 1,
            "pending_benchmark_attempts": 1,
            "pending_credit_claims": 1,
        }
    )


def test_development_login_exposes_only_the_two_mock_accounts(
    client, workflow_data, settings
):
    settings.DEBUG = True
    login_page = client.get(reverse("account_login"), {"next": "/review/"})
    assert b"Continue as Ada Decoder (admin)" in login_page.content
    assert b"Continue as Casey Circuit" in login_page.content

    response = client.post(
        reverse("account-development-login", args=[workflow_data["admin"].id]),
        {"next": "/review/"},
    )
    assert response.status_code == 302
    assert response.url == "/review/"


def test_pending_candidate_edit_uses_preview_and_keeps_exact_uuid(
    client, workflow_data
):
    contributor = workflow_data["contributor"]
    pending = DecoderVersion.objects.get(
        id=demo_id("submission/decoder/window-cluster/0.1")
    )
    original_id = pending.id
    payload = submission_payload_for_record(SubmissionKind.DECODER, pending)
    payload["description"] = "Edited while awaiting review."
    client.force_login(contributor)

    preview = client.post(
        reverse("submissions:edit", args=["decoder", pending.id]),
        {"mode": "json", "payload": json.dumps(payload)},
    )
    assert preview.status_code == 302
    committed = client.post(preview.url + "submit/")

    pending.refresh_from_db()
    assert committed.status_code == 302
    assert pending.id == original_id
    assert pending.description == "Edited while awaiting review."
    assert pending.state == "pending_review"
    assert pending.record_events.filter(action="edited").exists()


def test_withdrawn_machine_can_be_revised_into_pending_reapproval(
    client, workflow_data
):
    contributor = workflow_data["contributor"]
    admin = workflow_data["admin"]
    machine = Machine.objects.get(id=demo_id("submission/machine/simulated-gpu"))
    client.force_login(contributor)

    confirmation = client.get(
        reverse("submissions:withdraw", args=["machine", machine.id])
    )
    assert confirmation.status_code == 200
    assert b"Confirm withdrawal" in confirmation.content
    withdrawn = client.post(
        reverse("submissions:withdraw", args=["machine", machine.id]),
        {"note": "Superseded hardware description."},
    )
    machine.refresh_from_db()
    assert withdrawn.status_code == 302
    assert machine.state == "withdrawn"
    assert machine.withdrawn_at is not None

    payload = submission_payload_for_record(SubmissionKind.MACHINE, machine)
    payload["slug"] = "demo-simulated-gpu-revision"
    successor_preview = client.post(
        reverse("submissions:successor", args=["machine", machine.id]),
        {"mode": "json", "payload": json.dumps(payload)},
    )
    assert successor_preview.status_code == 302
    client.post(successor_preview.url + "submit/")

    successor = Machine.objects.get(slug="demo-simulated-gpu-revision")
    assert successor.predecessor == machine
    assert successor.state == "pending_reapproval"
    assert successor.published_at is None
    assert successor.record_events.filter(action="resubmitted").exists()

    client.force_login(admin)
    approved = client.post(
        reverse("submissions:approve", args=["machine", successor.id])
    )
    successor.refresh_from_db()
    assert approved.status_code == 302
    assert successor.state == "published"
    assert successor.record_events.get(action="approved").actor_account == admin


def test_editing_published_record_creates_successor_without_mutating_predecessor(
    client, workflow_data
):
    admin = workflow_data["admin"]
    predecessor = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    original_description = predecessor.description
    payload = submission_payload_for_record(SubmissionKind.DECODER, predecessor)
    payload.update(
        {
            "slug": "clear-matcher-0-3-candidate",
            "version": "0.3",
            "description": "Candidate successor description.",
            "revision_description": "Creates a new immutable successor.",
        }
    )
    client.force_login(admin)

    preview = client.post(
        reverse("submissions:successor", args=["decoder", predecessor.id]),
        {"mode": "json", "payload": json.dumps(payload)},
    )
    assert preview.status_code == 302
    client.post(preview.url + "submit/")

    predecessor.refresh_from_db()
    successor = DecoderVersion.objects.get(slug="clear-matcher-0-3-candidate")
    assert predecessor.state == "published"
    assert predecessor.description == original_description
    assert successor.predecessor == predecessor
    assert successor.state == "pending_review"


def test_replacement_revision_withdraws_source_and_enters_reapproval(
    client, workflow_data
):
    contributor = workflow_data["contributor"]
    predecessor = CircuitRevision.objects.get(id=demo_id("circuit/rotated-memory-d5"))
    payload = submission_payload_for_record(SubmissionKind.CIRCUIT, predecessor)
    payload.update(
        {
            "slug": "rotated-memory-d5-replacement",
            "name": "Rotated surface-code memory d=5 replacement",
            "revision_description": "Replacement candidate.",
        }
    )
    client.force_login(contributor)

    preview = client.post(
        reverse("submissions:successor", args=["circuit", predecessor.id]),
        {
            "mode": "json",
            "revision_mode": "replace",
            "payload": json.dumps(payload),
        },
    )
    assert preview.status_code == 302
    preview_content = client.get(preview.url).content.decode()
    assert (
        "will be withdrawn and this successor will enter pending reapproval"
        in preview_content
    )

    committed = client.post(preview.url + "submit/")
    predecessor.refresh_from_db()
    successor = CircuitRevision.objects.get(slug=payload["slug"])

    assert committed.status_code == 302
    assert predecessor.state == "withdrawn"
    assert successor.predecessor == predecessor
    assert successor.state == "pending_reapproval"
    assert predecessor.record_events.filter(action="withdrawn").exists()


def test_profile_has_unified_pending_published_only_sections_and_row_actions(
    client, workflow_data
):
    client.force_login(workflow_data["contributor"])
    response = client.get(reverse("submissions:profile"))
    content = response.content.decode()

    assert "Pending items" in content
    assert "Window Cluster" in content
    assert "Clear Matcher 0.2 on Rotated surface-code memory d=5" in content
    assert "Published machines" in content
    assert "demo-simulated-gpu" in content
    assert "Edit / new revision" in content
    assert "Withdraw…" in content
    assert 'class="table-action"' in content
    assert 'class="table-action table-action-danger"' in content
    for table in content.split('<table class="data-table submission-table"')[1:]:
        assert 'class="button button-compact' not in table.split("</table>", 1)[0]
    assert ">System<" in content
    assert "Your submitted records and their current publication states" not in content
    assert "Submission, revision, and withdrawal policy" in content
    assert "<title>Profile: Casey Circuit · Circuit Bench</title>" in content
    assert 'href="/profile/">Profile: Casey Circuit</a>' in content
    assert ">Submit data</a>" in content
    assert 'href="/accounts/">Settings</a>' in content
    assert "Manage sign-in identities" not in content

    filtered = client.get(
        reverse("submissions:profile"),
        {"q": "Window Cluster", "kind": "decoder", "sort": "record"},
    ).content.decode()
    assert "Window Cluster" in filtered
    assert "demo-simulated-gpu" not in filtered


def test_profile_pending_queue_is_paginated(client, workflow_data):
    contributor = workflow_data["contributor"]
    prototype = DecoderVersion.objects.get(
        id=demo_id("submission/decoder/window-cluster/0.1")
    )
    histories = RecordHistory.objects.bulk_create(
        [RecordHistory(record_kind="decoder") for _index in range(25)]
    )
    DecoderVersion.objects.bulk_create(
        [
            DecoderVersion(
                schema_release=prototype.schema_release,
                slug=f"pending-pagination-{index:02d}",
                name=f"Pending pagination {index:02d}",
                version="0.1",
                description="Pagination fixture.",
                revision_description="First candidate.",
                circuit_skeleton_preparation="required",
                circuit_priors_preparation="required",
                provides_failure_probability=True,
                submitted_by=contributor,
                state="pending_review",
                history=histories[index],
            )
            for index in range(25)
        ]
    )
    client.force_login(contributor)

    first = client.get(reverse("submissions:profile")).content.decode()
    second = client.get(
        reverse("submissions:profile"), {"pending_page": 2}
    ).content.decode()
    assert "Page 1 of 2" in first
    assert "Page 2 of 2" in second


def test_admin_page_is_work_queue_plus_last_seven_days_withdrawals(
    client, workflow_data
):
    contributor = workflow_data["contributor"]
    admin = workflow_data["admin"]
    recent = Machine.objects.get(id=demo_id("submission/machine/simulated-gpu"))
    recent.state = "withdrawn"
    recent.withdrawn_at = timezone.now()
    recent.save(update_fields=["state", "withdrawn_at"])
    old = Machine.objects.filter(state="published").exclude(id=recent.id).first()
    old.state = "withdrawn"
    old.withdrawn_at = timezone.now() - timedelta(days=8)
    old.save(update_fields=["state", "withdrawn_at"])
    client.force_login(admin)

    content = client.get(reverse("submissions:review")).content.decode()
    assert "Waiting for review" in content
    assert "Recently withdrawn" in content
    assert "Window Cluster" in content
    assert recent.slug in content
    assert old.slug not in content
    assert "All submitted decoder versions" not in content
    assert "Streaming Cluster" not in content
    assert contributor.display_name in content


def test_approve_form_works_with_enforced_csrf(workflow_data):
    csrf_client = Client(enforce_csrf_checks=True)
    admin = workflow_data["admin"]
    pending = DecoderVersion.objects.get(
        id=demo_id("submission/decoder/window-cluster/0.1")
    )
    csrf_client.force_login(admin)
    page = csrf_client.get(reverse("submissions:review"))
    assert page.status_code == 200
    assert b'name="csrfmiddlewaretoken"' in page.content
    token = csrf_client.cookies["csrftoken"].value

    response = csrf_client.post(
        reverse("submissions:approve", args=["decoder", pending.id]),
        {"csrfmiddlewaretoken": token},
    )
    pending.refresh_from_db()
    assert response.status_code == 302
    assert pending.state == "published"
    assert pending.record_events.get(action="approved").actor_account == admin


def test_submission_policy_is_rendered_and_listed_with_static_pages(client):
    policy_url = reverse("pages:static-reference", args=["submission-policy"])
    policy = client.get(policy_url)
    assert policy.status_code == 200
    assert b"Submission, revision, and withdrawal policy 0.1" in policy.content
    assert b"pending_reapproval" in policy.content
    assert policy_url.encode() in client.get(reverse("pages:home")).content
    assert policy_url.encode() in client.get(reverse("pages:about")).content
