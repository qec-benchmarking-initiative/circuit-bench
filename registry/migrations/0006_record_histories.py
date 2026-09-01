import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SYSTEM_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


RECORD_CONFIGS = (
    ("DecoderVersion", "decoder", "decoder_version", "previous_version_id"),
    ("NoiseModel", "noise_model", "noise_model", "supersedes_noise_model_id"),
    ("CircuitRevision", "circuit", "circuit_revision", "previous_revision_id"),
    ("Machine", "machine", "machine", "supersedes_machine_id"),
    ("Result", "result", "result", "supersedes_result_id"),
    ("Tag", "tag", "tag", None),
    ("BenchmarkRevision", "benchmark", "benchmark_revision", "previous_revision_id"),
    ("EvaluatorRelease", "evaluator", "evaluator_release", None),
)


def _components(rows, predecessor_field):
    identifiers = [row["id"] for row in rows]
    parent = {identifier: identifier for identifier in identifiers}

    def find(identifier):
        while parent[identifier] != identifier:
            parent[identifier] = parent[parent[identifier]]
            identifier = parent[identifier]
        return identifier

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[max(left_root, right_root, key=str)] = min(
                left_root, right_root, key=str
            )

    if predecessor_field:
        for row in rows:
            predecessor = row[predecessor_field]
            if predecessor in parent:
                union(row["id"], predecessor)
    grouped = {}
    for identifier in identifiers:
        grouped.setdefault(find(identifier), []).append(identifier)
    return grouped.values()


def _append_inferred_event(
    Event,
    *,
    history_id,
    sequence,
    subject_field,
    subject_id,
    action,
    note,
    occurred_at,
    actor_account_id=None,
    actor_system=None,
    details=None,
    snapshot=None,
):
    values = {
        "history_id": history_id,
        "sequence": sequence,
        "action": action,
        "note": note,
        "details": details or {"migration_inferred": True},
        "event_schema_version": "0.1",
        "payload_snapshot": snapshot,
        "visibility": "public",
        subject_field + "_id": subject_id,
    }
    if actor_account_id:
        values.update(
            actor_type="account",
            actor_account_id=actor_account_id,
            actor_system=None,
        )
    else:
        values.update(
            actor_type="system",
            actor_account_id=None,
            actor_system=actor_system or "migration_backfill",
        )
    event = Event.objects.create(**values)
    Event.objects.filter(id=event.id).update(occurred_at=occurred_at)
    return event


