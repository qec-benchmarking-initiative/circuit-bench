"""Ordered, append-only workflow histories for exact scientific records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Max, Q
from django.urls import NoReverseMatch, reverse

from registry.models import Artifact, RecordEvent, RecordHistory

SUBJECT_FIELD_BY_KIND = {
    "decoder": "decoder_version",
    "noise_model": "noise_model",
    "circuit": "circuit_revision",
    "machine": "machine",
    "result": "result",
    "tag": "tag",
    "benchmark": "benchmark_revision",
    "benchmark_attempt": "benchmark_attempt",
    "evaluator": "evaluator_release",
}

SNAPSHOT_ACTIONS = (
    RecordEvent.Action.SUBMITTED,
    RecordEvent.Action.EDITED,
    RecordEvent.Action.RESUBMITTED,
)


def history_for_new_record(kind: str, predecessor=None) -> RecordHistory:
    """Reuse a predecessor's history or create the stable history container."""

    if predecessor is not None:
        if predecessor.history.record_kind != kind:
            raise ValueError("A predecessor belongs to a different record kind.")
        return predecessor.history
    return RecordHistory.objects.create(record_kind=kind)


def submission_snapshot(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Wrap canonical submitted data with the exact public schema identity."""

    artifact_ids = {
        str(value)
        for key, value in payload.items()
        if key.endswith("_artifact") and value
    }
    artifacts = {
        str(artifact.id): {
            "sha256": artifact.sha256,
            "byte_size": artifact.byte_size,
            "media_type": artifact.media_type,
            "original_filename": artifact.original_filename,
        }
        for artifact in Artifact.objects.filter(id__in=artifact_ids)
    }
    return {
        "schema": {"record_type": kind, "version": "0.1"},
        "data": payload,
        "artifacts": artifacts,
    }


def latest_snapshot_event(kind: str, record) -> RecordEvent:
    """Return the latest recorded payload for this exact record, not its lineage.

    Pre-history-migration events may explicitly record that their payload was
    unavailable. They remain the only defensible cause for a decision on one of
    those legacy candidates.
    """

    subject_field = SUBJECT_FIELD_BY_KIND[kind]
    candidates = RecordEvent.objects.filter(
        history_id=record.history_id,
        action__in=SNAPSHOT_ACTIONS,
        **{subject_field: record},
    )
    event = (
        candidates.filter(payload_snapshot__isnull=False)
        .order_by("-sequence", "-id")
        .first()
    )
    event = (
        event
        or candidates.filter(details__legacy_payload_unavailable=True)
        .order_by("-sequence", "-id")
        .first()
    )
    if event is None:
        raise ValueError("The exact record has no recorded submission payload event.")
    return event


@transaction.atomic
def append_history_event(
    *,
    kind: str,
    record,
    action: str,
    note: str,
    details: dict[str, Any] | None = None,
    actor=None,
    actor_system: str | None = None,
    payload_snapshot: dict[str, Any] | None = None,
    caused_by: RecordEvent | None = None,
    visibility: str = RecordEvent.Visibility.PUBLIC,
) -> RecordEvent:
    """Append one event while serialising sequence allocation per history."""

    subject_field = SUBJECT_FIELD_BY_KIND[kind]
    if not record.history_id:
        raise ValueError("The exact record has no history.")
    if record.history.record_kind != kind:
        raise ValueError("The exact record and history have different kinds.")
    if (actor is None) == (actor_system is None):
        raise ValueError("Specify exactly one account or system actor.")

    history = RecordHistory.objects.select_for_update().get(id=record.history_id)
    latest = history.events.aggregate(maximum=Max("sequence"))["maximum"] or 0
    actor_values = (
        {
            "actor_type": RecordEvent.ActorType.ACCOUNT,
            "actor_account": actor,
            "actor_system": None,
        }
        if actor is not None
        else {
            "actor_type": RecordEvent.ActorType.SYSTEM,
            "actor_account": None,
            "actor_system": actor_system,
        }
    )
    return RecordEvent.objects.create(
        history=history,
        sequence=latest + 1,
        action=action,
        note=note,
        details=details or {},
        event_schema_version="0.1",
        payload_snapshot=payload_snapshot,
        caused_by=caused_by,
        visibility=visibility,
        **actor_values,
        **{subject_field: record},
    )


@dataclass(frozen=True)
class HistoryEventView:
    sequence: int
    occurred_at: Any
    action: str
    action_label: str
    actor_label: str
    actor_detail: str
    note: str
    details: dict[str, Any]
    details_json: str
    snapshot: dict[str, Any] | None
    snapshot_json: str | None
    record_label: str
    record_url: str | None
    predecessor_url: str | None
    predecessor_label: str | None
    caused_by_sequence: int | None


@dataclass(frozen=True)
class HistoryView:
    history_id: str
    record_kind: str
    events: tuple[HistoryEventView, ...]
    revised_from_label: str | None
    revised_from_url: str | None
    revised_to_label: str | None
    revised_to_url: str | None


def history_view(kind: str, record, viewer=None) -> HistoryView:
    """Return the stable presentation model for one exact data page."""

    events = (
        RecordEvent.objects.filter(history_id=record.history_id)
        .select_related(
            "history",
            "actor_account",
            "caused_by",
            *SUBJECT_FIELD_BY_KIND.values(),
        )
        .order_by("sequence")
    )
    events = events.filter(_event_visibility_q(kind, viewer))

    predecessor = _predecessor(kind, record)
    successor = _successor(kind, record)
    return HistoryView(
        history_id=str(record.history_id),
        record_kind=kind,
        events=tuple(_event_view(event) for event in events),
        revised_from_label=_record_label(kind, predecessor) if predecessor else None,
        revised_from_url=_record_url(kind, predecessor) if predecessor else None,
        revised_to_label=_record_label(kind, successor) if successor else None,
        revised_to_url=_record_url(kind, successor) if successor else None,
    )


def current_publication_approval(record) -> RecordEvent | None:
    """Find the approval which caused the latest publication episode."""

    publication = (
        record.record_events.filter(action=RecordEvent.Action.PUBLISHED)
        .select_related("caused_by", "caused_by__actor_account")
        .order_by("-sequence")
        .first()
    )
    return publication.caused_by if publication else None


def _event_view(event: RecordEvent) -> HistoryEventView:
    kind = event.history.record_kind
    record = getattr(event, SUBJECT_FIELD_BY_KIND[kind])
    predecessor_id = event.details.get("predecessor_id")
    predecessor = _record_in_history(event, predecessor_id)
    actor_detail = (
        event.actor_system or "system"
        if event.actor_type == RecordEvent.ActorType.SYSTEM
        else "Account"
    )
    return HistoryEventView(
        sequence=event.sequence,
        occurred_at=event.occurred_at,
        action=event.action,
        action_label=event.get_action_display(),
        actor_label=event.actor_label,
        actor_detail=actor_detail,
        note=event.note,
        details=event.details,
        details_json=json.dumps(event.details, indent=2, sort_keys=True),
        snapshot=event.payload_snapshot,
        snapshot_json=(
            json.dumps(event.payload_snapshot, indent=2, sort_keys=True)
            if event.payload_snapshot
            else None
        ),
        record_label=_record_label(kind, record),
        record_url=_record_url(kind, record),
        predecessor_url=_record_url(kind, predecessor) if predecessor else None,
        predecessor_label=_record_label(kind, predecessor) if predecessor else None,
        caused_by_sequence=event.caused_by.sequence if event.caused_by else None,
    )


def _record_in_history(event, record_id):
    if not record_id:
        return None
    relation = SUBJECT_FIELD_BY_KIND[event.history.record_kind]
    model = event._meta.get_field(relation).remote_field.model
    return model.objects.filter(id=record_id, history_id=event.history_id).first()


def _predecessor(kind: str, record):
    field = {
        "decoder": "predecessor",
        "noise_model": "predecessor",
        "circuit": "predecessor",
        "machine": "predecessor",
        "result": "predecessor",
        "benchmark": "predecessor",
    }.get(kind)
    return getattr(record, field, None) if field else None


def _successor(kind: str, record):
    relation = {
        "decoder": "successor",
        "noise_model": "successor",
        "circuit": "successor",
        "machine": "successor",
        "result": "successor",
        "benchmark": "successor",
    }.get(kind)
    if not relation:
        return None
    try:
        value = getattr(record, relation)
    except (AttributeError, record.__class__.DoesNotExist):
        return None
    if hasattr(value, "filter"):
        return value.order_by("created_at", "id").first()
    return value


def _record_label(kind: str, record) -> str:
    if record is None:
        return ""
    if kind == "decoder":
        return f"{record.name} {record.version}"
    if kind == "result":
        return f"{record.decoder_version} on {record.circuit_revision}"
    if kind == "benchmark":
        return f"{record.name} {record.version}"
    return (
        getattr(record, "name", None)
        or getattr(record, "label", None)
        or getattr(record, "slug", str(record.id))
    )


def _record_url(kind: str, record) -> str | None:
    if record is None or getattr(record, "state", "published") not in {
        "published",
        "withdrawn",
    }:
        return None
    try:
        if kind == "decoder":
            return reverse("decoders:detail", args=[record.slug])
        if kind == "noise_model":
            return reverse("noise-models:detail", args=[record.slug])
        if kind == "circuit":
            return reverse("circuits:detail", args=[record.slug])
        if kind == "machine":
            return reverse("machines:detail", args=[record.slug])
        if kind == "result":
            return reverse("results:detail", args=[record.id])
        if kind == "benchmark":
            return reverse("benchmarks:detail", args=[record.slug])
        if kind == "tag":
            return reverse(
                "taxonomy:tag-detail",
                kwargs={"namespace": record.namespace, "slug": record.slug},
            )
    except NoReverseMatch:
        return None
    return None


def events_visible_to(viewer, record):
    """Expose the visibility predicate for bounded table prefetches."""

    return _event_visibility_q(record.history.record_kind, viewer)


def _event_visibility_q(kind: str, viewer) -> Q:
    """Authorise uploader-only notes against each event's exact subject."""

    if getattr(viewer, "is_admin", False):
        return Q()
    public = Q(visibility=RecordEvent.Visibility.PUBLIC)
    if not getattr(viewer, "is_authenticated", False):
        return public
    return public | Q(
        visibility=RecordEvent.Visibility.UPLOADER,
        **{f"{SUBJECT_FIELD_BY_KIND[kind]}__submitted_by_id": viewer.id},
    )
