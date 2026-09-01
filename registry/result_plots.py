"""Pure plot declarations over an exact caller-supplied ResultRecord page."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_UP,
    Decimal,
    InvalidOperation,
    localcontext,
)

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.urls import NoReverseMatch, reverse

from registry.formatting import format_scientific_value, scientific_number_display
from registry.models import Result
from registry.result_query import (
    FIELD_BY_NAME,
    RESULT_RECORD_SCHEMA_VERSION,
    ResultField,
    metric_component_annotation,
    result_record,
)

DEFAULT_X_FIELD = "t_1000_ns"
DEFAULT_Y_FIELD = "score_ler_upper_95_at_5pct_acceptance_v0_1"
NUMERIC_FIELD_KINDS = {"integer", "decimal"}
PLOT_SCALES = {"linear", "log"}
UNCERTAINTY_STYLES = {"bars", "areas", "none"}
POINT_CONTEXTS = {"results", "circuit", "decoder", "machine", "benchmark"}

VIEWBOX_WIDTH = Decimal(800)
VIEWBOX_HEIGHT = Decimal(440)
PLOT_LEFT = Decimal(92)
PLOT_RIGHT = Decimal(24)
PLOT_TOP = Decimal(20)
PLOT_BOTTOM = Decimal(76)
PLOT_WIDTH = VIEWBOX_WIDTH - PLOT_LEFT - PLOT_RIGHT
PLOT_HEIGHT = VIEWBOX_HEIGHT - PLOT_TOP - PLOT_BOTTOM
TARGET_MAJOR_INTERVALS = 4


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
    x_min: object | None = None,
    x_max: object | None = None,
    y_min: object | None = None,
    y_max: object | None = None,
    uncertainty_style: str = "bars",
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
    _validate_uncertainty_style(uncertainty_style)
    x_min_bound = _axis_bound(x_min, axis="x", edge="minimum", scale=x_scale)
    x_max_bound = _axis_bound(x_max, axis="x", edge="maximum", scale=x_scale)
    y_min_bound = _axis_bound(y_min, axis="y", edge="minimum", scale=y_scale)
    y_max_bound = _axis_bound(y_max, axis="y", edge="maximum", scale=y_scale)
    _validate_bound_order(x_min_bound, x_max_bound, axis="x")
    _validate_bound_order(y_min_bound, y_max_bound, axis="y")
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
    plotted_values: list[
        tuple[
            Result,
            Decimal,
            Decimal,
            dict[str, Decimal] | None,
            dict[str, Decimal] | None,
        ]
    ] = []
    null_omissions = 0
    log_omissions = 0
    range_omissions = 0

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
        x_interval = _stored_interval(result, x_definition, scale=x_scale)
        y_interval = _stored_interval(result, y_definition, scale=y_scale)
        plotted_values.append((result, x_value, y_value, x_interval, y_interval))

    with localcontext() as context:
        context.prec = 50
        show_uncertainty = uncertainty_style != "none"
        x_domain_min, x_domain_max = _domain(
            _domain_values(
                plotted_values, axis_index=1, show_uncertainty=show_uncertainty
            ),
            scale=x_scale,
            minimum_bound=x_min_bound,
            maximum_bound=x_max_bound,
            axis="x",
        )
        y_domain_min, y_domain_max = _domain(
            _domain_values(
                plotted_values, axis_index=2, show_uncertainty=show_uncertainty
            ),
            scale=y_scale,
            minimum_bound=y_min_bound,
            maximum_bound=y_max_bound,
            axis="y",
        )
        in_range_values = []
        for item in plotted_values:
            _, x_value, y_value, _, _ = item
            if not _within_bounds(x_value, x_min_bound, x_max_bound) or not (
                _within_bounds(y_value, y_min_bound, y_max_bound)
            ):
                range_omissions += 1
                continue
            in_range_values.append(item)
        x_axis = _axis_declaration(
            x_definition,
            x_domain_min,
            x_domain_max,
            scale=x_scale,
            horizontal=True,
            minimum_is_explicit=x_min_bound is not None,
            maximum_is_explicit=x_max_bound is not None,
        )
        y_axis = _axis_declaration(
            y_definition,
            y_domain_min,
            y_domain_max,
            scale=y_scale,
            horizontal=False,
            minimum_is_explicit=y_min_bound is not None,
            maximum_is_explicit=y_max_bound is not None,
        )
        points = [
            _point_declaration(
                result,
                x_value,
                y_value,
                x_definition=x_definition,
                y_definition=y_definition,
                x_min=x_domain_min,
                x_max=x_domain_max,
                y_min=y_domain_min,
                y_max=y_domain_max,
                x_scale=x_scale,
                y_scale=y_scale,
                x_interval=x_interval if show_uncertainty else None,
                y_interval=y_interval if show_uncertainty else None,
                point_context=point_context,
            )
            for result, x_value, y_value, x_interval, y_interval in in_range_values
        ]

    total_count = len(population)
    plotted_count = len(points)
    available_x_intervals = sum(item[3] is not None for item in in_range_values)
    available_y_intervals = sum(item[4] is not None for item in in_range_values)
    resolved_title = title or f"{y_definition.label} against {x_definition.label}"
    omitted_parts = []
    if null_omissions:
        omitted_parts.append(f"{null_omissions} with at least one null axis value")
    if log_omissions:
        omitted_parts.append(
            f"{log_omissions} with a non-positive value on a logarithmic axis"
        )
    if range_omissions:
        omitted_parts.append(f"{range_omissions} outside the explicit axis limits")
    return {
        "id": plot_id,
        "kind": "scatter",
        "schema_version": RESULT_RECORD_SCHEMA_VERSION,
        "title": resolved_title,
        "description": (
            f"Scatter plot of {y_definition.label} against {x_definition.label}; "
            f"x is {x_scale} and y is {y_scale}. Points retain the caller's "
            f"result order. Stored intervals are displayed as {uncertainty_style}."
        ),
        "viewbox": f"0 0 {_coordinate(VIEWBOX_WIDTH)} {_coordinate(VIEWBOX_HEIGHT)}",
        "width": _coordinate(VIEWBOX_WIDTH),
        "height": _coordinate(VIEWBOX_HEIGHT),
        "plot_left": _coordinate(PLOT_LEFT),
        "plot_right": _coordinate(VIEWBOX_WIDTH - PLOT_RIGHT),
        "plot_top": _coordinate(PLOT_TOP),
        "plot_bottom": _coordinate(VIEWBOX_HEIGHT - PLOT_BOTTOM),
        "plot_width": _coordinate(PLOT_WIDTH),
        "plot_height": _coordinate(PLOT_HEIGHT),
        "plot_centre_x": _coordinate(PLOT_LEFT + PLOT_WIDTH / 2),
        "plot_centre_y": _coordinate(PLOT_TOP + PLOT_HEIGHT / 2),
        "x_axis": x_axis,
        "y_axis": y_axis,
        "points": points,
        "uncertainty_style": uncertainty_style,
        "uncertainty": {
            "style": uncertainty_style,
            "label": {
                "bars": "Whisker bars",
                "areas": "Shaded extents",
                "none": "Hidden",
            }[uncertainty_style],
            "x_interval_count": available_x_intervals,
            "y_interval_count": available_y_intervals,
            "explanation": (
                "Only complete lower/upper intervals stored under the exact selected "
                "score definition are drawn; Circuit Bench does not infer missing "
                "errors."
            ),
        },
        "result_ids": [str(result.id) for result in population],
        "plotted_result_ids": [point["id"] for point in points],
        "total_count": total_count,
        "plotted_count": plotted_count,
        "omitted_count": total_count - plotted_count,
        "null_omission_count": null_omissions,
        "log_omission_count": log_omissions,
        "range_omission_count": range_omissions,
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


def _validate_uncertainty_style(style: str) -> None:
    if style not in UNCERTAINTY_STYLES:
        raise PlotDeclarationError(
            "invalid_uncertainty_style", f"Unknown uncertainty display: {style}"
        )


def _stored_interval(
    result: Result,
    field: ResultField,
    *,
    scale: str,
) -> dict[str, Decimal] | None:
    """Read a complete stored interval projected by ``annotate_result_metrics``."""

    if not field.is_metric:
        return None
    values: dict[str, Decimal] = {}
    for component in (
        "point_estimate",
        "lower_bound",
        "upper_bound",
        "confidence_level",
    ):
        raw_value = getattr(
            result,
            metric_component_annotation(field, component),
            None,
        )
        if raw_value is None:
            continue
        converted = _decimal_value(raw_value, field=field)
        if converted is not None:
            values[component] = converted
    lower = values.get("lower_bound")
    upper = values.get("upper_bound")
    if lower is None or upper is None or lower > upper:
        return None
    if scale == "log" and (lower <= 0 or upper <= 0):
        return None
    return values


def _domain_values(plotted_values, *, axis_index: int, show_uncertainty: bool):
    values = [item[axis_index] for item in plotted_values]
    if not show_uncertainty:
        return values
    interval_index = 3 if axis_index == 1 else 4
    for item in plotted_values:
        interval = item[interval_index]
        if interval is not None:
            values.extend((interval["lower_bound"], interval["upper_bound"]))
    return values


def _axis_bound(
    value: object | None,
    *,
    axis: str,
    edge: str,
    scale: str,
) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        bound = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PlotDeclarationError(
            "invalid_axis_bound",
            f"The {axis}-axis {edge} must be a finite number.",
        ) from error
    if not bound.is_finite():
        raise PlotDeclarationError(
            "invalid_axis_bound",
            f"The {axis}-axis {edge} must be a finite number.",
        )
    if scale == "log" and bound <= 0:
        raise PlotDeclarationError(
            "nonpositive_log_bound",
            f"The {axis}-axis {edge} must be positive on a logarithmic scale.",
        )
    return bound


def _validate_bound_order(
    minimum: Decimal | None,
    maximum: Decimal | None,
    *,
    axis: str,
) -> None:
    if minimum is not None and maximum is not None and minimum >= maximum:
        raise PlotDeclarationError(
            "invalid_axis_domain",
            f"The {axis}-axis minimum must be less than its maximum.",
        )


def _within_bounds(
    value: Decimal,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> bool:
    return (minimum is None or value >= minimum) and (
        maximum is None or value <= maximum
    )


def _transform(value: Decimal, scale: str) -> Decimal:
    return value if scale == "linear" else value.log10()


def _inverse_transform(value: Decimal, scale: str) -> Decimal:
    return value if scale == "linear" else Decimal(10) ** value


def _domain(
    values: list[Decimal],
    *,
    scale: str,
    minimum_bound: Decimal | None,
    maximum_bound: Decimal | None,
    axis: str,
) -> tuple[Decimal, Decimal]:
    if not values:
        automatic_minimum, automatic_maximum = Decimal(0), Decimal(1)
    else:
        transformed = [_transform(value, scale) for value in values]
        automatic_minimum = min(transformed)
        automatic_maximum = max(transformed)
        span = automatic_maximum - automatic_minimum
        if span == 0:
            padding = (
                Decimal("0.05")
                if scale == "log"
                else abs(automatic_minimum) * Decimal("0.05")
            )
            if padding == 0:
                padding = Decimal(1)
        else:
            padding = span * Decimal("0.05")
        automatic_minimum -= padding
        automatic_maximum += padding

    minimum = (
        _transform(minimum_bound, scale)
        if minimum_bound is not None
        else automatic_minimum
    )
    maximum = (
        _transform(maximum_bound, scale)
        if maximum_bound is not None
        else automatic_maximum
    )
    if minimum >= maximum:
        if minimum_bound is not None and maximum_bound is None:
            maximum = minimum + _empty_domain_span(minimum, scale=scale)
        elif minimum_bound is None and maximum_bound is not None:
            minimum = maximum - _empty_domain_span(maximum, scale=scale)
        else:
            raise PlotDeclarationError(
                "invalid_axis_domain",
                f"The resolved {axis}-axis minimum must be less than its maximum.",
            )
    return minimum, maximum


def _empty_domain_span(edge: Decimal, *, scale: str) -> Decimal:
    if scale == "log":
        return Decimal("0.05")
    span = abs(edge) * Decimal("0.05")
    return span if span else Decimal(1)


def _axis_declaration(
    field: ResultField,
    minimum: Decimal,
    maximum: Decimal,
    *,
    scale: str,
    horizontal: bool,
    minimum_is_explicit: bool,
    maximum_is_explicit: bool,
) -> dict[str, object]:
    unit_suffix = f" ({field.unit})" if field.unit else ""
    major_values, minor_values = _tick_values(minimum, maximum, scale=scale)
    major_ticks = [
        _tick_declaration(
            value,
            minimum,
            maximum,
            scale=scale,
            horizontal=horizontal,
            kind="major",
            number=scientific_number_display(value, profile=_number_profile(field)),
        )
        for value in major_values
    ]
    minor_ticks = [
        _tick_declaration(
            value,
            minimum,
            maximum,
            scale=scale,
            horizontal=horizontal,
            kind="minor",
        )
        for value in minor_values
    ]
    ticks = sorted(
        [*major_ticks, *minor_ticks],
        key=lambda tick: Decimal(str(tick["value"])),
    )
    return {
        "field": field.name,
        "label": field.label,
        "label_with_unit": f"{field.label}{unit_suffix}",
        "unit": field.unit,
        "number_profile": _number_profile(field),
        "definition": field.definition,
        "direction": field.direction,
        "direction_label": field.direction.replace("_", " "),
        "scale": scale,
        "minimum": str(_inverse_transform(minimum, scale)),
        "maximum": str(_inverse_transform(maximum, scale)),
        "minimum_display": format_scientific_value(_inverse_transform(minimum, scale)),
        "maximum_display": format_scientific_value(_inverse_transform(maximum, scale)),
        "minimum_is_explicit": minimum_is_explicit,
        "maximum_is_explicit": maximum_is_explicit,
        "major_ticks": major_ticks,
        "minor_ticks": minor_ticks,
        "ticks": ticks,
    }


def _tick_values(
    minimum: Decimal,
    maximum: Decimal,
    *,
    scale: str,
) -> tuple[list[Decimal], list[Decimal]]:
    if scale == "log":
        return _log_tick_values(minimum, maximum)
    return _linear_tick_values(minimum, maximum)


def _linear_tick_values(
    minimum: Decimal,
    maximum: Decimal,
    *,
    target_intervals: int = TARGET_MAJOR_INTERVALS,
) -> tuple[list[Decimal], list[Decimal]]:
    step = _nice_step((maximum - minimum) / Decimal(target_intervals))
    minor_step = _linear_minor_step(step)
    major_values = _multiples_within(minimum, maximum, step)
    major_set = set(major_values)
    minor_values = [
        value
        for value in _multiples_within(minimum, maximum, minor_step)
        if value not in major_set
    ]
    return major_values, minor_values


def _nice_step(rough_step: Decimal) -> Decimal:
    exponent = rough_step.adjusted()
    magnitude = Decimal(1).scaleb(exponent)
    fraction = rough_step / magnitude
    if fraction < Decimal("1.5"):
        multiplier = Decimal(1)
    elif fraction < Decimal(3):
        multiplier = Decimal(2)
    elif fraction < Decimal(7):
        multiplier = Decimal(5)
    else:
        multiplier = Decimal(10)
    return multiplier * magnitude


def _linear_minor_step(major_step: Decimal) -> Decimal:
    normalised = major_step.scaleb(-major_step.adjusted())
    if normalised == 2:
        return major_step / Decimal(4)
    return major_step / Decimal(5)


def _multiples_within(
    minimum: Decimal,
    maximum: Decimal,
    step: Decimal,
) -> list[Decimal]:
    first_multiplier = (minimum / step).to_integral_value(rounding=ROUND_CEILING)
    last_multiplier = (maximum / step).to_integral_value(rounding=ROUND_FLOOR)
    return [
        multiplier * step
        for multiplier in range(int(first_multiplier), int(last_multiplier) + 1)
    ]


def _log_tick_values(
    minimum: Decimal,
    maximum: Decimal,
) -> tuple[list[Decimal], list[Decimal]]:
    raw_minimum = _inverse_transform(minimum, "log")
    raw_maximum = _inverse_transform(maximum, "log")
    decade_span = maximum - minimum
    if decade_span < 1:
        major_values, minor_values = _linear_tick_values(
            raw_minimum,
            raw_maximum,
            target_intervals=6,
        )
        return (
            [value for value in major_values if value > 0],
            [value for value in minor_values if value > 0],
        )

    first_major_exponent = int(minimum.to_integral_value(rounding=ROUND_CEILING))
    last_major_exponent = int(maximum.to_integral_value(rounding=ROUND_FLOOR))
    decade_values = [
        Decimal(1).scaleb(exponent)
        for exponent in range(first_major_exponent, last_major_exponent + 1)
    ]

    first_minor_exponent = int(minimum.to_integral_value(rounding=ROUND_FLOOR))
    last_minor_exponent = int(maximum.to_integral_value(rounding=ROUND_FLOOR))
    subdivision_values = []
    for exponent in range(first_minor_exponent, last_minor_exponent + 1):
        decade = Decimal(1).scaleb(exponent)
        subdivision_values.extend(
            value
            for multiplier in range(1, 10)
            if raw_minimum <= (value := Decimal(multiplier) * decade) <= raw_maximum
        )
    if decade_span < Decimal("2.5"):
        major_values = [
            value
            for value in subdivision_values
            if value / Decimal(1).scaleb(value.adjusted()) in {1, 2, 5}
        ]
    else:
        major_values = decade_values
    major_set = set(major_values)
    minor_values = [value for value in subdivision_values if value not in major_set]
    return major_values, minor_values


def _tick_declaration(
    value: Decimal,
    minimum: Decimal,
    maximum: Decimal,
    *,
    scale: str,
    horizontal: bool,
    kind: str,
    number=None,
) -> dict[str, object]:
    fraction = (_transform(value, scale) - minimum) / (maximum - minimum)
    if horizontal:
        position = PLOT_LEFT + PLOT_WIDTH * fraction
    else:
        position = PLOT_TOP + PLOT_HEIGHT * (Decimal(1) - fraction)
    declaration: dict[str, object] = {
        "position": _coordinate(position),
        "value": str(value),
        "kind": kind,
        "is_major": kind == "major",
    }
    if number is not None:
        declaration["number"] = number
        declaration["label"] = number.text
    return declaration


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
    x_interval: dict[str, Decimal] | None,
    y_interval: dict[str, Decimal] | None,
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
        "x_display": _display_with_unit(
            x_value, x_definition.unit, profile=_number_profile(x_definition)
        ),
        "y_display": _display_with_unit(
            y_value, y_definition.unit, profile=_number_profile(y_definition)
        ),
        "x_interval": _interval_declaration(
            x_interval,
            field=x_definition,
            minimum=x_min,
            maximum=x_max,
            scale=x_scale,
            horizontal=True,
        ),
        "y_interval": _interval_declaration(
            y_interval,
            field=y_definition,
            minimum=y_min,
            maximum=y_max,
            scale=y_scale,
            horizontal=False,
        ),
        "summary_items": _summary_items(result),
        "result_url": _reverse_or_path(
            "results:detail", [result.id], f"/results/{result.id}/"
        ),
    }


def _interval_declaration(
    interval: dict[str, Decimal] | None,
    *,
    field: ResultField,
    minimum: Decimal,
    maximum: Decimal,
    scale: str,
    horizontal: bool,
) -> dict[str, object] | None:
    if interval is None:
        return None
    lower_value = interval["lower_bound"]
    upper_value = interval["upper_bound"]
    lower_position = _value_position(
        lower_value,
        minimum=minimum,
        maximum=maximum,
        scale=scale,
        horizontal=horizontal,
    )
    upper_position = _value_position(
        upper_value,
        minimum=minimum,
        maximum=maximum,
        scale=scale,
        horizontal=horizontal,
    )
    start = min(lower_position, upper_position)
    end = max(lower_position, upper_position)
    confidence = interval.get("confidence_level")
    estimate = interval.get("point_estimate")
    return {
        "lower_value": str(lower_value),
        "upper_value": str(upper_value),
        "lower_display": _display_with_unit(
            lower_value, field.unit, profile=_number_profile(field)
        ),
        "upper_display": _display_with_unit(
            upper_value, field.unit, profile=_number_profile(field)
        ),
        "start": _coordinate(start),
        "end": _coordinate(end),
        "size": _coordinate(end - start),
        "point_estimate": str(estimate) if estimate is not None else None,
        "point_estimate_display": (
            _display_with_unit(estimate, field.unit, profile=_number_profile(field))
            if estimate is not None
            else None
        ),
        "confidence_level": str(confidence) if confidence is not None else None,
        "confidence_display": (
            f"{format_scientific_value(confidence * 100)}%"
            if confidence is not None
            else None
        ),
    }


def _value_position(
    value: Decimal,
    *,
    minimum: Decimal,
    maximum: Decimal,
    scale: str,
    horizontal: bool,
) -> Decimal:
    transformed = _transform(value, scale)
    fraction = (transformed - minimum) / (maximum - minimum)
    fraction = max(Decimal(0), min(Decimal(1), fraction))
    if horizontal:
        return PLOT_LEFT + fraction * PLOT_WIDTH
    return PLOT_TOP + (Decimal(1) - fraction) * PLOT_HEIGHT


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
        {
            "label": "Shots",
            "value": getattr(result, "shots_total", None),
            "numeric": True,
            "number_profile": "count",
        },
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


def _display_with_unit(
    value: Decimal, unit: str | None, *, profile: str = "default"
) -> str:
    rendered = format_scientific_value(value, profile=profile)
    return f"{rendered} {unit}" if unit else rendered


def _number_profile(field: ResultField) -> str:
    if field.kind == "integer":
        return "count"
    if field.unit == "probability" or "ler" in field.name or "brier" in field.name:
        return "probability"
    if field.unit in {"ns", "s", "ms", "µs"}:
        return "duration"
    return "score"


def _coordinate(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"
