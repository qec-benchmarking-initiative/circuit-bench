"""One authority for record visibility and public dependency closure."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, QuerySet

from accounts.models import Account
from registry.models import (
    BenchmarkAttempt,
    BenchmarkRevision,
    CircuitCollection,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    RecordEvent,
    Result,
    Tag,
)
from registry.models.common import RecordVisibility
from registry.services.histories import append_history_event

KIND_MODEL = {
    "decoder": DecoderVersion,
    "circuit": CircuitRevision,
    "result": Result,
    "machine": Machine,
    "noise_model": NoiseModel,
    "benchmark": BenchmarkRevision,
    "benchmark_attempt": BenchmarkAttempt,
    "tag": Tag,
    "evaluator": EvaluatorRelease,
    "collection": CircuitCollection,
}


class VisibilityError(Exception):
    pass


def actor_visibility_q(actor: Account | None, prefix: str = "") -> Q:
    """Records visible by their own flag or contributor/admin authority."""

    visibility = f"{prefix}visibility"
    submitted_by = f"{prefix}submitted_by"
    if getattr(actor, "is_admin", False):
        # A bare Q() is an identity element, not a Boolean ``true`` once it is
        # ORed with another condition.  Return an explicit tautology for the
        # (non-null) primary key so nullable dependency expressions such as
        # ``machine IS NULL OR actor_visibility_q(...)`` remain unrestricted
        # for administrators.
        return Q(**{f"{prefix}pk__isnull": False})
    if getattr(actor, "is_authenticated", False):
        return Q(**{visibility: RecordVisibility.PUBLIC}) | Q(**{submitted_by: actor})
    return Q(**{visibility: RecordVisibility.PUBLIC})


def visible_to_actor(queryset: QuerySet, actor: Account | None) -> QuerySet:
    return queryset.filter(actor_visibility_q(actor))


def can_manage_visibility(actor: Account, record) -> bool:
    return bool(
        actor.is_active and (actor.is_admin or record.submitted_by_id == actor.id)
    )


def official_benchmark_lock_reason(kind: str, record) -> str | None:
    """Explain why a record must remain publicly available, if applicable."""

    official = BenchmarkRevision.RecognitionStatus.OFFICIAL
    benchmark_filter = Q(
        benchmark_revision__recognition_status=official,
        benchmark_revision__state="published",
    )
    if kind == "benchmark" and record.recognition_status == official:
        return "This is an official benchmark revision."
    if (
        kind == "benchmark_attempt"
        and record.benchmark_revision.recognition_status == official
    ):
        return "This attempt belongs to an official benchmark."
    if (
        kind == "circuit"
        and record.benchmark_items.filter(
            benchmark_revision__recognition_status=official,
            benchmark_revision__state="published",
        ).exists()
    ):
        return "This circuit is required by an official benchmark."
    if (
        kind == "result"
        and record.benchmark_attempt_memberships.filter(
            **{
                "benchmark_attempt__benchmark_revision__recognition_status": official,
                "benchmark_attempt__benchmark_revision__state": "published",
            }
        ).exists()
    ):
        return "This result is part of an official benchmark attempt."
    if (
        kind == "decoder"
        and BenchmarkAttempt.objects.filter(
            benchmark_filter,
            state="published",
            decoder_version=record,
        ).exists()
    ):
        return "This decoder is used by an official benchmark attempt."
    result_ids = Result.objects.filter(
        benchmark_attempt_memberships__benchmark_attempt__benchmark_revision__recognition_status=official,
        benchmark_attempt_memberships__benchmark_attempt__benchmark_revision__state="published",
    )
    if kind == "machine" and result_ids.filter(machine=record).exists():
        return "This machine is used by an official benchmark result."
    if kind == "evaluator" and result_ids.filter(evaluator_version=record).exists():
        return "This evaluator is used by an official benchmark result."
    if (
        kind == "noise_model"
        and CircuitRevision.objects.filter(
            noise_model=record,
            benchmark_items__benchmark_revision__recognition_status=official,
            benchmark_items__benchmark_revision__state="published",
        ).exists()
    ):
        return "This noise model is used by an official benchmark circuit."
    return None


@transaction.atomic
def set_record_visibility(
    kind: str,
    record_id,
    *,
    actor: Account,
    visibility: str,
):
    if kind not in KIND_MODEL:
        raise VisibilityError("Unknown record kind.")
    if visibility not in RecordVisibility.values:
        raise VisibilityError("Visibility must be public or private.")
    model = KIND_MODEL[kind]
    try:
        record = model.objects.select_for_update().get(id=record_id)
    except model.DoesNotExist as error:
        raise VisibilityError("Record not found.") from error
    if not can_manage_visibility(actor, record):
        raise PermissionDenied(
            "Only the contributor or an admin may change visibility."
        )
    if visibility == RecordVisibility.PRIVATE:
        reason = official_benchmark_lock_reason(kind, record)
        if reason:
            raise VisibilityError(f"This record cannot be made private. {reason}")
    if record.visibility == visibility:
        return record

    previous = record.visibility
    record.visibility = visibility
    record.save(update_fields=["visibility"])
    append_history_event(
        kind=kind,
        record=record,
        actor=actor,
        action=(
            RecordEvent.Action.MADE_PUBLIC
            if visibility == RecordVisibility.PUBLIC
            else RecordEvent.Action.MADE_PRIVATE
        ),
        note=f"Made this record {visibility}.",
        details={"previous_visibility": previous, "visibility": visibility},
    )
    return record
