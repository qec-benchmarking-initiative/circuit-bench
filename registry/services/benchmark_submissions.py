"""Transactional benchmark-revision and benchmark-attempt submission services."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from accounts.models import Account
from registry.models import (
    BenchmarkAttempt,
    BenchmarkAttemptResult,
    BenchmarkRevision,
    BenchmarkRevisionItem,
    CircuitRevision,
    Credit,
    DecoderVersion,
    ModerationEvent,
    Result,
    SchemaRelease,
)
from registry.models.common import REVIEW_QUEUE_STATES
from registry.services.artifacts import store_artifact_chunks, verify_artifact
from registry.services.histories import (
    append_history_event,
    history_for_new_record,
    submission_snapshot,
)


class BenchmarkSubmissionError(Exception):
    pass


class BenchmarkPermissionError(BenchmarkSubmissionError):
    pass


class BenchmarkStateError(BenchmarkSubmissionError):
    pass


class BenchmarkValidationError(BenchmarkSubmissionError):
    pass


@dataclass(frozen=True)
class ManifestItem:
    circuit: CircuitRevision
    required: bool


@dataclass(frozen=True)
class BenchmarkSubmissionOutcome:
    benchmark: BenchmarkRevision
    manifest_created: bool


def canonical_benchmark_payload(payload: dict) -> dict:
    """Validate and return the stable JSON representation used for review."""

    slug = str(payload.get("slug", "")).strip()
    name = str(payload.get("name", "")).strip()
    version = str(payload.get("version", "")).strip()
    description = _nullable_text(payload.get("description"))
    revision_description = str(payload.get("revision_description", "")).strip()
    previous_id = _nullable_uuid(payload.get("previous_revision"), "previous revision")
    items = _manifest_items(payload.get("items"))

    if not slug:
        raise BenchmarkValidationError("Provide a permanent benchmark slug.")
    if not name:
        raise BenchmarkValidationError("Provide a benchmark name.")
    if not version:
        raise BenchmarkValidationError("Provide a benchmark version.")
    if not revision_description:
        raise BenchmarkValidationError("Describe this exact revision.")
    if previous_id is None and not description:
        raise BenchmarkValidationError(
            "The first benchmark revision requires a description."
        )
    if not any(item.required for item in items):
        raise BenchmarkValidationError(
            "A benchmark must contain at least one required circuit."
        )

    return {
        "slug": slug,
        "name": name,
        "version": version,
        "previous_revision": str(previous_id) if previous_id else None,
        "description": description,
        "revision_description": revision_description,
        "items": [
            {"circuit_revision": str(item.circuit.id), "required": item.required}
            for item in items
        ],
    }


@transaction.atomic
def create_benchmark_submission(
    payload: dict, *, submitter: Account
) -> BenchmarkSubmissionOutcome:
    if not submitter.is_active:
        raise BenchmarkPermissionError("Inactive accounts cannot submit benchmarks.")
    payload = canonical_benchmark_payload(payload)
    if BenchmarkRevision.objects.filter(slug=payload["slug"]).exists():
        raise BenchmarkValidationError("That benchmark slug is already in use.")

    previous = _previous_revision(payload["previous_revision"])
    if previous is not None:
        try:
            previous.next_revision
        except ObjectDoesNotExist:
            pass
        else:
            raise BenchmarkStateError(
                "That benchmark revision already has an exact successor."
            )

    items = _manifest_items(payload["items"])
    release = _frozen_benchmark_schema()
    state = (
        "pending_reapproval"
        if previous and previous.state == "withdrawn"
        else "pending_review"
    )
    history = history_for_new_record("benchmark", previous)
    manifest_bytes = _manifest_bytes(payload)
    manifest, manifest_created = store_artifact_chunks(
        [manifest_bytes],
        uploaded_by=submitter,
        media_type="application/json",
        original_filename=f"{payload['slug']}-manifest.json",
    )
    benchmark = BenchmarkRevision.objects.create(
        schema_release=release,
        history=history,
        slug=payload["slug"],
        name=payload["name"],
        version=payload["version"],
        previous_revision=previous,
        description=payload["description"],
        revision_description=payload["revision_description"],
        recognition_status=BenchmarkRevision.RecognitionStatus.COMMUNITY_SUBMITTED,
        manifest_artifact=manifest,
        submitted_by=submitter,
        state=state,
    )
    BenchmarkRevisionItem.objects.bulk_create(
        [
            BenchmarkRevisionItem(
                benchmark_revision=benchmark,
                circuit_revision=item.circuit,
                position=position,
                is_required=item.required,
            )
            for position, item in enumerate(items, 1)
        ]
    )
    Credit.objects.create(
        benchmark_revision=benchmark,
        position=1,
        account=submitter,
    )
    if previous is not None:
        append_history_event(
            kind="benchmark",
            record=benchmark,
            actor=submitter,
            action=ModerationEvent.Action.REVISION_CREATED,
            note="Created this exact benchmark revision as a successor.",
            details={"policy_version": "0.1", "predecessor_id": str(previous.id)},
        )
    snapshot_payload = {**payload, "manifest_artifact": str(manifest.id)}
    append_history_event(
        kind="benchmark",
        record=benchmark,
        actor=submitter,
        action=(
            ModerationEvent.Action.RESUBMITTED
            if state == "pending_reapproval"
            else ModerationEvent.Action.SUBMITTED
        ),
        note="Submitted a benchmark revision for administrator review.",
        details={
            "policy_version": "0.1",
            "approval_route": "admin_review",
            "projected_state": state,
        },
        payload_snapshot=submission_snapshot("benchmark", snapshot_payload),
    )
    return BenchmarkSubmissionOutcome(benchmark, manifest_created)


@transaction.atomic
def approve_benchmark_submission(
    benchmark_id, *, reviewer: Account
) -> BenchmarkRevision:
    _require_admin(reviewer)
    try:
        benchmark = (
            BenchmarkRevision.objects.select_for_update()
            .select_related("manifest_artifact")
            .get(id=benchmark_id)
        )
    except BenchmarkRevision.DoesNotExist as error:
        raise BenchmarkStateError("Benchmark submission not found.") from error
    if benchmark.state not in REVIEW_QUEUE_STATES:
        raise BenchmarkStateError("Only waiting benchmark revisions can be approved.")
    _validate_stored_manifest(benchmark)
    previous_state = benchmark.state
    details = {
        "policy_version": "0.1",
        "approval_route": "admin_review",
        "approved_by": str(reviewer.id),
        "approved_by_name": reviewer.display_name,
        "previous_state": previous_state,
    }
    approval = append_history_event(
        kind="benchmark",
        record=benchmark,
        actor=reviewer,
        action=ModerationEvent.Action.APPROVED,
        note="Approved the benchmark revision after manifest revalidation.",
        details=details,
    )
    publication = append_history_event(
        kind="benchmark",
        record=benchmark,
        actor=reviewer,
        action=ModerationEvent.Action.PUBLISHED,
        note="Published the administrator-approved benchmark revision.",
        details=details,
        caused_by=approval,
    )
    benchmark.state = "published"
    benchmark.published_at = publication.occurred_at
    benchmark.withdrawn_at = None
    benchmark.recognition_status = BenchmarkRevision.RecognitionStatus.ADMIN_APPROVED
    benchmark.full_clean()
    benchmark.save(
        update_fields=[
            "state",
            "published_at",
            "withdrawn_at",
            "recognition_status",
        ]
    )
    return benchmark


@transaction.atomic
def promote_benchmark_official(
    benchmark_id, *, reviewer: Account, note: str
) -> BenchmarkRevision:
    _require_admin(reviewer)
    note = note.strip()
    if not note:
        raise BenchmarkValidationError("Explain why this benchmark is now official.")
    try:
        benchmark = BenchmarkRevision.objects.select_for_update().get(id=benchmark_id)
    except BenchmarkRevision.DoesNotExist as error:
        raise BenchmarkStateError("Benchmark revision not found.") from error
    if benchmark.state != "published":
        raise BenchmarkStateError("Only a published benchmark can become official.")
    if benchmark.recognition_status == BenchmarkRevision.RecognitionStatus.OFFICIAL:
        raise BenchmarkStateError("This benchmark revision is already official.")
    benchmark.recognition_status = BenchmarkRevision.RecognitionStatus.OFFICIAL
    benchmark.save(update_fields=["recognition_status"])
    append_history_event(
        kind="benchmark",
        record=benchmark,
        actor=reviewer,
        action=ModerationEvent.Action.PROMOTED_OFFICIAL,
        note=note,
        details={"policy_version": "0.1", "previous_status": "admin_approved"},
    )
    return benchmark


@transaction.atomic
def create_benchmark_attempt(
    *,
    benchmark: BenchmarkRevision,
    decoder: DecoderVersion,
    result_ids_by_circuit: dict[str, str | None],
    submitter: Account,
    description: str = "",
) -> BenchmarkAttempt:
    """Publish a grouping of already-published compatible exact results."""

    if not submitter.is_active:
        raise BenchmarkPermissionError("Inactive accounts cannot submit attempts.")
    benchmark = BenchmarkRevision.objects.select_for_update().get(id=benchmark.id)
    decoder = DecoderVersion.objects.get(id=decoder.id)
    if benchmark.state != "published":
        raise BenchmarkStateError("The benchmark revision must be published.")
    if decoder.state != "published":
        raise BenchmarkStateError("The decoder version must be published.")
    items = list(
        benchmark.items.select_related("circuit_revision").order_by("position")
    )
    manifest_ids = {str(item.circuit_revision_id) for item in items}
    unexpected = set(result_ids_by_circuit) - manifest_ids
    if unexpected:
        raise BenchmarkValidationError(
            "An attempt cannot contain circuits outside the benchmark manifest."
        )

    memberships = []
    seen_results = set()
    for item in items:
        circuit_key = str(item.circuit_revision_id)
        raw_result_id = result_ids_by_circuit.get(circuit_key)
        if not raw_result_id:
            if item.is_required:
                raise BenchmarkValidationError(
                    f"Required manifest position {item.position} needs one result."
                )
            continue
        try:
            result_id = UUID(str(raw_result_id))
            result = Result.objects.get(id=result_id, state="published")
        except (ValueError, Result.DoesNotExist) as error:
            raise BenchmarkValidationError(
                f"Manifest position {item.position} does not name a published result."
            ) from error
        if result.id in seen_results:
            raise BenchmarkValidationError(
                "The same exact result cannot fill more than one manifest position."
            )
        if result.decoder_version_id != decoder.id:
            raise BenchmarkValidationError(
                f"Manifest position {item.position} uses a different decoder."
            )
        if result.circuit_revision_id != item.circuit_revision_id:
            raise BenchmarkValidationError(
                f"Manifest position {item.position} uses a different circuit."
            )
        seen_results.add(result.id)
        memberships.append((item.circuit_revision, result))

    published_at = timezone.now()
    attempt = BenchmarkAttempt.objects.create(
        benchmark_revision=benchmark,
        decoder_version=decoder,
        submitted_by=submitter,
        description=_nullable_text(description),
        state="published",
        published_at=published_at,
    )
    BenchmarkAttemptResult.objects.bulk_create(
        [
            BenchmarkAttemptResult(
                benchmark_attempt=attempt,
                circuit_revision=circuit,
                result=result,
            )
            for circuit, result in memberships
        ]
    )
    return attempt


def _manifest_items(raw_items) -> tuple[ManifestItem, ...]:
    if not isinstance(raw_items, list) or not raw_items:
        raise BenchmarkValidationError("Select at least one circuit revision.")
    seen = set()
    items = []
    for position, raw in enumerate(raw_items, 1):
        if not isinstance(raw, dict):
            raise BenchmarkValidationError(
                f"Manifest position {position} must be an object."
            )
        try:
            circuit_id = UUID(str(raw["circuit_revision"]))
            circuit = CircuitRevision.objects.get(id=circuit_id, state="published")
        except (KeyError, ValueError, CircuitRevision.DoesNotExist) as error:
            raise BenchmarkValidationError(
                f"Manifest position {position} must name a published circuit revision."
            ) from error
        if circuit.id in seen:
            raise BenchmarkValidationError(
                "Each circuit revision may occur only once in a benchmark manifest."
            )
        required = raw.get("required")
        if not isinstance(required, bool):
            raise BenchmarkValidationError(
                f"Manifest position {position} needs a boolean required value."
            )
        seen.add(circuit.id)
        items.append(ManifestItem(circuit, required))
    return tuple(items)


def _previous_revision(raw_id) -> BenchmarkRevision | None:
    if not raw_id:
        return None
    try:
        return BenchmarkRevision.objects.select_for_update().get(
            id=raw_id, state__in=["published", "withdrawn"]
        )
    except BenchmarkRevision.DoesNotExist as error:
        raise BenchmarkValidationError(
            "Previous revision must be published or withdrawn."
        ) from error


def _frozen_benchmark_schema() -> SchemaRelease:
    try:
        return SchemaRelease.objects.get(
            record_type=SchemaRelease.RecordType.BENCHMARK,
            version="0.1",
            state=SchemaRelease.State.FROZEN,
        )
    except SchemaRelease.DoesNotExist as error:
        raise BenchmarkStateError(
            "Frozen benchmark schema release 0.1 is unavailable."
        ) from error


def _manifest_bytes(payload: dict) -> bytes:
    manifest = {
        "schema": "circuit-bench/benchmark-manifest/0.1",
        "benchmark": {"slug": payload["slug"], "version": payload["version"]},
        "items": [
            {
                "position": position,
                "circuit_revision": item["circuit_revision"],
                "required": item["required"],
            }
            for position, item in enumerate(payload["items"], 1)
        ],
    }
    return (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()


def _validate_stored_manifest(benchmark: BenchmarkRevision) -> None:
    verify_artifact(benchmark.manifest_artifact)
    items = list(
        benchmark.items.select_related("circuit_revision").order_by("position")
    )
    if not items or not any(item.is_required for item in items):
        raise BenchmarkValidationError(
            "A benchmark needs at least one required manifest circuit."
        )
    if [item.position for item in items] != list(range(1, len(items) + 1)):
        raise BenchmarkValidationError("Manifest positions must be continuous from 1.")
    if any(item.circuit_revision.state != "published" for item in items):
        raise BenchmarkValidationError(
            "Every manifest circuit must still be published at approval."
        )


def _require_admin(account: Account) -> None:
    if not account.is_active or not account.is_admin:
        raise BenchmarkPermissionError("Only active admins may perform this action.")


def _nullable_text(value) -> str | None:
    text = str(value or "").strip()
    return text or None


def _nullable_uuid(value, label: str) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except ValueError as error:
        raise BenchmarkValidationError(f"Invalid {label} identifier.") from error
