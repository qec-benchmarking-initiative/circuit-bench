"""Pure plot declarations over an exact caller-supplied ResultRecord page."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.urls import NoReverseMatch, reverse

from registry.formatting import format_scientific_value
from registry.models import Result
from registry.result_query import (
    FIELD_BY_NAME,
    RESULT_RECORD_SCHEMA_VERSION,
    ResultField,
    result_record,
)

DEFAULT_X_FIELD = "t_1000_ns"
DEFAULT_Y_FIELD = "score_ler_upper_95_at_5pct_acceptance_v0_1"
NUMERIC_FIELD_KINDS = {"integer", "decimal"}
PLOT_SCALES = {"linear", "log"}
POINT_CONTEXTS = {"results", "circuit", "decoder", "machine", "benchmark"}

VIEWBOX_WIDTH = Decimal(800)
VIEWBOX_HEIGHT = Decimal(440)
PLOT_LEFT = Decimal(92)
PLOT_RIGHT = Decimal(24)
PLOT_TOP = Decimal(20)
PLOT_BOTTOM = Decimal(76)
PLOT_WIDTH = VIEWBOX_WIDTH - PLOT_LEFT - PLOT_RIGHT
PLOT_HEIGHT = VIEWBOX_HEIGHT - PLOT_TOP - PLOT_BOTTOM
TICK_INTERVALS = 4


class PlotDeclarationError(ValueError):
    """A stable, user-facing failure to declare a scientific plot."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def build_result_scatter_plot(
    results: Sequence[Result],
    *,
    x_field: str = DEFAULT_X_FIELD,
    y_field: str = DEFAULT_Y_FIELD,
    x_scale: str = "linear",
    y_scale: str = "linear",
    plot_id: str = "result-scatter",
    point_context: str = "results",
    title: str | None = None,
) -> dict[str, object]:
    """Describe one scatter plot without selecting any database rows.

    ``results`` must be the already parsed, ordered, and paged population used
    by the caller's table.  In particular, evaluator metric annotations must
    already be present (as they are after ``execute_result_query``).  This
    function deliberately performs no ORM query and preserves supplied order.
    """

    x_definition = _numeric_field(x_field, axis="x")
    y_definition = _numeric_field(y_field, axis="y")
    _validate_scale(x_scale, axis="x")
    _validate_scale(y_scale, axis="y")
    if point_context not in POINT_CONTEXTS:
        raise PlotDeclarationError(
            "invalid_point_context", f"Unknown plot point context: {point_context}"
        )
    if isinstance(results, QuerySet):
        raise PlotDeclarationError(
            "unmaterialized_population",
            "Pass the exact materialized result page, not a QuerySet, to the plot.",
        )
    population = list(results)
    plotted_values: list[tuple[Result, Decimal, Decimal]] = []
    null_omissions = 0
    log_omissions = 0

    for result in population:
        try:
            record = result_record(result, (x_field, y_field))
        except AttributeError as error:
            raise PlotDeclarationError(
                "missing_projection",
                "Plot metrics must already be annotated on the supplied results.",
            ) from error
        x_value = _decimal_value(record[x_field], field=x_definition)
        y_value = _decimal_value(record[y_field], field=y_definition)
        if x_value is None or y_value is None:
            null_omissions += 1
            continue
        if (x_scale == "log" and x_value <= 0) or (y_scale == "log" and y_value <= 0):
            log_omissions += 1
            continue
        plotted_values.append((result, x_value, y_value))

    with localcontext() as context:
        context.prec = 50
        x_min, x_max = _domain([value[1] for value in plotted_values], scale=x_scale)
        y_min, y_max = _domain([value[2] for value in plotted_values], scale=y_scale)
        x_axis = _axis_declaration(
            x_definition, x_min, x_max, scale=x_scale, horizontal=True
        )
        y_axis = _axis_declaration(
            y_definition, y_min, y_max, scale=y_scale, horizontal=False
        )
        points = [
            _point_declaration(
                result,
                x_value,
                y_value,
                x_definition=x_definition,
                y_definition=y_definition,
                x_min=x_min,
                x_max=x_max,
                y_min=y_min,
                y_max=y_max,
                x_scale=x_scale,
                y_scale=y_scale,
                point_context=point_context,
            )
            for result, x_value, y_value in plotted_values
        ]

    total_count = len(population)
    plotted_count = len(points)
    resolved_title = title or f"{y_definition.label} against {x_definition.label}"
    omitted_parts = []
    if null_omissions:
        omitted_parts.append(f"{null_omissions} with at least one null axis value")
    if log_omissions:
        omitted_parts.append(
            f"{log_omissions} with a non-positive value on a logarithmic axis"
        )
    return {
        "id": plot_id,
        "kind": "scatter",
        "schema_version": RESULT_RECORD_SCHEMA_VERSION,
        "title": resolved_title,
        "description": (
            f"Scatter plot of {y_definition.label} against {x_definition.label}; "
            f"x is {x_scale} and y is {y_scale}. Points retain the caller's "
            "result order."
        ),
        "viewbox": f"0 0 {_coordinate(VIEWBOX_WIDTH)} {_coordinate(VIEWBOX_HEIGHT)}",
        "width": _coordinate(VIEWBOX_WIDTH),
        "height": _coordinate(VIEWBOX_HEIGHT),
        "plot_left": _coordinate(PLOT_LEFT),
        "plot_right": _coordinate(VIEWBOX_WIDTH - PLOT_RIGHT),
        "plot_top": _coordinate(PLOT_TOP),
        "plot_bottom": _coordinate(VIEWBOX_HEIGHT - PLOT_BOTTOM),
        "plot_centre_x": _coordinate(PLOT_LEFT + PLOT_WIDTH / 2),
        "plot_centre_y": _coordinate(PLOT_TOP + PLOT_HEIGHT / 2),
        "x_axis": x_axis,
        "y_axis": y_axis,
        "points": points,
        "result_ids": [str(result.id) for result in population],
        "plotted_result_ids": [point["id"] for point in points],
        "total_count": total_count,
        "plotted_count": plotted_count,
        "omitted_count": total_count - plotted_count,
        "null_omission_count": null_omissions,
        "log_omission_count": log_omissions,
        "omitted_explanation": "; ".join(omitted_parts),
    }


