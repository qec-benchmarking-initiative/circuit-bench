"""Presentation-neutral cell data for public result tables."""

from urllib.parse import urlencode

from django.urls import reverse

from registry.models import Result


def result_cell_map(
    result: Result,
    *,
    filter_url: str,
    algorithm_tag_name: str = "algorithm_tag",
) -> dict[str, dict[str, object]]:
    decoder = result.decoder_version
    circuit = result.circuit_revision
    scores = "; ".join(
        (
            f"{score.score_definition.name}: {score.value} "
            f"{score.score_definition.unit}"
        ).rstrip()
        for score in sorted(
            result.scores.all(),
            key=lambda score: score.score_definition.display_order,
        )
    )
    return {
        "result": {"key": "result", "value": str(result.id)},
        "decoder": {
            "key": "decoder",
            "value": decoder.name,
            "url": reverse("decoders:detail", args=[decoder.slug]),
        },
        "version": {"key": "version", "value": decoder.version},
        "algorithm_tags": {
            "key": "algorithm_tags",
            "tags": [
                {
                    "label": tag.label,
                    "display_color": tag.display_color,
                    "url": f"{filter_url}?{urlencode({algorithm_tag_name: tag.slug})}",
                }
                for tag in decoder.display_algorithm_tags
            ],
        },
        "circuit": {
            "key": "circuit",
            "value": circuit.name,
            "url": reverse("circuits:detail", args=[circuit.slug]),
        },
        "code_tags": {
            "key": "code_tags",
            "tags": [
                {
                    "label": tag.label,
                    "display_color": tag.display_color,
                    "url": f"{filter_url}?{urlencode({'code_tag': tag.slug})}",
                }
                for tag in circuit.display_code_tags
            ],
        },
        "experiment_tags": {
            "key": "experiment_tags",
            "tags": [
                {
                    "label": tag.label,
                    "display_color": tag.display_color,
                    "url": f"{filter_url}?{urlencode({'experiment_tag': tag.slug})}",
                }
                for tag in circuit.display_experiment_tags
            ],
        },
        "noise_model": {
            "key": "noise_model",
            "value": circuit.noise_model.name,
            "url": reverse("noise-models:detail", args=[circuit.noise_model.slug]),
        },
        "machine_class": {
            "key": "machine_class",
            "value": (
                result.machine.get_machine_class_display()
                if result.machine
                else "Unreported"
            ),
        },
        "machine": {
            "key": "machine",
            "value": result.machine.slug if result.machine else None,
        },
        "shots": {"key": "shots", "value": result.shots_total, "numeric": True},
        "scores": {"key": "scores", "value": scores},
        "reproduction": {
            "key": "reproduction",
            "value": result.get_reproduction_status_display(),
        },
        "published": {"key": "published", "value": result.published_at},
    }