def backfill_histories(apps, schema_editor):
    History = apps.get_model("registry", "RecordHistory")
    Event = apps.get_model("registry", "ModerationEvent")
    model_by_subject = {}

    for model_name, kind, subject_field, predecessor_field in RECORD_CONFIGS:
        model = apps.get_model("registry", model_name)
        model_by_subject[subject_field] = model
        value_fields = ["id"]
        if predecessor_field:
            value_fields.append(predecessor_field)
        rows = list(model.objects.order_by("id").values(*value_fields))
        for component in _components(rows, predecessor_field):
            history = History.objects.create(record_kind=kind)
            model.objects.filter(id__in=component).update(history_id=history.id)

    next_sequence = {}
    events = list(Event.objects.order_by("occurred_at", "id"))
    for event in events:
        subject_field = next(
            field
            for _model, _kind, field, _predecessor in RECORD_CONFIGS
            if getattr(event, field + "_id") is not None
        )
        subject_id = getattr(event, subject_field + "_id")
        history_id = (
            model_by_subject[subject_field]
            .objects.values_list("history_id", flat=True)
            .get(id=subject_id)
        )
        sequence = next_sequence.get(history_id, 0) + 1
        next_sequence[history_id] = sequence
        values = {
            "history_id": history_id,
            "sequence": sequence,
            "actor_type": "account",
            "details": {**event.details, "migration_inferred": True},
        }
        if event.action in {"submitted", "edited", "resubmitted"}:
            values["details"] = {
                **values["details"],
                "legacy_payload_unavailable": True,
            }
        if event.actor_account_id == SYSTEM_ACCOUNT_ID:
            values.update(
                actor_type="system",
                actor_account_id=None,
                actor_system="submission_policy",
            )
        Event.objects.filter(id=event.id).update(**values)

    for model_name, kind, subject_field, predecessor_field in RECORD_CONFIGS:
        model = apps.get_model("registry", model_name)
        records = model.objects.order_by("created_at", "id")
        for record in records:
            history_id = record.history_id
            sequence = next_sequence.get(history_id, 0)
            subject_events = Event.objects.filter(**{subject_field + "_id": record.id})
            existing_actions = set(subject_events.values_list("action", flat=True))
            predecessor_id = (
                getattr(record, predecessor_field) if predecessor_field else None
            )
            if predecessor_id and "revision_created" not in existing_actions:
                sequence += 1
                _append_inferred_event(
                    Event,
                    history_id=history_id,
                    sequence=sequence,
                    subject_field=subject_field,
                    subject_id=record.id,
                    action="revision_created",
                    note="Revision relationship migrated from the typed record.",
                    occurred_at=record.created_at,
                    actor_account_id=getattr(record, "submitted_by_id", None),
                    details={
                        "migration_inferred": True,
                        "predecessor_id": str(predecessor_id),
                    },
                )
            if not existing_actions.intersection({"submitted", "resubmitted"}):
                sequence += 1
                schema_release_id = getattr(record, "schema_release_id", None)
                snapshot = {
                    "schema": {"record_type": kind, "version": "0.1"},
                    "data": {
                        "record_id": str(record.id),
                        "schema_release_id": (
                            str(schema_release_id) if schema_release_id else None
                        ),
                        "migration_inferred": True,
                    },
                }
                _append_inferred_event(
                    Event,
                    history_id=history_id,
                    sequence=sequence,
                    subject_field=subject_field,
                    subject_id=record.id,
                    action="submitted",
                    note="Submission event synthesised during history migration.",
                    occurred_at=record.created_at,
                    actor_account_id=getattr(record, "submitted_by_id", None),
                    details={
                        "migration_inferred": True,
                        "projected_state": getattr(record, "state", None),
                    },
                    snapshot=snapshot,
                )

            state = getattr(record, "state", None)
            if (
                state in {"published", "withdrawn"}
                and "published" not in existing_actions
            ):
                published_at = (
                    getattr(record, "published_at", None) or record.created_at
                )
                sequence += 1
                approval = _append_inferred_event(
                    Event,
                    history_id=history_id,
                    sequence=sequence,
                    subject_field=subject_field,
                    subject_id=record.id,
                    action="approved",
                    note="Historical approval actor was not recorded.",
                    occurred_at=published_at,
                    actor_system="migration_backfill",
                    details={
                        "migration_inferred": True,
                        "approval_route": "legacy_unknown",
                    },
                )
                sequence += 1
                published = _append_inferred_event(
                    Event,
                    history_id=history_id,
                    sequence=sequence,
                    subject_field=subject_field,
                    subject_id=record.id,
                    action="published",
                    note="Publication event synthesised from the lifecycle projection.",
                    occurred_at=published_at,
                    actor_system="migration_backfill",
                    details={"migration_inferred": True},
                )
                Event.objects.filter(id=published.id).update(caused_by_id=approval.id)
            if state == "withdrawn" and "withdrawn" not in existing_actions:
                sequence += 1
                _append_inferred_event(
                    Event,
                    history_id=history_id,
                    sequence=sequence,
                    subject_field=subject_field,
                    subject_id=record.id,
                    action="withdrawn",
                    note="Withdrawal event synthesised from the lifecycle projection.",
                    occurred_at=record.withdrawn_at,
                    actor_system="migration_backfill",
                    details={"migration_inferred": True},
                )
            next_sequence[history_id] = sequence


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        (
            "registry",
            "0005_remove_benchmarkattempt_registry_benchmarkattempt_lifecycle_timestamps_and_more",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RecordHistory",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "record_kind",
                    models.CharField(
                        choices=[
                            ("decoder", "Decoder version"),
                            ("noise_model", "Noise model"),
                            ("circuit", "Circuit revision"),
                            ("machine", "Machine"),
                            ("result", "Result"),
                            ("tag", "Tag"),
                            ("benchmark", "Benchmark revision"),
                            ("evaluator", "Evaluator release"),
                        ],
                        max_length=30,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "record_history"},
        ),
        *[
            migrations.AddField(
                model_name=model_name.lower(),
                name="history",
                field=models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name=related_name,
                    to="registry.recordhistory",
                ),
            )
            for model_name, related_name in (
                ("DecoderVersion", "decoder_versions"),
                ("NoiseModel", "noise_models"),
                ("CircuitRevision", "circuit_revisions"),
                ("Machine", "machines"),
                ("Result", "results"),
                ("Tag", "tags"),
                ("BenchmarkRevision", "benchmark_revisions"),
                ("EvaluatorRelease", "evaluator_releases"),
            )
        ],
        migrations.RenameField(
            model_name="moderationevent",
            old_name="created_at",
            new_name="occurred_at",
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="history",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="registry.recordhistory",
            ),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="sequence",
            field=models.PositiveIntegerField(null=True),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="actor_type",
            field=models.CharField(
                choices=[("account", "Account"), ("system", "System")],
                max_length=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="actor_system",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="event_schema_version",
            field=models.CharField(default="0.1", max_length=20),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="payload_snapshot",
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="caused_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="consequences",
                to="registry.moderationevent",
            ),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("uploader", "Uploader and administrators"),
                    ("admin", "Administrators only"),
                ],
                default="public",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="moderationevent",
            name="actor_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="moderation_events",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="moderationevent",
            name="action",
            field=models.CharField(
                choices=[
                    ("submitted", "Submitted"),
                    ("edited", "Edited"),
                    ("resubmitted", "Resubmitted"),
                    ("requested_changes", "Requested changes"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                    ("published", "Published"),
                    ("withdrawn", "Withdrawn"),
                    ("restored", "Restored"),
                    ("revision_created", "Revision created"),
                    ("promoted_official", "Promoted official"),
                    ("deprecated", "Deprecated"),
                    ("merged", "Merged"),
                    (
                        "admin_credit_claim_override",
                        "Admin credit claim override",
                    ),
                ],
                max_length=40,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="moderationevent",
            name="moderation_event_action_valid",
        ),
        migrations.RunPython(backfill_histories, migrations.RunPython.noop),
        *[
            migrations.AlterField(
                model_name=model_name.lower(),
                name="history",
                field=models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name=related_name,
                    to="registry.recordhistory",
                ),
            )
            for model_name, related_name in (
                ("DecoderVersion", "decoder_versions"),
                ("NoiseModel", "noise_models"),
                ("CircuitRevision", "circuit_revisions"),
                ("Machine", "machines"),
                ("Result", "results"),
                ("Tag", "tags"),
                ("BenchmarkRevision", "benchmark_revisions"),
                ("EvaluatorRelease", "evaluator_releases"),
            )
        ],
        migrations.AlterField(
            model_name="moderationevent",
            name="history",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="registry.recordhistory",
            ),
        ),
        migrations.AlterField(
            model_name="moderationevent",
            name="sequence",
            field=models.PositiveIntegerField(),
        ),
        migrations.AlterField(
            model_name="moderationevent",
            name="actor_type",
            field=models.CharField(
                choices=[("account", "Account"), ("system", "System")],
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="recordhistory",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    record_kind__in=[
                        "decoder",
                        "noise_model",
                        "circuit",
                        "machine",
                        "result",
                        "tag",
                        "benchmark",
                        "evaluator",
                    ]
                ),
                name="record_history_kind_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="moderationevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    action__in=[
                        "submitted",
                        "edited",
                        "resubmitted",
                        "requested_changes",
                        "approved",
                        "rejected",
                        "published",
                        "withdrawn",
                        "restored",
                        "revision_created",
                        "promoted_official",
                        "deprecated",
                        "merged",
                        "admin_credit_claim_override",
                    ]
                ),
                name="moderation_event_action_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="moderationevent",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        actor_type="account",
                        actor_account__isnull=False,
                        actor_system__isnull=True,
                    )
                    | models.Q(
                        actor_type="system",
                        actor_account__isnull=True,
                        actor_system__isnull=False,
                    )
                ),
                name="moderation_event_actor_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="moderationevent",
            constraint=models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="moderation_event_sequence_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="moderationevent",
            constraint=models.UniqueConstraint(
                fields=("history", "sequence"),
                name="moderation_event_history_sequence_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="moderationevent",
            index=models.Index(
                fields=["history", "occurred_at"], name="idx_event_history_time"
            ),
        ),
        migrations.AddIndex(
            model_name="moderationevent",
            index=models.Index(
                fields=["action", "occurred_at"], name="idx_event_action_time"
            ),
        ),
        migrations.AddIndex(
            model_name="moderationevent",
            index=models.Index(
                fields=["actor_account"], name="idx_event_actor_account"
            ),
        ),
    ]