def _numeric_field(name: str, *, axis: str) -> ResultField:
    field = FIELD_BY_NAME.get(name)
    if field is None:
        raise PlotDeclarationError(
            "unknown_field", f"Unknown ResultRecord field for {axis}-axis: {name}"
        )
    if field.kind not in NUMERIC_FIELD_KINDS:
        raise PlotDeclarationError(
            "nonnumeric_axis",
            f"ResultRecord field {name} cannot be used as a numeric {axis}-axis.",
        )
    return field


def _decimal_value(value: object, *, field: ResultField) -> Decimal | None:
    if value is None:
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PlotDeclarationError(
            "invalid_numeric_value",
            f"ResultRecord field {field.name} contains a non-numeric value.",
        ) from error
    if not converted.is_finite():
        raise PlotDeclarationError(
            "nonfinite_value",
            f"ResultRecord field {field.name} contains a non-finite value.",
        )
    return converted


def _validate_scale(scale: str, *, axis: str) -> None:
    if scale not in PLOT_SCALES:
        raise PlotDeclarationError(
            "invalid_scale", f"Unknown {axis}-axis scale: {scale}"
        )


def _transform(value: Decimal, scale: str) -> Decimal:
    return value if scale == "linear" else value.log10()


def _inverse_transform(value: Decimal, scale: str) -> Decimal:
    return value if scale == "linear" else Decimal(10) ** value


def _domain(values: list[Decimal], *, scale: str) -> tuple[Decimal, Decimal]:
    if not values:
        return Decimal(0), Decimal(1)
    transformed = [_transform(value, scale) for value in values]
    minimum = min(transformed)
    maximum = max(transformed)
    span = maximum - minimum
    if span == 0:
        padding = Decimal("0.05") if scale == "log" else abs(minimum) * Decimal("0.05")
        if padding == 0:
            padding = Decimal(1)
    else:
        padding = span * Decimal("0.05")
    return minimum - padding, maximum + padding


