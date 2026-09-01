import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "machine",
    "result",
    "tag",
    "benchmark_revision",
    "benchmark_attempt",
    "evaluator_release",
)


def _exactly_one_not_null(*field_names):
    condition = models.Q(pk__isnull=True) & ~models.Q(pk__isnull=True)
    for selected in field_names:
        branch = models.Q(**{f"{selected}__isnull": False})
        for other in field_names:
            if other != selected:
                branch &= models.Q(**{f"{other}__isnull": True})
        condition |= branch
    return condition


def backfill_benchmark_attempt_histories(apps, schema_editor):
    BenchmarkAttempt = apps.get_model("registry", "BenchmarkAttempt")
    RecordHistory = apps.get_model("registry", "RecordHistory")
    ModerationEvent = apps.get_model("registry", "ModerationEvent")

    for attempt in BenchmarkAttempt.objects.filter(history__isnull=True).iterator():
        history = RecordHistory.objects.create(record_kind="benchmark_attempt")
        BenchmarkAttempt.objects.filter(id=attempt.id).update(history=history)
        submitted = ModerationEvent.objects.create(
            history=history,
            sequence=1,
            actor_type="account",
            actor_account_id=attempt.submitted_by_id,
            benchmark_attempt_id=attempt.id,
            action="submitted",
            note="Imported legacy benchmark attempt.",
            details={
                "migration_inferred": True,
                "legacy_payload_unavailable": True,
                "projected_state": (
                    "pending_review"
                    if attempt.state in {"published", "withdrawn"}
                    else attempt.state
                ),
            },
            event_schema_version="0.1",
            visibility="public",
        )
        ModerationEvent.objects.filter(id=submitted.id).update(
            occurred_at=attempt.created_at
        )
        if attempt.state not in {"published", "withdrawn"}:
            continue
        approved = ModerationEvent.objects.create(
            history=history,
            sequence=2,
            actor_type="system",
            actor_system="history_migration_0012",
            benchmark_attempt_id=attempt.id,
            action="approved",
            note="Inferred approval for a legacy published benchmark attempt.",
            details={"migration_inferred": True},
            event_schema_version="0.1",
            caused_by=submitted,
            visibility="public",
        )
        published = ModerationEvent.objects.create(
            history=history,
            sequence=3,
            actor_type="system",
            actor_system="history_migration_0012",
            benchmark_attempt_id=attempt.id,
            action="published",
            note="Inferred publication for a legacy benchmark attempt.",
            details={"migration_inferred": True},
            event_schema_version="0.1",
            caused_by=approved,
            visibility="public",
        )
        publication_time = attempt.published_at or attempt.created_at
        ModerationEvent.objects.filter(id__in=[approved.id, published.id]).update(
            occurred_at=publication_time
        )
        if attempt.state == "withdrawn":
            withdrawn = ModerationEvent.objects.create(
                history=history,
                sequence=4,
                actor_type="system",
                actor_system="history_migration_0012",
                benchmark_attempt_id=attempt.id,
                action="withdrawn",
                note="Inferred withdrawal for a legacy benchmark attempt.",
                details={"migration_inferred": True},
                event_schema_version="0.1",
                visibility="public",
            )
            ModerationEvent.objects.filter(id=withdrawn.id).update(
                occurred_at=attempt.withdrawn_at or publication_time
            )


def reverse_benchmark_attempt_histories(apps, schema_editor):
    BenchmarkAttempt = apps.get_model("registry", "BenchmarkAttempt")
    RecordHistory = apps.get_model("registry", "RecordHistory")
    history_ids = list(
        BenchmarkAttempt.objects.exclude(history__isnull=True).values_list(
            "history_id", flat=True
        )
    )
    BenchmarkAttempt.objects.update(history=None)
    RecordHistory.objects.filter(
        id__in=history_ids, record_kind="benchmark_attempt"
    ).delete()


class Migration(migrations.Migration):
    # PostgreSQL must commit the backfill writes before Django creates the
    # deferred FK indexes added by this same migration.
    atomic = False

    dependencies = [
        ("registry", "0011_update_result_reproduction_label"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="recordhistory",
            name="record_history_kind_valid",
        ),
        migrations.RemoveConstraint(
            model_name="moderationevent",
            name="moderation_event_one_subject",
        ),
        migrations.AlterField(
            model_name="recordhistory",
            name="record_kind",
            field=models.CharField(
                choices=[
                    ("decoder", "Decoder version"),
                    ("noise_model", "Noise model"),
                    ("circuit", "Circuit revision"),
                    ("machine", "Machine"),
                    ("result", "Result"),
                    ("tag", "Tag"),
                    ("benchmark", "Benchmark revision"),
                    ("benchmark_attempt", "Benchmark attempt"),
                    ("evaluator", "Evaluator release"),
                ],
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="benchmarkattempt",
            name="history",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="benchmark_attempts",
                to="registry.recordhistory",
            ),
        ),
        migrations.AddField(
            model_name="moderationevent",
            name="benchmark_attempt",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="moderation_events",
                to="registry.benchmarkattempt",
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
                        "benchmark_attempt",
                        "evaluator",
                    ]
                ),
                name="record_history_kind_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="moderationevent",
            constraint=models.CheckConstraint(
                condition=_exactly_one_not_null(*SUBJECT_FIELDS),
                name="moderation_event_one_subject",
            ),
        ),
        migrations.RunPython(
            backfill_benchmark_attempt_histories,
            reverse_benchmark_attempt_histories,
        ),
        migrations.AlterField(
            model_name="benchmarkattempt",
            name="history",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="benchmark_attempts",
                to="registry.recordhistory",
            ),
        ),
    ]
