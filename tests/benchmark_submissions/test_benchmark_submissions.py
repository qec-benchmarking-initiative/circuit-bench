import json
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.forms_benchmark_submissions import (
    BenchmarkAttemptResultsForm,
    BenchmarkAttemptSelectionForm,
    BenchmarkRevisionSubmissionForm,
)
from registry.models import (
    BenchmarkAttempt,
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    ModerationEvent,
    RecordHistory,
    Result,
)
from registry.services.artifacts import local_artifact_path, store_artifact_chunks
from registry.services.benchmark_submissions import (
    BenchmarkPermissionError,
    BenchmarkStateError,
    BenchmarkValidationError,
    approve_benchmark_attempt,
    approve_benchmark_submission,
    canonical_benchmark_payload,
    create_benchmark_attempt,
    create_benchmark_submission,
    promote_benchmark_official,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def benchmark_submission_urls(settings):
    settings.ROOT_URLCONF = "tests.benchmark_submissions.urls"


@pytest.fixture
def benchmark_data(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    seed_demo_data()
    return {
        "admin": Account.objects.get(id=DEMO_ACCOUNT_ID),
        "contributor": Account.objects.get(id=demo_id("account/contributor")),
        "circuit": CircuitRevision.objects.get(id=demo_id("circuit/rotated-memory-d5")),
        "decoder": DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2")),
        "other_decoder": DecoderVersion.objects.get(
            id=demo_id("decoder/clear-matcher/0.1")
        ),
        "result": Result.objects.get(id=demo_id("result/clear-matcher-rotated-memory")),
        "benchmark": BenchmarkRevision.objects.get(
            id=demo_id("benchmark/memory-smoke-test/0.1")
        ),
    }


def _payload(data, slug="community-memory-0-1", **overrides):
    payload = {
        "slug": slug,
        "name": "Community memory benchmark",
        "version": "0.1",
        "previous_revision": None,
        "description": "A compact benchmark submitted by the community.",
        "revision_description": "First exact revision.",
        "items": [
            {
                "circuit_revision": str(data["circuit"].id),
                "required": True,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _create_pending(data, slug="community-memory-0-1", **overrides):
    return create_benchmark_submission(
        _payload(data, slug=slug, **overrides),
        submitter=data["contributor"],
    ).benchmark


def _create_published(data, slug="community-memory-0-1", **overrides):
    benchmark = _create_pending(data, slug=slug, **overrides)
    return approve_benchmark_submission(benchmark.id, reviewer=data["admin"])


def _clone_record(record, **overrides):
    excluded = {"id", "created_at", "published_at", "withdrawn_at"}
    values = {
        field.name: getattr(record, field.name)
        for field in record._meta.fields
        if field.name not in excluded
    }
    values.update(overrides)
    return type(record).objects.create(**values)


def _second_circuit(data, *, slug="optional-memory-d7"):
    return _clone_record(
        data["circuit"],
        history=RecordHistory.objects.create(record_kind="circuit"),
        slug=slug,
        name="Optional memory circuit d=7",
        previous_revision=None,
        state="published",
        published_at=timezone.now(),
    )


def _result_for(data, circuit, *, decoder=None, state="published"):
    return _clone_record(
        data["result"],
        history=RecordHistory.objects.create(record_kind="result"),
        decoder_version=decoder or data["decoder"],
        circuit_revision=circuit,
        supersedes_result=None,
        state=state,
        published_at=timezone.now() if state == "published" else None,
    )


def _items(*rows):
    return [
        {"circuit_revision": str(circuit.id), "required": required}
        for circuit, required in rows
    ]


def _attempt_mapping(benchmark, *results):
    return {
        str(item.circuit_revision_id): str(result.id) if result else None
        for item, result in zip(
            benchmark.items.order_by("position"), results, strict=True
        )
    }


def test_structured_form_produces_the_canonical_payload(benchmark_data):
    payload = _payload(benchmark_data)
    form = BenchmarkRevisionSubmissionForm(
        {
            "slug": payload["slug"],
            "name": payload["name"],
            "version": payload["version"],
            "previous_revision": "",
            "description": payload["description"],
            "revision_description": payload["revision_description"],
            "items_json": json.dumps(payload["items"]),
        }
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["payload"] == canonical_benchmark_payload(payload)


@pytest.mark.parametrize("mode", ["structured", "json"])
def test_structured_and_json_entry_preview_then_commit(client, benchmark_data, mode):
    client.force_login(benchmark_data["contributor"])
    slug = f"{mode}-preview-0-1"
    payload = _payload(benchmark_data, slug=slug, name=f"{mode.title()} preview")
    post_data = (
        {
            "mode": "structured",
            "slug": payload["slug"],
            "name": payload["name"],
            "version": payload["version"],
            "previous_revision": "",
            "description": payload["description"],
            "revision_description": payload["revision_description"],
            "items_json": json.dumps(payload["items"]),
        }
        if mode == "structured"
        else {"mode": "json", "payload": json.dumps(payload)}
    )

    response = client.post(reverse("benchmark-submissions:create"), post_data)

    assert response.status_code == 302
    assert "/submit/benchmark/preview/" in response.url
    assert not BenchmarkRevision.objects.filter(slug=slug).exists()
    preview = client.get(response.url)
    assert preview.status_code == 200
    assert payload["name"].encode() in preview.content
    assert benchmark_data["circuit"].name.encode() in preview.content

    committed = client.post(
        reverse(
            "benchmark-submissions:commit",
            args=[response.url.rstrip("/").split("/")[-1]],
        )
    )

    record = BenchmarkRevision.objects.get(slug=slug)
    assert committed.status_code == 302
    assert committed.url == reverse("benchmark-submissions:candidate", args=[record.id])
    assert record.state == "pending_review"
    assert record.published_at is None
    assert record.submitted_by == benchmark_data["contributor"]
    assert record.recognition_status == "community_submitted"
    assert record.moderation_events.get(action="submitted").payload_snapshot["data"][
        "manifest_artifact"
    ] == str(record.manifest_artifact_id)


def test_submission_generates_an_immutable_canonical_manifest(benchmark_data):
    payload = _payload(
        benchmark_data,
        slug="canonical-manifest-0-1",
        items=[
            {
                "circuit_revision": str(benchmark_data["circuit"].id),
                "required": True,
            }
        ],
    )

    outcome = create_benchmark_submission(
        payload, submitter=benchmark_data["contributor"]
    )

    file = outcome.benchmark.manifest_artifact
    expected = {
        "schema": "circuit-bench/benchmark-manifest/0.1",
        "benchmark": {"slug": payload["slug"], "version": "0.1"},
        "items": [
            {
                "position": 1,
                "circuit_revision": str(benchmark_data["circuit"].id),
                "required": True,
            }
        ],
    }
    expected_bytes = (
        json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    assert outcome.manifest_created is True
    assert file.original_filename == "canonical-manifest-0-1-manifest.json"
    assert file.media_type == "application/json"
    assert file.uploaded_by == benchmark_data["contributor"]
    assert local_artifact_path(file).read_bytes() == expected_bytes


def test_approval_publishes_as_admin_approved_with_causal_history(benchmark_data):
    benchmark = _create_pending(benchmark_data, slug="approval-history-0-1")

    approved = approve_benchmark_submission(
        benchmark.id, reviewer=benchmark_data["admin"]
    )

    events = list(approved.moderation_events.order_by("sequence"))
    approval = next(event for event in events if event.action == "approved")
    publication = next(event for event in events if event.action == "published")
    assert approved.state == "published"
    assert approved.published_at == publication.occurred_at
    assert approved.recognition_status == "admin_approved"
    assert approval.actor_account == benchmark_data["admin"]
    assert publication.actor_account == benchmark_data["admin"]
    assert publication.caused_by == approval
    assert approval.details["previous_state"] == "pending_review"
    assert approval.details["approved_by"] == str(benchmark_data["admin"].id)


def test_official_promotion_is_separate_noted_and_admin_only(benchmark_data):
    benchmark = _create_published(benchmark_data, slug="official-candidate-0-1")

    with pytest.raises(BenchmarkPermissionError, match="Only active admins"):
        promote_benchmark_official(
            benchmark.id,
            reviewer=benchmark_data["contributor"],
            note="A contributor cannot promote it.",
        )
    with pytest.raises(BenchmarkValidationError, match="Explain why"):
        promote_benchmark_official(
            benchmark.id, reviewer=benchmark_data["admin"], note="   "
        )

    promoted = promote_benchmark_official(
        benchmark.id,
        reviewer=benchmark_data["admin"],
        note="Approved as the reference memory benchmark.",
    )

    event = promoted.moderation_events.get(action="promoted_official")
    assert promoted.recognition_status == "official"
    assert event.actor_account == benchmark_data["admin"]
    assert event.note == "Approved as the reference memory benchmark."
    assert event.details["previous_status"] == "admin_approved"


def test_predecessor_successor_duplicate_and_withdrawn_reapproval(benchmark_data):
    predecessor = benchmark_data["benchmark"]
    with pytest.raises(BenchmarkPermissionError, match="uploader or an administrator"):
        _create_pending(
            benchmark_data,
            slug="unauthorised-successor-0-2",
            version="0.2",
            previous_revision=str(predecessor.id),
            description=None,
        )

    successor = create_benchmark_submission(
        _payload(
            benchmark_data,
            slug="memory-smoke-test-0-2",
            version="0.2",
            previous_revision=str(predecessor.id),
            description=None,
            revision_description="Adds a stricter required circuit.",
        ),
        submitter=benchmark_data["admin"],
    ).benchmark
    assert successor.previous_revision == predecessor
    assert successor.history == predecessor.history
    assert successor.state == "pending_review"
    assert successor.moderation_events.filter(action="revision_created").exists()

    with pytest.raises(BenchmarkStateError, match="already has an exact successor"):
        create_benchmark_submission(
            _payload(
                benchmark_data,
                slug="competing-successor-0-2",
                version="0.2",
                previous_revision=str(predecessor.id),
                description=None,
            ),
            submitter=benchmark_data["admin"],
        )

    approve_benchmark_submission(successor.id, reviewer=benchmark_data["admin"])
    BenchmarkRevision.objects.filter(id=successor.id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )
    successor.refresh_from_db()
    reapproval = create_benchmark_submission(
        _payload(
            benchmark_data,
            slug="memory-smoke-test-0-3",
            version="0.3",
            previous_revision=str(successor.id),
            description=None,
            revision_description="Replaces the withdrawn second revision.",
        ),
        submitter=benchmark_data["admin"],
    ).benchmark
    assert reapproval.state == "pending_reapproval"
    assert reapproval.moderation_events.get(action="resubmitted")

    with pytest.raises(BenchmarkValidationError, match="slug is already in use"):
        create_benchmark_submission(
            _payload(benchmark_data, slug=reapproval.slug),
            submitter=benchmark_data["admin"],
        )


def test_submission_rejects_nonpublic_and_duplicate_manifest_circuits(
    benchmark_data,
):
    circuit = benchmark_data["circuit"]
    CircuitRevision.objects.filter(id=circuit.id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )
    with pytest.raises(BenchmarkValidationError, match="published circuit revision"):
        canonical_benchmark_payload(_payload(benchmark_data))

    CircuitRevision.objects.filter(id=circuit.id).update(
        state="published", withdrawn_at=None
    )
    with pytest.raises(BenchmarkValidationError, match="only once"):
        canonical_benchmark_payload(
            _payload(benchmark_data, items=_items((circuit, True), (circuit, False)))
        )


def test_approval_revalidates_that_manifest_circuits_remain_public(benchmark_data):
    benchmark = _create_pending(benchmark_data, slug="approval-revalidation-0-1")
    CircuitRevision.objects.filter(id=benchmark_data["circuit"].id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )

    with pytest.raises(BenchmarkValidationError, match="still be published"):
        approve_benchmark_submission(benchmark.id, reviewer=benchmark_data["admin"])

    benchmark.refresh_from_db()
    assert benchmark.state == "pending_review"
    assert not benchmark.moderation_events.filter(action="approved").exists()


def test_approval_rejects_a_valid_file_with_the_wrong_manifest_meaning(
    benchmark_data,
):
    benchmark = _create_pending(benchmark_data, slug="wrong-manifest-0-1")
    wrong_file, _created = store_artifact_chunks(
        [b'{"schema":"circuit-bench/benchmark-manifest/0.1","items":[]}\n'],
        uploaded_by=benchmark_data["contributor"],
        media_type="application/json",
        original_filename="wrong-but-valid-manifest.json",
    )
    BenchmarkRevision.objects.filter(id=benchmark.id).update(
        manifest_artifact=wrong_file
    )

    with pytest.raises(BenchmarkValidationError, match="does not exactly match"):
        approve_benchmark_submission(benchmark.id, reviewer=benchmark_data["admin"])

    benchmark.refresh_from_db()
    assert benchmark.state == "pending_review"
    assert not benchmark.moderation_events.filter(action="approved").exists()


def test_attempt_forms_are_two_step_and_limit_results_to_exact_matches(
    benchmark_data,
):
    selection = BenchmarkAttemptSelectionForm(
        {
            "benchmark_revision": benchmark_data["benchmark"].id,
            "decoder_version": benchmark_data["decoder"].id,
        }
    )
    assert selection.is_valid(), selection.errors

    results = BenchmarkAttemptResultsForm(
        benchmark=selection.cleaned_data["benchmark_revision"],
        decoder=selection.cleaned_data["decoder_version"],
    )
    field_name = results.field_name(benchmark_data["circuit"].id)
    assert list(results.fields) == ["description", field_name]
    assert results.fields[field_name].required is True
    assert list(results.fields[field_name].queryset) == [benchmark_data["result"]]


def test_attempt_view_selects_then_submits_results_for_review(client, benchmark_data):
    client.force_login(benchmark_data["contributor"])
    url = reverse("benchmark-submissions:attempt-create")
    first = client.get(url)
    assert first.status_code == 200
    assert b"Choose results" in first.content
    assert b"Submit for review" not in first.content

    selected = client.get(
        url,
        {
            "benchmark_revision": benchmark_data["benchmark"].id,
            "decoder_version": benchmark_data["decoder"].id,
        },
    )
    assert selected.status_code == 200
    assert b"Submit for review" in selected.content
    field_name = BenchmarkAttemptResultsForm.field_name(benchmark_data["circuit"].id)

    response = client.post(
        url,
        {
            "benchmark_revision": benchmark_data["benchmark"].id,
            "decoder_version": benchmark_data["decoder"].id,
            "description": "A complete attempt from existing exact results.",
            field_name: benchmark_data["result"].id,
        },
    )

    attempt = BenchmarkAttempt.objects.latest("created_at")
    assert response.status_code == 302
    assert response.url == reverse(
        "benchmark-submissions:attempt-candidate", args=[attempt.id]
    )
    assert attempt.state == "pending_review"
    assert attempt.published_at is None
    assert attempt.submitted_by == benchmark_data["contributor"]
    assert attempt.result_memberships.get().result == benchmark_data["result"]
    submitted = attempt.moderation_events.get(action="submitted")
    assert submitted.payload_snapshot["data"]["results"] == [
        {
            "circuit_revision": str(benchmark_data["circuit"].id),
            "result": str(benchmark_data["result"].id),
        }
    ]


@pytest.mark.parametrize("include_optional", [False, True])
def test_attempt_submission_accepts_optional_omission_or_completion(
    benchmark_data, include_optional
):
    optional_circuit = _second_circuit(benchmark_data)
    optional_result = _result_for(benchmark_data, optional_circuit)
    benchmark = _create_published(
        benchmark_data,
        slug=f"required-optional-{include_optional}-0-1",
        items=_items(
            (benchmark_data["circuit"], True),
            (optional_circuit, False),
        ),
    )
    mapping = _attempt_mapping(
        benchmark,
        benchmark_data["result"],
        optional_result if include_optional else None,
    )

    attempt = create_benchmark_attempt(
        benchmark=benchmark,
        decoder=benchmark_data["decoder"],
        result_ids_by_circuit=mapping,
        submitter=benchmark_data["contributor"],
        description="An exact compatible attempt.",
    )

    assert attempt.state == "pending_review"
    assert attempt.published_at is None
    assert attempt.result_memberships.count() == (2 if include_optional else 1)

    published = approve_benchmark_attempt(attempt.id, reviewer=benchmark_data["admin"])
    assert published.state == "published"
    assert published.published_at is not None
    events = list(published.moderation_events.order_by("sequence"))
    assert [event.action for event in events] == ["submitted", "approved", "published"]
    assert events[-1].caused_by == events[-2]


def test_attempt_approval_revalidates_referenced_results(benchmark_data):
    attempt = create_benchmark_attempt(
        benchmark=benchmark_data["benchmark"],
        decoder=benchmark_data["decoder"],
        result_ids_by_circuit={
            str(benchmark_data["circuit"].id): str(benchmark_data["result"].id)
        },
        submitter=benchmark_data["contributor"],
    )
    Result.objects.filter(id=benchmark_data["result"].id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )

    with pytest.raises(BenchmarkValidationError, match="published result"):
        approve_benchmark_attempt(attempt.id, reviewer=benchmark_data["admin"])

    attempt.refresh_from_db()
    assert attempt.state == "pending_review"


def test_attempt_rejects_missing_required_result(benchmark_data):
    with pytest.raises(BenchmarkValidationError, match="needs one result"):
        create_benchmark_attempt(
            benchmark=benchmark_data["benchmark"],
            decoder=benchmark_data["decoder"],
            result_ids_by_circuit={},
            submitter=benchmark_data["contributor"],
        )


def test_attempt_rejects_result_from_another_decoder(benchmark_data):
    with pytest.raises(BenchmarkValidationError, match="different decoder"):
        create_benchmark_attempt(
            benchmark=benchmark_data["benchmark"],
            decoder=benchmark_data["other_decoder"],
            result_ids_by_circuit={
                str(benchmark_data["circuit"].id): str(benchmark_data["result"].id)
            },
            submitter=benchmark_data["contributor"],
        )


def test_attempt_rejects_result_from_another_circuit(benchmark_data):
    second = _second_circuit(benchmark_data)
    benchmark = _create_published(
        benchmark_data,
        slug="mismatched-circuit-0-1",
        items=_items((second, True)),
    )

    with pytest.raises(BenchmarkValidationError, match="different circuit"):
        create_benchmark_attempt(
            benchmark=benchmark,
            decoder=benchmark_data["decoder"],
            result_ids_by_circuit={str(second.id): str(benchmark_data["result"].id)},
            submitter=benchmark_data["contributor"],
        )


def test_attempt_rejects_unpublished_result(benchmark_data):
    Result.objects.filter(id=benchmark_data["result"].id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )

    with pytest.raises(BenchmarkValidationError, match="published result"):
        create_benchmark_attempt(
            benchmark=benchmark_data["benchmark"],
            decoder=benchmark_data["decoder"],
            result_ids_by_circuit={
                str(benchmark_data["circuit"].id): str(benchmark_data["result"].id)
            },
            submitter=benchmark_data["contributor"],
        )


def test_attempt_rejects_one_result_reused_for_two_manifest_positions(
    benchmark_data,
):
    second = _second_circuit(benchmark_data)
    benchmark = _create_published(
        benchmark_data,
        slug="duplicate-result-0-1",
        items=_items((benchmark_data["circuit"], True), (second, True)),
    )

    with pytest.raises(BenchmarkValidationError, match="same exact result"):
        create_benchmark_attempt(
            benchmark=benchmark,
            decoder=benchmark_data["decoder"],
            result_ids_by_circuit={
                str(benchmark_data["circuit"].id): str(benchmark_data["result"].id),
                str(second.id): str(benchmark_data["result"].id),
            },
            submitter=benchmark_data["contributor"],
        )


def test_attempt_rejects_unpublished_benchmark_or_decoder(benchmark_data):
    pending = _create_pending(benchmark_data, slug="pending-attempt-0-1")
    mapping = {str(benchmark_data["circuit"].id): str(benchmark_data["result"].id)}
    with pytest.raises(BenchmarkStateError, match="benchmark revision"):
        create_benchmark_attempt(
            benchmark=pending,
            decoder=benchmark_data["decoder"],
            result_ids_by_circuit=mapping,
            submitter=benchmark_data["contributor"],
        )

    DecoderVersion.objects.filter(id=benchmark_data["decoder"].id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )
    with pytest.raises(BenchmarkStateError, match="decoder version"):
        create_benchmark_attempt(
            benchmark=benchmark_data["benchmark"],
            decoder=benchmark_data["decoder"],
            result_ids_by_circuit=mapping,
            submitter=benchmark_data["contributor"],
        )


def test_candidate_is_private_to_submitter_and_admin(client, benchmark_data):
    pending = _create_pending(benchmark_data, slug="private-candidate-0-1")
    url = reverse("benchmark-submissions:candidate", args=[pending.id])

    assert client.get(url).status_code == 302
    outsider = Account.objects.create_user(display_name="Outside scientist")
    client.force_login(outsider)
    assert client.get(url).status_code == 403
    client.force_login(benchmark_data["contributor"])
    owner = client.get(url)
    assert owner.status_code == 200
    assert pending.name.encode() in owner.content
    assert b"Approve and publish" not in owner.content
    client.force_login(benchmark_data["admin"])
    admin = client.get(url)
    assert admin.status_code == 200
    assert b"Approve and publish" in admin.content


def test_review_queue_is_admin_only_and_contains_only_waiting_records(
    client, benchmark_data
):
    pending = _create_pending(benchmark_data, slug="queued-benchmark-0-1")
    url = reverse("benchmark-submissions:review")
    assert client.get(url).status_code == 302

    client.force_login(benchmark_data["contributor"])
    assert client.get(url).status_code == 403
    client.force_login(benchmark_data["admin"])
    response = client.get(url)
    assert response.status_code == 200
    assert pending.name.encode() in response.content
    assert benchmark_data["benchmark"].name.encode() not in response.content


def test_approve_and_promote_routes_require_post_and_admin(benchmark_data, client):
    pending = _create_pending(benchmark_data, slug="post-only-actions-0-1")
    approve_url = reverse("benchmark-submissions:approve", args=[pending.id])
    promote_url = reverse("benchmark-submissions:promote", args=[pending.id])
    client.force_login(benchmark_data["contributor"])
    assert client.get(approve_url).status_code == 405
    assert client.get(promote_url).status_code == 405
    client.post(approve_url)
    pending.refresh_from_db()
    assert pending.state == "pending_review"


def test_approve_and_promote_forms_work_with_enforced_csrf(benchmark_data):
    pending = _create_pending(benchmark_data, slug="csrf-actions-0-1")
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(benchmark_data["admin"])
    approve_url = reverse("benchmark-submissions:approve", args=[pending.id])

    assert csrf_client.post(approve_url).status_code == 403
    page = csrf_client.get(
        reverse("benchmark-submissions:candidate", args=[pending.id])
    )
    assert page.status_code == 200
    token = csrf_client.cookies["csrftoken"].value
    approved = csrf_client.post(approve_url, {"csrfmiddlewaretoken": token})
    pending.refresh_from_db()
    assert approved.status_code == 302
    assert pending.state == "published"

    promote_url = reverse("benchmark-submissions:promote", args=[pending.id])
    promoted = csrf_client.post(
        promote_url,
        {
            "csrfmiddlewaretoken": token,
            "note": "Promoted after documented administrator review.",
        },
    )
    pending.refresh_from_db()
    assert promoted.status_code == 302
    assert pending.recognition_status == "official"
    assert (
        pending.moderation_events.get(
            action=ModerationEvent.Action.PROMOTED_OFFICIAL
        ).actor_account
        == benchmark_data["admin"]
    )


def test_commit_route_requires_csrf(benchmark_data):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(benchmark_data["contributor"])
    preview_id = uuid4()
    session = csrf_client.session
    session["benchmark_submission_previews"] = {
        str(preview_id): canonical_benchmark_payload(
            _payload(benchmark_data, slug="csrf-commit-0-1")
        )
    }
    session.save()

    response = csrf_client.post(
        reverse("benchmark-submissions:commit", args=[preview_id])
    )

    assert response.status_code == 403
    assert not BenchmarkRevision.objects.filter(slug="csrf-commit-0-1").exists()
