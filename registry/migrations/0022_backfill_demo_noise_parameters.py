"""Backfill only known synthetic fixtures, never infer real scientific metadata."""

import uuid

from django.db import migrations

NAMESPACE = uuid.UUID("f333b191-09a8-4631-8775-3cb6fc51426e")
CIRCUIT_KEYS = (
    "circuit/rotated-memory-d5",
    "circuit/rotated-memory-d3",
    "circuit/rotated-memory-d7",
    "circuit/rotated-memory-d9",
    "circuit/planar-stability-d5",
    "circuit/colour-memory-d5",
    "circuit/bicycle-memory-144",
    "circuit/surface-cnot-d3",
    "submission/circuit/rotated-memory-d7",
)


def backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Circuit = apps.get_model("registry", "CircuitRevision")
    # demo.py/demo_plotting.py freeze X_ERROR(0.001) in every seeded file;
    # demo_submissions.py reuses the same file. No real circuit is changed.
    Circuit.objects.using(alias).filter(
        id__in=[uuid.uuid5(NAMESPACE, key) for key in CIRCUIT_KEYS],
        noise_parameter__isnull=True,
    ).update(noise_parameter=0.001)
    NoiseModel = apps.get_model("registry", "NoiseModel")
    descriptions = {
        "fixed-phenomenological": (
            "Synthetic fixed-prior model. The noise parameter p is the dimensionless "
            "X_ERROR probability in [0, 1] in the demonstration circuit; "
            "it is not a percentage."
        ),
        "randomised-phenomenological": (
            "Synthetic randomised-prior placeholder. The noise parameter p is the "
            "nominal physical error probability in [0, 1], not a percentage. "
            "These demonstration files contain only X_ERROR(p); they do not "
            "implement a randomised distribution."
        ),
    }
    for slug, description in descriptions.items():
        NoiseModel.objects.using(alias).filter(
            id=uuid.uuid5(NAMESPACE, f"noise/{slug}"),
        ).update(short_description=description)


class Migration(migrations.Migration):
    dependencies = [("registry", "0021_circuit_noise_parameter")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