def _axis_declaration(
    field: ResultField,
    minimum: Decimal,
    maximum: Decimal,
    *,
    scale: str,
    horizontal: bool,
) -> dict[str, object]:
    unit_suffix = f" ({field.unit})" if field.unit else ""
    ticks = []
    for index in range(TICK_INTERVALS + 1):
        fraction = Decimal(index) / Decimal(TICK_INTERVALS)
        transformed_value = minimum + (maximum - minimum) * fraction
        value = _inverse_transform(transformed_value, scale)
        if horizontal:
            position = PLOT_LEFT + PLOT_WIDTH * fraction
        else:
            position = PLOT_TOP + PLOT_HEIGHT * (Decimal(1) - fraction)
        ticks.append(
            {
                "position": _coordinate(position),
                "value": str(value),
                "label": format_scientific_value(value),
            }
        )
    return {
        "field": field.name,
        "label": field.label,
        "label_with_unit": f"{field.label}{unit_suffix}",
        "unit": field.unit,
        "definition": field.definition,
        "direction": field.direction,
        "direction_label": field.direction.replace("_", " "),
        "scale": scale,
        "minimum": str(_inverse_transform(minimum, scale)),
        "maximum": str(_inverse_transform(maximum, scale)),
        "minimum_display": format_scientific_value(_inverse_transform(minimum, scale)),
        "maximum_display": format_scientific_value(_inverse_transform(maximum, scale)),
        "ticks": ticks,
    }


def _point_declaration(
    result: Result,
    x_value: Decimal,
    y_value: Decimal,
    *,
    x_definition: ResultField,
    y_definition: ResultField,
    x_min: Decimal,
    x_max: Decimal,
    y_min: Decimal,
    y_max: Decimal,
    x_scale: str,
    y_scale: str,
    point_context: str,
) -> dict[str, object]:
    transformed_x = _transform(x_value, x_scale)
    transformed_y = _transform(y_value, y_scale)
    x_position = PLOT_LEFT + (transformed_x - x_min) / (x_max - x_min) * PLOT_WIDTH
    y_position = (
        PLOT_TOP + PLOT_HEIGHT - (transformed_y - y_min) / (y_max - y_min) * PLOT_HEIGHT
    )
    result_id = str(result.id)
    identity = _point_identity(result, point_context)
    return {
        "id": result_id,
        **identity,
        "x": _coordinate(x_position),
        "y": _coordinate(y_position),
        "x_value": str(x_value),
        "y_value": str(y_value),
        "x_display": _display_with_unit(x_value, x_definition.unit),
        "y_display": _display_with_unit(y_value, y_definition.unit),
        "summary_items": _summary_items(result),
        "result_url": _reverse_or_path(
            "results:detail", [result.id], f"/results/{result.id}/"
        ),
    }


def _point_identity(result: Result, point_context: str) -> dict[str, object]:
    decoder = _related(result, "decoder_version")
    circuit = _related(result, "circuit_revision")
    result_url = _reverse_or_path(
        "results:detail", [result.id], f"/results/{result.id}/"
    )
    decoder_label = (
        f"{decoder.name} v{decoder.version}" if decoder is not None else "Decoder"
    )
    circuit_label = circuit.name if circuit is not None else "Circuit"
    if point_context == "circuit" and decoder is not None:
        return {
            "label": decoder_label,
            "link_url": _reverse_or_path(
                "decoders:detail",
                [decoder.slug],
                f"/decoders/{decoder.slug}/",
            ),
            "link_label": f"Open {decoder_label}",
        }
    if point_context == "decoder" and circuit is not None:
        return {
            "label": circuit_label,
            "link_url": _reverse_or_path(
                "circuits:detail",
                [circuit.slug],
                f"/circuits/{circuit.slug}/",
            ),
            "link_label": f"Open {circuit_label}",
        }
    if point_context in {"results", "machine", "benchmark"}:
        return {
            "label": f"{decoder_label} · {circuit_label}",
            "link_url": result_url,
            "link_label": "Open exact result record",
        }
    return {
        "label": f"Result {result.id}",
        "link_url": result_url,
        "link_label": "Open exact result record",
    }


def _summary_items(result: Result) -> list[dict[str, object]]:
    decoder = _related(result, "decoder_version")
    circuit = _related(result, "circuit_revision")
    machine = _related(result, "machine")
    return [
        {
            "label": "Decoder",
            "value": (
                f"{decoder.name} v{decoder.version}" if decoder is not None else None
            ),
        },
        {
            "label": "Circuit",
            "value": circuit.name if circuit is not None else None,
        },
        {
            "label": "Machine",
            "value": machine.slug if machine is not None else None,
        },
        {"label": "Shots", "value": getattr(result, "shots_total", None)},
        {"label": "Result UUID", "value": str(result.id), "technical": True},
    ]


def _related(result: Result, name: str):
    try:
        return getattr(result, name)
    except ObjectDoesNotExist:
        return None


def _reverse_or_path(name, args, fallback):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return fallback


def _display_with_unit(value: Decimal, unit: str | None) -> str:
    rendered = format_scientific_value(value)
    return f"{rendered} {unit}" if unit else rendered


def _coordinate(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"
