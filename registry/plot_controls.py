"""Declarative controls for the reusable scientific result plot."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from registry.formatting import format_scientific_range, format_scientific_value
from registry.result_query import (
    ResultField,
    metric_component_annotation,
    result_record,
)

PLOT_SCALES = (("linear", "Linear"), ("log", "Logarithmic"))
MARKER_STYLES = (
    ("circle", "Circle"),
    ("square", "Square"),
    ("diamond", "Diamond"),
    ("cross", "Cross"),
)
MARKER_COLOURS = (
    ("theme", "Theme accent"),
    ("blue", "Blue"),
    ("orange", "Orange"),
    ("green", "Green"),
    ("purple", "Purple"),
)
UNCERTAINTY_STYLES = (
    ("bars", "Whisker bars"),
    ("areas", "Shaded extents"),
    ("none", "Hidden"),
)


def plot_control_grids(
    *,
    plot_id: str,
    results,
    numeric_fields: tuple[ResultField, ...],
    x_field: str,
    y_field: str,
    x_scale: str,
    y_scale: str,
    x_minimum: str,
    x_maximum: str,
    y_minimum: str,
    y_maximum: str,
    major_gridlines: bool,
    minor_gridlines: bool,
    marker_style: str,
    marker_colour: str,
    uncertainty_style: str = "bars",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return main and advanced plot-control grids over one result page."""

    options = []
    for field in numeric_fields:
        interval_count = _axis_interval_count(results, field)
        options.append(
            {
                "value": field.name,
                "label": field.label,
                "unit": field.unit,
                "description": _axis_description(field),
                "interval_count": interval_count,
                "interval_label": (
                    f"{interval_count} stored interval"
                    f"{'s' if interval_count != 1 else ''}"
                ),
            }
        )
    options = tuple(options)
    fields_by_name = {field.name: field for field in numeric_fields}
    main = {
        "id": f"{plot_id}-main-settings",
        "title": "Main plot settings",
        "legend": "axes, scales and visible ranges",
        "open": True,
        "cells": [
            _axis_cell(
                key="x-axis",
                label="x-axis",
                name="plot_x",
                value=x_field,
                options=options,
                picker_id=f"{plot_id}-x-axis-picker",
            ),
            _choice_cell(
                key="x-scale",
                label="x-scale",
                name="plot_x_scale",
                value=x_scale,
                choices=PLOT_SCALES,
            ),
            _range_cell(
                key="x-range",
                label="x range",
                minimum_name="plot_x_min",
                maximum_name="plot_x_max",
                minimum_value=x_minimum,
                maximum_value=x_maximum,
                values=_axis_values(results, fields_by_name[x_field]),
                histogram_label=f"{fields_by_name[x_field].label} distribution",
                number_profile=_number_profile(fields_by_name[x_field]),
            ),
            _axis_cell(
                key="y-axis",
                label="y-axis",
                name="plot_y",
                value=y_field,
                options=options,
                picker_id=f"{plot_id}-y-axis-picker",
            ),
            _choice_cell(
                key="y-scale",
                label="y-scale",
                name="plot_y_scale",
                value=y_scale,
                choices=PLOT_SCALES,
            ),
            _range_cell(
                key="y-range",
                label="y range",
                minimum_name="plot_y_min",
                maximum_name="plot_y_max",
                minimum_value=y_minimum,
                maximum_value=y_maximum,
                values=_axis_values(results, fields_by_name[y_field]),
                histogram_label=f"{fields_by_name[y_field].label} distribution",
                number_profile=_number_profile(fields_by_name[y_field]),
            ),
        ],
    }
    advanced = {
        "id": f"{plot_id}-advanced-settings",
        "title": "Advanced plot settings",
        "legend": "uncertainty, grid and marker appearance",
        "open": False,
        "cells": [
            _toggle_cell(
                key="major-gridlines",
                label="Major gridlines",
                name="plot_major_grid",
                checked=major_gridlines,
            ),
            _toggle_cell(
                key="minor-gridlines",
                label="Minor gridlines",
                name="plot_minor_grid",
                checked=minor_gridlines,
            ),
            _choice_cell(
                key="uncertainty-style",
                label="Stored intervals",
                name="plot_uncertainty",
                value=uncertainty_style,
                choices=UNCERTAINTY_STYLES,
            ),
            _choice_cell(
                key="marker-style",
                label="Marker style",
                name="plot_marker_style",
                value=marker_style,
                choices=MARKER_STYLES,
            ),
            _choice_cell(
                key="marker-colour",
                label="Marker colour",
                name="plot_marker_colour",
                value=marker_colour,
                choices=MARKER_COLOURS,
            ),
        ],
    }
    return main, advanced


