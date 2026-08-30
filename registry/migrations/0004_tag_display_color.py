import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0003_cross_record_integrity"),
    ]

    operations = [
        migrations.AddField(
            model_name="tag",
            name="display_color",
            field=models.CharField(
                blank=True,
                help_text="Optional admin-selected colour for an official tag.",
                max_length=7,
                null=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Use a six-digit hexadecimal colour such as #315f7d."
                        ),
                        regex="^#[0-9A-Fa-f]{6}$",
                    )
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="tag",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("display_color__isnull", True))
                    | models.Q(("display_color__regex", "^#[0-9A-Fa-f]{6}$"))
                ),
                name="tag_display_color_hex",
            ),
        ),
    ]
