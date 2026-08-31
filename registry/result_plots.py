"""Pure plot declarations over an exact caller-supplied ResultRecord page."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

from django.db.models import QuerySet

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
    plot_id: str = "result-scatter",
    title: str | None = None,
) -> dict[str, object]:
    """Describe one linear scatter plot without selecting any database rows.

    ``results`` must be the already parsed, ordered, and paged population used
    by the caller's table.  In particular, evaluator metric annotations must
    already be present (as they are after ``execute_result_query``).  This
    function deliberately performs no ORM query and preserves supplied order.
    """

    x_definition = _numeric_field(x_field, axis="x")
    y_definition = _numeric_field(y_field, axis="y")
    if isinstance(results, QuerySet):
        raise PlotDeclarationError(
            "unmaterialized_population",
            "Pass the exact materialized result page, not a QuerySet, to the plot.",
        )
    population = list(results)
    plotted_values: list[tuple[Result, Decimal, Decimal]] = []

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
            continue
        plotted_values.append((result, x_value, y_value))

    with localcontext() as context:
        context.prec = 50
        x_min, x_max = _domain([value[1] for value in plotted_values])
        y_min, y_max = _domain([value[2] for value in plotted_values])
        x_axis = _axis_declaration(x_definition, x_min, x_max, horizontal=True)
        y_axis = _axis_declaration(y_definition, y_min, y_max, horizontal=False)
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
            )
            for result, x_value, y_value in plotted_values
        ]

    total_count = len(population)
    plotted_count = len(points)
    resolved_title = title or f"{y_definition.label} against {x_definition.label}"
    return {
        "id": plot_id,
        "kind": "scatter",
        "schema_version": RESULT_RECORD_SCHEMA_VERSION,
        "title": resolved_title,
        "description": (
            f"Linear scatter plot of {y_definition.label} against "
            f"{x_definition.label}. Points retain the caller's result order."
        ),
        "viewbox": f"0 0 {_coordinate(VIEWBOX_WIDTH)} "
        f"{_coordinate(VIEWBOX_HEIGHT)}",
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


def _domain(values: list[Decimal]) -> tuple[Decimal, Decimal]:
    if not values:
        return Decimal(0), Decimal(1)
    minimum = min(values)
    maximum = max(values)
    span = maximum - minimum
    if span == 0:
        padding = abs(minimum) * Decimal("0.05")
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
    horizontal: bool,
) -> dict[str, object]:
    unit_suffix = f" ({field.unit})" if field.unit else ""
    ticks = []
    for index in range(TICK_INTERVALS + 1):
        fraction = Decimal(index) / Decimal(TICK_INTERVALS)
        value = minimum + (maximum - minimum) * fraction
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
        "scale": "linear",
        "minimum": str(minimum),
        "maximum": str(maximum),
        "minimum_display": format_scientific_value(minimum),
        "maximum_display": format_scientific_value(maximum),
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
) -> dict[str, object]:
    x_position = PLOT_LEFT + (x_value - x_min) / (x_max - x_min) * PLOT_WIDTH
    y_position = (
        PLOT_TOP
        + PLOT_HEIGHT
        - (y_value - y_min) / (y_max - y_min) * PLOT_HEIGHT
    )
    result_id = str(result.id)
    return {
        "id": result_id,
        "label": f"Result {result_id}",
        "x": _coordinate(x_position),
        "y": _coordinate(y_position),
        "x_value": str(x_value),
        "y_value": str(y_value),
        "x_display": _display_with_unit(x_value, x_definition.unit),
        "y_display": _display_with_unit(y_value, y_definition.unit),
    }


def _display_with_unit(value: Decimal, unit: str | None) -> str:
    rendered = format_scientific_value(value)
    return f"{rendered} {unit}" if unit else rendered


def _coordinate(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"
