from django.db import migrations, models


SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "result",
    "benchmark_revision",
)


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0013_artifact_grants"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="credit",
            constraint=models.UniqueConstraint(
                fields=(subject, "account"),
                condition=(
                    models.Q(**{f"{subject}__isnull": False})
                    & models.Q(account__isnull=False)
                    & models.Q(hidden_at__isnull=True)
                ),
                name=f"credit_{subject}_visible_account_uniq",
            ),
        )
        for subject in SUBJECT_FIELDS
    ]
