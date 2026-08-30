"""Database-backed option and distribution data for reusable filter grids."""

from django.db.models import Case, IntegerField, Q, Value, When

from registry.models import NoiseModel, Tag
from registry.services.circuits import circuit_catalogue


def public_circuit_filter_options() -> dict[str, object]:
    tags = list(
        Tag.objects.filter(
            namespace__in=[Tag.Namespace.CODE, Tag.Namespace.EXPERIMENT],
            status__in=[Tag.Status.OFFICIAL, Tag.Status.CUSTOM],
        )
        .filter(
            Q(status=Tag.Status.OFFICIAL)
            | Q(code_circuit_revisions__state="published")
            | Q(experiment_circuit_revisions__state="published")
        )
        .annotate(
            official_order=Case(
                When(status=Tag.Status.OFFICIAL, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("namespace", "official_order", "label")
        .distinct()
    )
    distribution_rows = list(
        circuit_catalogue().values(
            "code_distance_upper_bound",
            "circuit_distance_upper_bound",
            "num_detectors",
            "num_errors",
        )
    )
    return {
        "code_tags": [tag for tag in tags if tag.namespace == Tag.Namespace.CODE],
        "experiment_tags": [
            tag for tag in tags if tag.namespace == Tag.Namespace.EXPERIMENT
        ],
        "noise_models": list(
            NoiseModel.objects.filter(state="published").order_by("name")
        ),
        "distributions": {
            "code_distance": [
                row["code_distance_upper_bound"] for row in distribution_rows
            ],
            "circuit_distance": [
                row["circuit_distance_upper_bound"] for row in distribution_rows
            ],
            "detectors": [row["num_detectors"] for row in distribution_rows],
            "errors": [row["num_errors"] for row in distribution_rows],
        },
    }
