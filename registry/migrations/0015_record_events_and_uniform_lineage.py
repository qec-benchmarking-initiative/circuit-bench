import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


LINEAGE_MODELS = (
    "DecoderVersion",
    "NoiseModel",
    "CircuitRevision",
    "Machine",
    "Result",
    "BenchmarkRevision",
)

RECORD_EVENT_SUBJECT_FIELDS = (
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


def assert_linear_lineages(apps, schema_editor):
    """Refuse the uniqueness change rather than silently discarding a branch."""

    for model_name in LINEAGE_MODELS:
        model = apps.get_model("registry", model_name)
        rows = list(model.objects.values_list("id", "history_id", "predecessor_id"))
        by_id = {row_id: (history_id, predecessor_id) for row_id, history_id, predecessor_id in rows}
        claimed = set()
        for row_id, history_id, predecessor_id in rows:
            if predecessor_id is None:
                continue
            if predecessor_id == row_id:
                raise RuntimeError(f"{model_name} {row_id} is its own predecessor")
            predecessor = by_id.get(predecessor_id)
            if predecessor is None or predecessor[0] != history_id:
                raise RuntimeError(
                    f"{model_name} {row_id} has a predecessor outside its history"
                )
            if predecessor_id in claimed:
                raise RuntimeError(
                    f"{model_name} lineage branches at predecessor {predecessor_id}"
                )
            claimed.add(predecessor_id)

        for row_id, _history_id, _predecessor_id in rows:
            visited = set()
            current_id = row_id
            while current_id is not None:
                if current_id in visited:
                    raise RuntimeError(f"{model_name} lineage contains a cycle")
                visited.add(current_id)
                current = by_id.get(current_id)
                current_id = current[1] if current is not None else None


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0014_credit_account_uniqueness"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(
            old_name="ModerationEvent",
            new_name="RecordEvent",
        ),
        migrations.AlterModelTable(
            name="recordevent",
            table="record_event",
        ),
        migrations.RemoveConstraint(
            model_name="recordevent",
            name="moderation_event_action_valid",
        ),
        migrations.RemoveConstraint(
            model_name="recordevent",
            name="moderation_event_one_subject",
        ),
        migrations.RemoveConstraint(
            model_name="recordevent",
            name="moderation_event_actor_valid",
        ),
        migrations.RemoveConstraint(
            model_name="recordevent",
            name="moderation_event_sequence_positive",
        ),
        migrations.RemoveConstraint(
            model_name="recordevent",
            name="moderation_event_history_sequence_uniq",
        ),
        migrations.RemoveConstraint(
            model_name="benchmarkrevision",
            name="benchmark_revision_previous_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="circuitrevision",
            name="circuit_revision_previous_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="decoderversion",
            name="decoder_version_previous_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="machine",
            name="machine_supersedes_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="noisemodel",
            name="noise_model_supersedes_not_self",
        ),
        migrations.RemoveConstraint(
            model_name="result",
            name="result_supersedes_not_self",
        ),
        migrations.RemoveIndex(
            model_name="result",
            name="idx_result_supersedes",
        ),
        migrations.RenameField(
            model_name="benchmarkrevision",
            old_name="previous_revision",
            new_name="predecessor",
        ),
        migrations.RenameField(
            model_name="circuitrevision",
            old_name="previous_revision",
            new_name="predecessor",
        ),
        migrations.RenameField(
            model_name="decoderversion",
            old_name="previous_version",
            new_name="predecessor",
        ),
        migrations.RenameField(
            model_name="machine",
            old_name="supersedes_machine",
            new_name="predecessor",
        ),
        migrations.RenameField(
            model_name="noisemodel",
            old_name="supersedes_noise_model",
            new_name="predecessor",
        ),
        migrations.RenameField(
            model_name="result",
            old_name="supersedes_result",
            new_name="predecessor",
        ),
        migrations.RunPython(assert_linear_lineages, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="benchmarkrevision",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="registry.benchmarkrevision",
            ),
        ),
        migrations.AlterField(
            model_name="circuitrevision",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="registry.circuitrevision",
            ),
        ),
        migrations.AlterField(
            model_name="decoderversion",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="registry.decoderversion",
            ),
        ),
        migrations.AlterField(
            model_name="machine",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="registry.machine",
            ),
        ),
        migrations.AlterField(
            model_name="noisemodel",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="registry.noisemodel",
            ),
        ),
        migrations.AlterField(
            model_name="result",
            name="predecessor",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="successor",
                to="registry.result",
            ),
        ),
        migrations.AlterField(
            model_name="recordevent",
            name="actor_account",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="record_events",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        *[
            migrations.AlterField(
                model_name="recordevent",
                name=field_name,
                field=models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="record_events",
                    to=f"registry.{target}",
                ),
            )
            for field_name, target in (
                ("decoder_version", "decoderversion"),
                ("noise_model", "noisemodel"),
                ("circuit_revision", "circuitrevision"),
                ("machine", "machine"),
                ("result", "result"),
                ("tag", "tag"),
                ("benchmark_revision", "benchmarkrevision"),
                ("benchmark_attempt", "benchmarkattempt"),
                ("evaluator_release", "evaluatorrelease"),
            )
        ],
        migrations.AddIndex(
            model_name="result",
            index=models.Index(
                fields=["predecessor"],
                condition=models.Q(predecessor__isnull=False),
                name="idx_result_predecessor",
            ),
        ),
        *[
            migrations.AddConstraint(
                model_name=model_name,
                constraint=models.CheckConstraint(
                    condition=(
                        models.Q(predecessor__isnull=True)
                        | ~models.Q(predecessor=models.F("id"))
                    ),
                    name=constraint_name,
                ),
            )
            for model_name, constraint_name in (
                ("benchmarkrevision", "benchmark_revision_predecessor_not_self"),
                ("circuitrevision", "circuit_revision_predecessor_not_self"),
                ("decoderversion", "decoder_version_predecessor_not_self"),
                ("machine", "machine_predecessor_not_self"),
                ("noisemodel", "noise_model_predecessor_not_self"),
                ("result", "result_predecessor_not_self"),
            )
        ],
        migrations.AddConstraint(
            model_name="recordevent",
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
                name="record_event_action_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordevent",
            constraint=models.CheckConstraint(
                condition=_exactly_one_not_null(*RECORD_EVENT_SUBJECT_FIELDS),
                name="record_event_one_subject",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordevent",
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
                name="record_event_actor_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordevent",
            constraint=models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="record_event_sequence_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordevent",
            constraint=models.UniqueConstraint(
                fields=["history", "sequence"],
                name="record_event_history_sequence_uniq",
            ),
        ),
    ]
