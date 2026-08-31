"""Presentation-neutral cell data for public result tables."""

from urllib.parse import urlencode

from django.urls import NoReverseMatch, reverse

from registry.explorer import ColumnSpec
from registry.formatting import format_scientific_value
from registry.models import Result
from registry.result_query import FIELD_BY_NAME, annotate_result_metrics

RESULT_METRIC_COLUMNS = (
    ColumnSpec(
        "score_ler_upper_95_at_5pct_acceptance_v0_1",
        "LER upper 95% @ 5%",
        numeric=True,
        default_direction="asc",
        help_text="Evaluator 0.1 score definition; probability, lower is better",
    ),
    ColumnSpec(
        "t_1000_ns",
        "t₁₀₀₀ (ns)",
        numeric=True,
        default_direction="asc",
        help_text="Finite-burst time until the 1,000th correction; lower is better",
    ),
    ColumnSpec(
        "score_brier_loss_upper_95_v0_1",
        "Brier upper 95%",
        numeric=True,
        default_visible=False,
        default_direction="asc",
        help_text="Evaluator 0.1 Brier-loss upper bound; lower is better",
    ),
)

RESULT_METRIC_SORT_FIELDS = {
    column.key: FIELD_BY_NAME[column.key].orm_name for column in RESULT_METRIC_COLUMNS
}


def with_result_metrics(queryset):
    """Annotate the stable public comparison metrics onto a result queryset."""

    return annotate_result_metrics(queryset)


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
            f"{score.score_definition.name}: {format_scientific_value(score.value)} "
            f"{score.score_definition.unit}"
        ).rstrip()
        for score in sorted(
            result.scores.all(),
            key=lambda score: score.score_definition.display_order,
        )
    )
    ler = _metric_value(result, "score_ler_upper_95_at_5pct_acceptance_v0_1")
    brier = _metric_value(result, "score_brier_loss_upper_95_v0_1")
    try:
        result_url = reverse("results:detail", args=[result.id])
    except NoReverseMatch:
        result_url = None
    return {
        "result": {
            "key": "result",
            "value": f"{str(result.id)[:8]}…",
            "title": str(result.id),
            "url": result_url,
        },
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
            "url": (
                reverse("machines:detail", args=[result.machine.slug])
                if result.machine
                else None
            ),
        },
        "shots": {"key": "shots", "value": result.shots_total, "numeric": True},
        "score_ler_upper_95_at_5pct_acceptance_v0_1": {
            "key": "score_ler_upper_95_at_5pct_acceptance_v0_1",
            "value": _format_metric(ler, "probability"),
            "numeric": True,
        },
        "t_1000_ns": {
            "key": "t_1000_ns",
            "value": _format_metric(result.t_1000_ns, "ns"),
            "numeric": True,
        },
        "score_brier_loss_upper_95_v0_1": {
            "key": "score_brier_loss_upper_95_v0_1",
            "value": _format_metric(brier, "probability"),
            "numeric": True,
        },
        "scores": {"key": "scores", "value": scores},
        "reproduction": {
            "key": "reproduction",
            "value": result.get_reproduction_status_display(),
        },
        "published": {"key": "published", "value": result.published_at},
    }


def _metric_value(result, public_field_name):
    field = FIELD_BY_NAME[public_field_name]
    if hasattr(result, field.orm_name):
        return getattr(result, field.orm_name)
    for score in result.scores.all():
        definition = score.score_definition
        if (
            definition.key == field.score_key
            and definition.version == field.score_version
            and score.evaluator_version.version == field.evaluator_version
        ):
            return score.value
    return None


def _format_metric(value, unit):
    if value is None:
        return None
    return f"{format_scientific_value(value)} {unit}"
