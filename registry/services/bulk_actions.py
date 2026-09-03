"""Atomic cross-kind actions used by contributor and moderation tables."""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction

from accounts.models import Account
from registry.models import CircuitCollection, CircuitRevision, RecordEvent
from registry.models.common import REVIEW_QUEUE_STATES
from registry.services.collections import (
    can_curate_collection,
    collection_circuit_ids,
)
from registry.services.histories import append_history_event, latest_snapshot_event
from registry.services.review_decisions import reject_submission
from registry.services.submissions import approve_submission, withdraw_submission
from registry.services.visibility import (
    KIND_MODEL,
    official_benchmark_lock_reason,
    set_record_visibility,
)
from registry.submission_policy import ENABLED_SUBMISSION_KINDS, SubmissionKind

MAX_BULK_TARGETS = 200
GENERIC_KINDS = {kind.value for kind in ENABLED_SUBMISSION_KINDS}
KIND_LABELS = {
    "decoder": "Decoder version",
    "circuit": "Circuit revision",
    "result": "Result",
    "machine": "Machine",
    "noise_model": "Noise model",
    "benchmark": "Benchmark revision",
    "benchmark_attempt": "Benchmark attempt",
    "collection": "Circuit collection",
}
BULK_KINDS = {
    "decoder",
    "circuit",
    "result",
    "machine",
    "noise_model",
    "benchmark",
    "benchmark_attempt",
    "collection",
}


class BulkActionError(Exception):
    pass


@dataclass(frozen=True)
class BulkTarget:
    kind: str
    record_id: object
    label: str
    state: str
    visibility: str

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.record_id}"

    @property
    def kind_label(self) -> str:
        return KIND_LABELS[self.kind]

    @property
    def state_label(self) -> str:
        return self.state.replace("_", " ").capitalize()

    @property
    def visibility_label(self) -> str:
        return self.visibility.capitalize()


@dataclass(frozen=True)
class CollectionVisibilityCascade:
    """A previewable plan for a collection page and its curator-owned circuits."""

    targets: tuple[BulkTarget, ...]
    skipped_other_owner_count: int
    skipped_unchanged_count: int
    skipped_locked: tuple[tuple[str, str], ...]


def parse_target_key(value: str) -> tuple[str, str]:
    kind, separator, record_id = value.partition(":")
    if not separator or kind not in BULK_KINDS or not record_id:
        raise BulkActionError("A selected record identifier is invalid.")
    return kind, record_id


def resolve_targets(
    raw_targets,
    *,
    actor: Account,
    collection_scope=None,
) -> tuple[BulkTarget, ...]:
    keys = list(dict.fromkeys(value for value in raw_targets if value))
    if collection_scope:
        collection = CircuitCollection.objects.filter(id=collection_scope).first()
        if collection is None:
            raise BulkActionError("The selected circuit collection does not exist.")
        ids = collection_circuit_ids(
            collection,
            include_descendants=True,
            viewer=actor,
        )
        owned = CircuitRevision.objects.filter(id__in=ids)
        if not actor.is_admin:
            owned = owned.filter(submitted_by=actor)
        keys.extend(
            f"circuit:{record_id}"
            for record_id in owned.order_by("id").values_list("id", flat=True)
        )
        keys = list(dict.fromkeys(keys))
    if not keys:
        raise BulkActionError("Select at least one record.")
    if len(keys) > MAX_BULK_TARGETS:
        raise BulkActionError(f"Select at most {MAX_BULK_TARGETS} records at once.")

    targets = []
    for key in keys:
        kind, record_id = parse_target_key(key)
        model = KIND_MODEL[kind]
        record = model.objects.filter(id=record_id).first()
        if record is None:
            raise BulkActionError("A selected record no longer exists.")
        if not actor.is_admin and record.submitted_by_id != actor.id:
            raise PermissionDenied(
                "Bulk actions only affect records that you contributed."
            )
        targets.append(
            BulkTarget(
                kind=kind,
                record_id=record.id,
                label=_label(kind, record),
                state=record.state,
                visibility=record.visibility,
            )
        )
    return tuple(targets)


def plan_collection_visibility_cascade(
    collection_id,
    *,
    action: str,
    actor: Account,
) -> CollectionVisibilityCascade:
    """Plan, but do not apply, a collection-and-owned-circuits visibility change."""

    if action not in {"make_public", "make_private"}:
        raise BulkActionError(
            "Collection visibility actions must make records public or private."
        )
    collection = CircuitCollection.objects.filter(id=collection_id).first()
    if collection is None:
        raise BulkActionError("The selected circuit collection does not exist.")
    if not can_curate_collection(actor, collection):
        raise PermissionDenied(
            "Only the collection curator or an admin may change the collection page."
        )

    desired_visibility = "public" if action == "make_public" else "private"
    circuit_ids = collection_circuit_ids(
        collection,
        include_descendants=True,
        viewer=actor,
    )
    visible_circuits = CircuitRevision.objects.filter(id__in=circuit_ids).order_by(
        "name", "id"
    )
    manageable_circuits = visible_circuits
    if not actor.is_admin:
        manageable_circuits = manageable_circuits.filter(submitted_by=actor)
    skipped_other_owner_count = visible_circuits.exclude(
        id__in=manageable_circuits.values("id")
    ).count()

    keys = []
    skipped_unchanged_count = 0
    skipped_locked = []
    if collection.visibility == desired_visibility:
        skipped_unchanged_count += 1
    else:
        keys.append(f"collection:{collection.id}")

    for circuit in manageable_circuits:
        if circuit.visibility == desired_visibility:
            skipped_unchanged_count += 1
            continue
        if desired_visibility == "private":
            reason = official_benchmark_lock_reason("circuit", circuit)
            if reason:
                skipped_locked.append((circuit.name, reason))
                continue
        keys.append(f"circuit:{circuit.id}")

    if len(keys) > MAX_BULK_TARGETS:
        raise BulkActionError(
            f"This operation would change more than {MAX_BULK_TARGETS} records."
        )
    if not keys:
        raise BulkActionError(
            "The collection page and all eligible circuits are already "
            f"{desired_visibility}."
        )
    return CollectionVisibilityCascade(
        targets=resolve_targets(keys, actor=actor),
        skipped_other_owner_count=skipped_other_owner_count,
        skipped_unchanged_count=skipped_unchanged_count,
        skipped_locked=tuple(skipped_locked),
    )


