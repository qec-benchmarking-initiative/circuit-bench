"""Database-backed option and distribution data for reusable filter grids."""

from django.db.models import Q

from registry.models import Tag
from registry.services.circuits import circuit_catalogue
from registry.services.tags import active_tag_queryset


def public_circuit_filter_options() -> dict[str, object]:
    tags = list(
        active_tag_queryset()
        .filter(namespace__in=[Tag.Namespace.CODE, Tag.Namespace.EXPERIMENT])
        .filter(
            Q(status=Tag.Status.OFFICIAL)
            | Q(code_circuit_revisions__state="published")
            | Q(experiment_circuit_revisions__state="published")
        )
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
