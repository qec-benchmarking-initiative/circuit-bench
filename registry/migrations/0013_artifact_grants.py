import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_uploaded_by_grants(apps, schema_editor):
    Artifact = apps.get_model("registry", "Artifact")
    ArtifactGrant = apps.get_model("registry", "ArtifactGrant")
    database = schema_editor.connection.alias
    batch = []

    for artifact in (
        Artifact.objects.using(database)
        .only("id", "uploaded_by_id", "created_at")
        .iterator(chunk_size=1000)
    ):
        batch.append(
            ArtifactGrant(
                id=uuid.uuid4(),
                artifact_id=artifact.id,
                account_id=artifact.uploaded_by_id,
                acquired_at=artifact.created_at,
                source="legacy_uploader",
            )
        )
        if len(batch) == 1000:
            ArtifactGrant.objects.using(database).bulk_create(
                batch, ignore_conflicts=True
            )
            batch.clear()

    if batch:
        ArtifactGrant.objects.using(database).bulk_create(
            batch, ignore_conflicts=True
        )


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0012_benchmark_attempt_histories"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ArtifactGrant",
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
                ("acquired_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("upload", "Uploaded file"),
                            ("generated", "Generated file"),
                            ("legacy_uploader", "Legacy uploader backfill"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifact_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "artifact",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="access_grants",
                        to="registry.artifact",
                    ),
                ),
            ],
            options={"db_table": "artifact_grant"},
        ),
        migrations.AddConstraint(
            model_name="artifactgrant",
            constraint=models.UniqueConstraint(
                fields=("artifact", "account"),
                name="artifact_grant_artifact_account_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="artifactgrant",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    source__in=["upload", "generated", "legacy_uploader"]
                ),
                name="artifact_grant_source_valid",
            ),
        ),
        migrations.RunPython(
            backfill_uploaded_by_grants,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