def _axis_cell(*, key, label, name, value, options, picker_id):
    selected = next(option for option in options if option["value"] == value)
    return {
        "type": "axis",
        "key": key,
        "label": label,
        "name": name,
        "value": value,
        "display_value": _option_label(selected),
        "options": options,
        "picker_id": picker_id,
        "span": 2,
    }


def _choice_cell(*, key, label, name, value, choices):
    normalized = tuple(
        {"value": choice_value, "label": choice_label}
        for choice_value, choice_label in choices
    )
    labels = {choice["value"]: choice["label"] for choice in normalized}
    return {
        "type": "choice",
        "key": key,
        "label": label,
        "name": name,
        "value": value,
        "display_value": labels[value],
        "choices": normalized,
        "filtered": True,
        "span": 1,
    }


def _toggle_cell(*, key, label, name, checked):
    return {
        "type": "toggle",
        "key": key,
        "label": label,
        "name": name,
        "checked": checked,
        "display_value": "Shown" if checked else "Hidden",
        "span": 1,
    }


def _range_cell(
    *,
    key,
    label,
    minimum_name,
    maximum_name,
    minimum_value,
    maximum_value,
    values,
    histogram_label,
    number_profile,
):
    histogram = _decimal_histogram(values)
    display_value = format_scientific_range(
        minimum_value,
        maximum_value,
        empty_label="Auto",
        minimum_fallback="auto",
        maximum_fallback="auto",
    )
    return {
        "type": "range",
        "key": key,
        "label": label,
        "minimum_name": minimum_name,
        "maximum_name": maximum_name,
        "minimum_value": minimum_value,
        "maximum_value": maximum_value,
        "display_minimum": (
            format_scientific_value(minimum_value) if minimum_value else "auto"
        ),
        "display_maximum": (
            format_scientific_value(maximum_value) if maximum_value else "auto"
        ),
        "display_value": display_value,
        "filtered": bool(minimum_value or maximum_value),
        "allow_negative": True,
        "histogram_label": histogram_label,
        "number_profile": number_profile,
        "histogram": histogram,
        "step": "any",
        "span": 1,
    }


def _axis_values(results, field: ResultField) -> list[Decimal]:
    values = []
    for result in results:
        value = result_record(result, (field.name,))[field.name]
        if value is None:
            continue
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if number.is_finite():
            values.append(number)
    return values


def _decimal_histogram(values, *, maximum_bins=18):
    clean = [Decimal(value) for value in values if Decimal(value).is_finite()]
    minimum = min(clean, default=Decimal(0))
    maximum = max(clean, default=Decimal(1))
    minimum = min(minimum, Decimal(0))
    if maximum <= minimum:
        maximum = minimum + Decimal(1)
    counts = [0] * maximum_bins
    span = maximum - minimum
    for value in clean:
        ratio = (value - minimum) / span
        index = min(maximum_bins - 1, max(0, int(ratio * maximum_bins)))
        counts[index] += 1
    return {
        "domain_min": _plain_decimal(minimum),
        "domain_max": _plain_decimal(maximum),
        "counts": counts,
    }


def _axis_description(field: ResultField) -> str:
    pieces = [field.kind]
    if field.unit:
        pieces.append(field.unit)
    if field.direction != "not_ranked":
        pieces.append(field.direction.replace("_", " "))
    return " · ".join(pieces)


def _axis_interval_count(results, field: ResultField) -> int:
    if not field.is_metric:
        return 0
    lower_name = metric_component_annotation(field, "lower_bound")
    upper_name = metric_component_annotation(field, "upper_bound")
    return sum(
        getattr(result, lower_name, None) is not None
        and getattr(result, upper_name, None) is not None
        for result in results
    )


def _option_label(option):
    return (
        f"{option['label']} ({option['unit']})" if option["unit"] else option["label"]
    )


def _plain_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _number_profile(field: ResultField) -> str:
    if field.kind == "integer":
        return "count"
    if field.unit == "probability" or "ler" in field.name or "brier" in field.name:
        return "probability"
    if field.unit in {"ns", "s", "ms", "µs"}:
        return "duration"
    return "score"
