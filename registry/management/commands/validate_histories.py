from django.core.management.base import BaseCommand, CommandError

from registry.models import (
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    ModerationEvent,
    NoiseModel,
    RecordHistory,
    Result,
    Tag,
)
from registry.services.histories import SUBJECT_FIELD_BY_KIND

MODEL_BY_KIND = {
    "decoder": DecoderVersion,
    "noise_model": NoiseModel,
    "circuit": CircuitRevision,
    "machine": Machine,
    "result": Result,
    "tag": Tag,
    "benchmark": BenchmarkRevision,
    "evaluator": EvaluatorRelease,
}

PREDECESSOR_BY_KIND = {
    "decoder": "previous_version_id",
    "noise_model": "supersedes_noise_model_id",
    "circuit": "previous_revision_id",
    "machine": "supersedes_machine_id",
    "result": "supersedes_result_id",
    "benchmark": "previous_revision_id",
}


class BaseHistoryValidator:
    def __init__(self):
        self.errors: list[str] = []

    def validate(self):
        for history in RecordHistory.objects.order_by("id"):
            self._validate_history(history)
        return self.errors

    def _validate_history(self, history):
        kind = history.record_kind
        model = MODEL_BY_KIND[kind]
        subject_field = SUBJECT_FIELD_BY_KIND[kind]
        records = list(
            model.objects.filter(history=history).order_by("created_at", "id")
        )
        if not records:
            self._error(history, "has no exact records")
            return

        events = list(history.events.select_related("caused_by").order_by("sequence"))
        sequences = [event.sequence for event in events]
        if sequences != list(range(1, len(events) + 1)):
            self._error(history, f"has non-continuous sequences {sequences}")

        records_by_id = {record.id: record for record in records}
        events_by_record = {record.id: [] for record in records}
        for event in events:
            subject = getattr(event, subject_field)
            if subject is None or subject.id not in records_by_id:
                self._error(
                    history,
                    f"event {event.id} points outside its exact-record history",
                )
                continue
            events_by_record[subject.id].append(event)
            self._validate_actor(history, event)
            self._validate_snapshot(history, event)
            if event.action == ModerationEvent.Action.PUBLISHED:
                if (
                    event.caused_by is None
                    or event.caused_by.action != ModerationEvent.Action.APPROVED
                    or event.caused_by.history_id != history.id
                ):
                    self._error(
                        history,
                        f"publication event {event.id} has no approval cause",
                    )

        predecessor_field = PREDECESSOR_BY_KIND.get(kind)
        for record in records:
            record_events = events_by_record[record.id]
            if not record_events:
                self._error(history, f"record {record.id} has no events")
                continue
            if predecessor_field:
                predecessor_id = getattr(record, predecessor_field)
                if predecessor_id:
                    if predecessor_id not in records_by_id:
                        self._error(
                            history,
                            f"record {record.id} has a predecessor in another history",
                        )
                    revision_events = [
                        event
                        for event in record_events
                        if event.action == ModerationEvent.Action.REVISION_CREATED
                    ]
                    if not any(
                        event.details.get("predecessor_id") == str(predecessor_id)
                        for event in revision_events
                    ):
                        self._error(
                            history,
                            f"record {record.id} lacks its revision-created event",
                        )
            self._validate_projection(history, record, record_events)

    def _validate_actor(self, history, event):
        account_actor = (
            event.actor_type == ModerationEvent.ActorType.ACCOUNT
            and event.actor_account_id is not None
            and event.actor_system is None
        )
        system_actor = (
            event.actor_type == ModerationEvent.ActorType.SYSTEM
            and event.actor_account_id is None
            and bool(event.actor_system)
        )
        if not (account_actor or system_actor):
            self._error(history, f"event {event.id} has an invalid actor")

    def _validate_snapshot(self, history, event):
        if event.action not in {
            ModerationEvent.Action.SUBMITTED,
            ModerationEvent.Action.RESUBMITTED,
            ModerationEvent.Action.EDITED,
        }:
            return
        if event.payload_snapshot is None:
            if event.details.get("legacy_payload_unavailable"):
                return
            self._error(history, f"event {event.id} has no payload snapshot")
            return
        schema = event.payload_snapshot.get("schema", {})
        if schema.get("record_type") != history.record_kind or not schema.get(
            "version"
        ):
            self._error(history, f"event {event.id} has an invalid snapshot schema")

    def _validate_projection(self, history, record, events):
        if not hasattr(record, "state"):
            return
        expected_state = None
        published_event = None
        withdrawn_event = None
        published_seen = False
        for event in events:
            if event.action in {
                ModerationEvent.Action.SUBMITTED,
                ModerationEvent.Action.RESUBMITTED,
            }:
                expected_state = event.details.get("projected_state") or (
                    "pending_reapproval"
                    if event.action == ModerationEvent.Action.RESUBMITTED
                    else "pending_review"
                )
            elif event.action == ModerationEvent.Action.PUBLISHED:
                expected_state = "published"
                published_event = event
                withdrawn_event = None
                published_seen = True
            elif event.action == ModerationEvent.Action.WITHDRAWN:
                expected_state = "withdrawn"
                withdrawn_event = event
            elif event.action == ModerationEvent.Action.RESTORED:
                expected_state = "published"
                withdrawn_event = None
            elif event.action == ModerationEvent.Action.EDITED and published_seen:
                self._error(
                    history, f"published record {record.id} was edited in place"
                )

        if expected_state and record.state != expected_state:
            self._error(
                history,
                (
                    f"record {record.id} projects {record.state}, "
                    f"events project {expected_state}"
                ),
            )
        if published_event and not published_event.details.get("migration_inferred"):
            if record.published_at != published_event.occurred_at:
                self._error(history, f"record {record.id} has a stale published_at")
        if withdrawn_event and not withdrawn_event.details.get("migration_inferred"):
            if record.withdrawn_at != withdrawn_event.occurred_at:
                self._error(history, f"record {record.id} has a stale withdrawn_at")

    def _error(self, history, message):
        self.errors.append(f"{history.record_kind} history {history.id}: {message}")


class Command(BaseCommand):
    help = "Validate record histories, immutable events, and lifecycle projections"

    def handle(self, *args, **options):
        errors = BaseHistoryValidator().validate()
        if errors:
            preview = "\n".join(f"- {message}" for message in errors[:50])
            suffix = "" if len(errors) <= 50 else f"\n… {len(errors) - 50} more"
            raise CommandError(
                f"History validation failed with {len(errors)} error(s):\n"
                f"{preview}{suffix}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Validated {RecordHistory.objects.count()} record histories."
            )
        )
