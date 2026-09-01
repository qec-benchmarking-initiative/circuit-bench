from django.core.management.base import BaseCommand, CommandError

from registry.models import (
    BenchmarkAttempt,
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    RecordEvent,
    RecordHistory,
    Result,
    Tag,
)
from registry.services.histories import SNAPSHOT_ACTIONS, SUBJECT_FIELD_BY_KIND

MODEL_BY_KIND = {
    "decoder": DecoderVersion,
    "noise_model": NoiseModel,
    "circuit": CircuitRevision,
    "machine": Machine,
    "result": Result,
    "tag": Tag,
    "benchmark": BenchmarkRevision,
    "benchmark_attempt": BenchmarkAttempt,
    "evaluator": EvaluatorRelease,
}

PREDECESSOR_BY_KIND = {
    "decoder": "predecessor_id",
    "noise_model": "predecessor_id",
    "circuit": "predecessor_id",
    "machine": "predecessor_id",
    "result": "predecessor_id",
    "benchmark": "predecessor_id",
}

EXPECTED_CAUSE_ACTIONS = {
    RecordEvent.Action.REQUESTED_CHANGES: set(SNAPSHOT_ACTIONS),
    RecordEvent.Action.REJECTED: set(SNAPSHOT_ACTIONS),
    RecordEvent.Action.RESUBMITTED: set(SNAPSHOT_ACTIONS),
    RecordEvent.Action.APPROVED: set(SNAPSHOT_ACTIONS),
    RecordEvent.Action.PUBLISHED: {RecordEvent.Action.APPROVED},
    RecordEvent.Action.MERGED: {RecordEvent.Action.DEPRECATED},
}
REQUIRED_CAUSE_ACTIONS = {
    RecordEvent.Action.REQUESTED_CHANGES,
    RecordEvent.Action.REJECTED,
    RecordEvent.Action.APPROVED,
    RecordEvent.Action.PUBLISHED,
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

        predecessor_field = PREDECESSOR_BY_KIND.get(kind)
        if predecessor_field:
            self._validate_lineage(history, records, records_by_id, predecessor_field)
        for record in records:
            record_events = events_by_record[record.id]
            if not record_events:
                self._error(history, f"record {record.id} has no events")
                continue
            for event in record_events:
                self._validate_causation(
                    history,
                    event,
                    subject_field,
                    record_events,
                )
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
                        if event.action == RecordEvent.Action.REVISION_CREATED
                    ]
                    if not any(
                        event.details.get("predecessor_id") == str(predecessor_id)
                        for event in revision_events
                    ):
                        self._error(
                            history,
                            f"record {record.id} lacks its revision-created event",
                        )
                elif any(
                    event.action == RecordEvent.Action.REVISION_CREATED
                    for event in record_events
                ):
                    self._error(
                        history,
                        f"root record {record.id} has a revision-created event",
                    )
            self._validate_projection(history, record, record_events)

    def _validate_lineage(self, history, records, records_by_id, predecessor_field):
        roots = [record for record in records if not getattr(record, predecessor_field)]
        if len(roots) != 1:
            self._error(
                history, f"has {len(roots)} lineage roots; expected exactly one"
            )

        claimed_predecessors = {}
        for record in records:
            predecessor_id = getattr(record, predecessor_field)
            if predecessor_id is None:
                continue
            if predecessor_id == record.id:
                self._error(history, f"record {record.id} is its own predecessor")
            prior_claim = claimed_predecessors.get(predecessor_id)
            if prior_claim is not None:
                self._error(
                    history,
                    f"records {prior_claim} and {record.id} share one predecessor",
                )
            claimed_predecessors[predecessor_id] = record.id

        for record in records:
            visited = set()
            current = record
            while current is not None:
                if current.id in visited:
                    self._error(history, f"lineage cycle includes record {current.id}")
                    break
                visited.add(current.id)
                predecessor_id = getattr(current, predecessor_field)
                if predecessor_id is None:
                    break
                current = records_by_id.get(predecessor_id)
                if current is None:
                    break

    def _validate_actor(self, history, event):
        account_actor = (
            event.actor_type == RecordEvent.ActorType.ACCOUNT
            and event.actor_account_id is not None
            and event.actor_system is None
        )
        system_actor = (
            event.actor_type == RecordEvent.ActorType.SYSTEM
            and event.actor_account_id is None
            and bool(event.actor_system)
        )
        if not (account_actor or system_actor):
            self._error(history, f"event {event.id} has an invalid actor")

    def _validate_snapshot(self, history, event):
        if event.action not in {
            RecordEvent.Action.SUBMITTED,
            RecordEvent.Action.RESUBMITTED,
            RecordEvent.Action.EDITED,
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

    def _validate_causation(self, history, event, subject_field, record_events):
        cause = event.caused_by
        legacy_history = any(
            candidate.details.get("migration_inferred") for candidate in record_events
        )
        legacy_event = bool(
            event.details.get("migration_inferred")
            or (legacy_history and event.details.get("fixture"))
        )
        earlier_legacy_snapshot = any(
            candidate.sequence < event.sequence
            and candidate.action in SNAPSHOT_ACTIONS
            and candidate.details.get("legacy_payload_unavailable")
            for candidate in record_events
        )
        cause_required = event.action in REQUIRED_CAUSE_ACTIONS or (
            event.action == RecordEvent.Action.RESUBMITTED
            and event.details.get("previous_state") == "changes_requested"
        )
        if event.action == RecordEvent.Action.APPROVED and (
            legacy_event or earlier_legacy_snapshot
        ):
            cause_required = False
        if cause is None:
            if cause_required:
                self._error(
                    history,
                    f"{event.action} event {event.id} has no recorded cause",
                )
            return

        expected_actions = EXPECTED_CAUSE_ACTIONS.get(event.action)
        if expected_actions is None:
            self._error(
                history,
                f"event {event.id} has an unexpected cause for {event.action}",
            )
            return
        if cause.history_id != history.id:
            self._error(history, f"event {event.id} has a cause in another history")
            return
        if getattr(cause, f"{subject_field}_id") != getattr(
            event, f"{subject_field}_id"
        ):
            self._error(
                history,
                f"event {event.id} has a cause for another exact record",
            )
        if cause.sequence >= event.sequence:
            self._error(
                history,
                f"event {event.id} does not have an earlier cause",
            )
        if cause.action not in expected_actions:
            expected = ", ".join(sorted(expected_actions))
            self._error(
                history,
                (
                    f"event {event.id} has cause action {cause.action}; "
                    f"expected {expected}"
                ),
            )

        if event.action not in {
            RecordEvent.Action.REQUESTED_CHANGES,
            RecordEvent.Action.REJECTED,
            RecordEvent.Action.RESUBMITTED,
            RecordEvent.Action.APPROVED,
        }:
            return
        if cause.details.get("legacy_payload_unavailable"):
            return
        eligible_snapshots = [
            candidate
            for candidate in record_events
            if candidate.sequence < event.sequence
            and candidate.action in SNAPSHOT_ACTIONS
            and candidate.payload_snapshot is not None
        ]
        latest_snapshot = eligible_snapshots[-1] if eligible_snapshots else None
        if latest_snapshot is None:
            self._error(
                history,
                f"{event.action} event {event.id} has no earlier exact snapshot",
            )
        elif cause.id != latest_snapshot.id:
            self._error(
                history,
                (
                    f"{event.action} event {event.id} does not cite the latest "
                    "exact snapshot"
                ),
            )

    def _validate_projection(self, history, record, events):
        if not hasattr(record, "state"):
            return
        expected_state = None
        published_event = None
        withdrawn_event = None
        published_seen = False
        rejected_seen = False
        legacy_history = any(
            event.details.get("migration_inferred") for event in events
        )
        for event in events:
            migration_inferred = bool(
                event.details.get("migration_inferred")
                or (legacy_history and event.details.get("fixture"))
            )
            if rejected_seen:
                self._error(
                    history,
                    f"rejected record {record.id} has a later {event.action} event",
                )
            if event.action in {
                RecordEvent.Action.SUBMITTED,
                RecordEvent.Action.RESUBMITTED,
            }:
                if (
                    event.action == RecordEvent.Action.SUBMITTED
                    and expected_state is not None
                    and not migration_inferred
                ):
                    self._error(
                        history,
                        f"submission event {event.id} is not the initial submission",
                    )
                if (
                    event.action == RecordEvent.Action.RESUBMITTED
                    and event.details.get("previous_state")
                    and event.details["previous_state"] != "changes_requested"
                ):
                    self._error(
                        history,
                        f"resubmission event {event.id} has an invalid previous state",
                    )
                if (
                    event.action == RecordEvent.Action.RESUBMITTED
                    and event.details.get("previous_state")
                    and expected_state != "changes_requested"
                    and not migration_inferred
                ):
                    self._error(
                        history,
                        (
                            f"resubmission event {event.id} did not follow "
                            "requested changes"
                        ),
                    )
                expected_state = event.details.get("projected_state") or (
                    "pending_reapproval"
                    if event.action == RecordEvent.Action.RESUBMITTED
                    else "pending_review"
                )
            elif event.action == RecordEvent.Action.REQUESTED_CHANGES:
                if expected_state not in {"pending_review", "pending_reapproval"}:
                    self._error(
                        history,
                        (
                            f"changes-request event {event.id} did not follow a "
                            "review queue"
                        ),
                    )
                if not event.note.strip():
                    self._error(
                        history, f"changes-request event {event.id} has no note"
                    )
                if (
                    event.details.get("previous_state")
                    and event.details["previous_state"] != expected_state
                    and not migration_inferred
                ):
                    self._error(
                        history,
                        f"changes-request event {event.id} has a stale previous state",
                    )
                expected_state = "changes_requested"
            elif event.action == RecordEvent.Action.REJECTED:
                if expected_state not in {"pending_review", "pending_reapproval"}:
                    self._error(
                        history,
                        f"rejection event {event.id} did not follow a review queue",
                    )
                if not event.note.strip():
                    self._error(history, f"rejection event {event.id} has no note")
                if (
                    event.details.get("previous_state")
                    and event.details["previous_state"] != expected_state
                    and not migration_inferred
                ):
                    self._error(
                        history,
                        f"rejection event {event.id} has a stale previous state",
                    )
                expected_state = "rejected"
                rejected_seen = True
            elif event.action == RecordEvent.Action.APPROVED:
                if (
                    expected_state
                    not in {"pending_review", "pending_reapproval", "published"}
                    and not migration_inferred
                ):
                    self._error(
                        history,
                        f"approval event {event.id} did not follow a review queue",
                    )
            elif event.action == RecordEvent.Action.PUBLISHED:
                expected_state = "published"
                published_event = event
                withdrawn_event = None
                published_seen = True
            elif event.action == RecordEvent.Action.WITHDRAWN:
                if expected_state != "published" and not migration_inferred:
                    self._error(
                        history,
                        f"withdrawal event {event.id} did not follow publication",
                    )
                expected_state = "withdrawn"
                withdrawn_event = event
            elif event.action == RecordEvent.Action.RESTORED:
                if expected_state != "withdrawn" and not migration_inferred:
                    self._error(
                        history,
                        f"restoration event {event.id} did not follow withdrawal",
                    )
                expected_state = "published"
                withdrawn_event = None
            elif event.action == RecordEvent.Action.EDITED:
                if published_seen:
                    self._error(
                        history, f"published record {record.id} was edited in place"
                    )
                elif (
                    expected_state
                    not in {"pending_review", "pending_reapproval", "changes_requested"}
                    and not migration_inferred
                ):
                    self._error(
                        history,
                        f"edit event {event.id} did not follow an editable state",
                    )
                event_state = event.details.get("state")
                if (
                    event_state
                    and event_state != expected_state
                    and not migration_inferred
                ):
                    self._error(
                        history, f"edit event {event.id} has a stale projected state"
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