def validate_bulk_action(action: str, targets, *, actor: Account) -> None:
    valid_actions = {"make_public", "make_private", "withdraw", "approve", "reject"}
    if action not in valid_actions:
        raise BulkActionError("Unknown bulk action.")
    if action in {"approve", "reject"} and not actor.is_admin:
        raise PermissionDenied("Only administrators may review submissions.")
    for target in targets:
        if action == "withdraw":
            if target.state != "published":
                raise BulkActionError(f"{target.label} is not published.")
            record = KIND_MODEL[target.kind].objects.get(id=target.record_id)
            reason = official_benchmark_lock_reason(target.kind, record)
            if reason:
                raise BulkActionError(f"{target.label} cannot be withdrawn. {reason}")
        elif (
            action in {"approve", "reject"} and target.state not in REVIEW_QUEUE_STATES
        ):
            raise BulkActionError(f"{target.label} is not waiting for review.")


@transaction.atomic
def apply_bulk_action(
    action: str,
    targets,
    *,
    actor: Account,
    note: str = "",
) -> int:
    validate_bulk_action(action, targets, actor=actor)
    for target in targets:
        if action == "make_public":
            set_record_visibility(
                target.kind,
                target.record_id,
                actor=actor,
                visibility="public",
            )
        elif action == "make_private":
            set_record_visibility(
                target.kind,
                target.record_id,
                actor=actor,
                visibility="private",
            )
        elif action == "withdraw":
            _withdraw(target, actor=actor, note=note)
        elif action == "approve":
            _approve(target, actor=actor)
        else:
            _reject(target, actor=actor, note=note)
    return len(targets)


def _withdraw(target: BulkTarget, *, actor, note):
    if target.kind in GENERIC_KINDS:
        return withdraw_submission(
            SubmissionKind(target.kind),
            target.record_id,
            actor=actor,
            note=note or "Withdrawn through a bulk action.",
        )
    record = (
        KIND_MODEL[target.kind].objects.select_for_update().get(id=target.record_id)
    )
    if record.state != "published":
        raise BulkActionError(f"{target.label} is not published.")
    reason = official_benchmark_lock_reason(target.kind, record)
    if reason:
        raise BulkActionError(f"{target.label} cannot be withdrawn. {reason}")
    event = append_history_event(
        kind=target.kind,
        record=record,
        actor=actor,
        action=RecordEvent.Action.WITHDRAWN,
        note=note or "Withdrawn through a bulk action.",
        details={"policy_version": "0.1", "bulk_action": True},
    )
    record.state = "withdrawn"
    record.withdrawn_at = event.occurred_at
    record.save(update_fields=["state", "withdrawn_at"])
    return record


def _approve(target: BulkTarget, *, actor):
    if target.kind in GENERIC_KINDS:
        return approve_submission(
            SubmissionKind(target.kind), target.record_id, reviewer=actor
        )
    if target.kind == "noise_model":
        from registry.services.taxonomy import approve_and_publish_noise_model

        return approve_and_publish_noise_model(target.record_id, reviewer=actor)
    if target.kind == "benchmark":
        from registry.services.benchmark_submissions import approve_benchmark_submission

        return approve_benchmark_submission(target.record_id, reviewer=actor)
    if target.kind == "benchmark_attempt":
        from registry.services.benchmark_submissions import approve_benchmark_attempt

        return approve_benchmark_attempt(target.record_id, reviewer=actor)
    raise BulkActionError(f"{target.label} does not use the review queue.")


def _reject(target: BulkTarget, *, actor, note):
    if not note.strip():
        raise BulkActionError("A review note is required when rejecting records.")
    if target.kind in GENERIC_KINDS:
        return reject_submission(
            SubmissionKind(target.kind),
            target.record_id,
            reviewer=actor,
            note=note,
        )
    record = (
        KIND_MODEL[target.kind].objects.select_for_update().get(id=target.record_id)
    )
    append_history_event(
        kind=target.kind,
        record=record,
        actor=actor,
        action=RecordEvent.Action.REJECTED,
        note=note.strip(),
        details={
            "policy_version": "0.1",
            "previous_state": record.state,
            "projected_state": "rejected",
            "bulk_action": True,
        },
        caused_by=latest_snapshot_event(target.kind, record),
        visibility=RecordEvent.Visibility.UPLOADER,
    )
    record.state = "rejected"
    record.published_at = None
    record.withdrawn_at = None
    record.save(update_fields=["state", "published_at", "withdrawn_at"])
    return record


def _label(kind: str, record) -> str:
    if kind == "decoder":
        return f"{record.name} {record.version}"
    if kind in {"circuit", "noise_model", "benchmark", "collection"}:
        return record.name
    if kind == "result":
        return f"{record.decoder_version} on {record.circuit_revision}"
    if kind == "benchmark_attempt":
        return f"{record.decoder_version} on {record.benchmark_revision}"
    if kind == "evaluator":
        return f"Evaluator {record.version}"
    if kind == "tag":
        return record.label
    return record.slug
