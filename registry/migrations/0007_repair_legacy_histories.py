from django.db import migrations
from django.db.models import F

SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "machine",
    "result",
    "tag",
    "benchmark_revision",
    "evaluator_release",
)


def _merge_details(event, **extra):
    event.details = {**(event.details or {}), **extra}
    event.save(update_fields=["details"])


def _subject_filter(event):
    for field in SUBJECT_FIELDS:
        identifier = getattr(event, field + "_id")
        if identifier is not None:
            return {field + "_id": identifier}
    raise RuntimeError(f"Moderation event {event.id} has no subject")


def _resequence(Event, history_id, ordered_events):
    Event.objects.filter(history_id=history_id).update(
        sequence=F("sequence") + 1_000_000
    )
    for sequence, event in enumerate(ordered_events, start=1):
        Event.objects.filter(id=event.id).update(sequence=sequence)


def repair_legacy_histories(apps, schema_editor):
    Event = apps.get_model("registry", "ModerationEvent")

    for event in Event.objects.filter(
        action__in=("submitted", "edited", "resubmitted"),
        payload_snapshot__isnull=True,
    ):
        _merge_details(
            event,
            migration_inferred=True,
            legacy_payload_unavailable=True,
        )

    publications = list(
        Event.objects.filter(action="published")
        .select_related("history")
        .order_by("history_id", "sequence")
    )
    for publication in publications:
        if not publication.details.get("migration_inferred"):
            _merge_details(publication, migration_inferred=True)
        if publication.caused_by_id is not None:
            continue

        approvals = Event.objects.filter(
            history_id=publication.history_id,
            action="approved",
            **_subject_filter(publication),
        ).order_by("sequence")
        approval = approvals.filter(sequence__lt=publication.sequence).last()
        approval = approval or approvals.first()
        if approval is None:
            approval = Event.objects.create(
                history_id=publication.history_id,
                sequence=(
                    Event.objects.filter(history_id=publication.history_id)
                    .order_by("-sequence")
                    .values_list("sequence", flat=True)
                    .first()
                    or 0
                )
                + 1,
                actor_type="system",
                actor_account_id=None,
                actor_system="migration_backfill",
                action="approved",
                note="Historical approval was not recorded before migration.",
                details={
                    "migration_inferred": True,
                    "approval_route": "legacy_unknown",
                },
                event_schema_version="0.1",
                payload_snapshot=None,
                visibility="public",
                **_subject_filter(publication),
            )

        ordered = list(
            Event.objects.filter(history_id=publication.history_id).order_by("sequence")
        )
        if ordered.index(approval) > ordered.index(publication):
            ordered.remove(approval)
            ordered.insert(ordered.index(publication), approval)
            _resequence(Event, publication.history_id, ordered)
        Event.objects.filter(id=publication.id).update(caused_by_id=approval.id)


class Migration(migrations.Migration):
    dependencies = [("registry", "0006_record_histories")]

    operations = [
        migrations.RunPython(
            repair_legacy_histories,
            migrations.RunPython.noop,
        )
    ]
