"""Shared circuit-population controls for native and imported tag pages."""

from __future__ import annotations

from collections.abc import Mapping

from django.urls import reverse

from registry.filter_grids import choice_cell, filter_grid, range_cell
from registry.services.circuits import circuit_catalogue
from registry.table_controls import (
    ColumnSpec,
    apply_sort,
    cells_for_visible_columns,
    parse_nonnegative_int,
    parse_sort,
    table_context,
    url_without,
)

CIRCUIT_USAGE_COLUMNS = (
    ColumnSpec("name", "Circuit"),
    ColumnSpec("noise_model", "Noise model"),
    ColumnSpec("priors", "Randomised priors"),
    ColumnSpec("css", "CSS"),
    ColumnSpec("code_distance", "Code d ≤", numeric=True),
    ColumnSpec("circuit_distance", "Circuit d ≤", numeric=True),
    ColumnSpec("detectors", "Detectors", numeric=True),
    ColumnSpec("errors", "Errors", numeric=True),
    ColumnSpec("results", "Results", numeric=True, default_direction="desc"),
    ColumnSpec("published", "Published", default_direction="desc"),
)

CIRCUIT_USAGE_SORT_FIELDS = {
    "name": "name",
    "noise_model": "noise_model__name",
    "priors": "noise_model__randomises_priors",
    "css": "is_css",
    "code_distance": "code_distance_upper_bound",
    "circuit_distance": "circuit_distance_upper_bound",
    "detectors": "num_detectors",
    "errors": "num_errors",
    "results": "published_result_count",
    "published": "published_at",
}


def include_descendants_from_request(request) -> bool:
    """Read the default-on descendant checkbox from a GET request."""

    values = request.GET.getlist("include_descendants")
    if not values:
        return True
    return values[-1] in {"1", "true", "on", "yes"}


def circuit_usage_context(
    request,
    *,
    scope_arguments: Mapping[str, object],
    reset_url: str,
    grid_id: str,
    label: str,
    empty: str,
) -> dict[str, object]:
    """Build one searchable, filterable and sortable circuit-usage table."""

    query = request.GET.get("q", "").strip()
    priors = request.GET.get("priors", "").strip()
    css = request.GET.get("css", "").strip()
    raw = {
        name: request.GET.get(name, "")
        for name in (
            "code_d_min",
            "code_d_max",
            "circuit_d_min",
            "circuit_d_max",
            "detector_min",
            "detector_max",
            "error_min",
            "error_max",
        )
    }
    base = circuit_catalogue(**scope_arguments)
    distributions = {
        "code_distance": list(base.values_list("code_distance_upper_bound", flat=True)),
        "circuit_distance": list(
            base.values_list("circuit_distance_upper_bound", flat=True)
        ),
        "detectors": list(base.values_list("num_detectors", flat=True)),
        "errors": list(base.values_list("num_errors", flat=True)),
    }
    filters = {
        "randomises_priors": priors,
        "is_css": css,
        "code_distance_min": parse_nonnegative_int(raw["code_d_min"]),
        "code_distance_max": parse_nonnegative_int(raw["code_d_max"]),
        "circuit_distance_min": parse_nonnegative_int(raw["circuit_d_min"]),
        "circuit_distance_max": parse_nonnegative_int(raw["circuit_d_max"]),
        "detector_min": parse_nonnegative_int(raw["detector_min"]),
        "detector_max": parse_nonnegative_int(raw["detector_max"]),
        "error_min": parse_nonnegative_int(raw["error_min"]),
        "error_max": parse_nonnegative_int(raw["error_max"]),
    }
    queryset = circuit_catalogue(query=query, **scope_arguments, **filters)
    sort_keys = parse_sort(
        request.GET.get("sort", ""), CIRCUIT_USAGE_COLUMNS, (("name", "asc"),)
    )
    records = list(apply_sort(queryset, sort_keys, CIRCUIT_USAGE_SORT_FIELDS))
    table = table_context(request, CIRCUIT_USAGE_COLUMNS, sort_keys)
    rows = _circuit_rows(records, table["visible_column_keys"])
    grid = _circuit_filter_grid(
        grid_id=grid_id,
        priors=priors,
        css=css,
        raw=raw,
        distributions=distributions,
    )
    include_descendants = include_descendants_from_request(request)
    return {
        "usage_query": query,
        "usage_records": records,
        "usage_rows": rows,
        "usage_grid": grid,
        "usage_label": label,
        "usage_empty": empty,
        "usage_search_label": "Search within these circuits",
        "usage_search_id": f"{grid_id}-search",
        "include_descendants": include_descendants,
        "descendant_control_label": (
            "Show circuits tagged with this tag or any child of it"
        ),
        "usage_filters_active": bool(
            query or grid["filtered"] or not include_descendants
        ),
        "usage_reset_url": reset_url,
        "result_count": len(records),
        "reset_sort_url": url_without(request, "sort"),
        "raw_sort": request.GET.get("sort", ""),
        "raw_columns": request.GET.get("columns", ""),
        **table,
    }


def _circuit_rows(records, visible_column_keys):
    rows = []
    for circuit in records:
        cells = {
            "name": {
                "key": "name",
                "value": circuit.name,
                "url": reverse("circuits:detail", args=[circuit.slug]),
            },
            "noise_model": {
                "key": "noise_model",
                "value": circuit.noise_model.name,
                "url": reverse("noise-models:detail", args=[circuit.noise_model.slug]),
            },
            "priors": {
                "key": "priors",
                "value": "Yes" if circuit.noise_model.randomises_priors else "No",
            },
            "css": {"key": "css", "value": "Yes" if circuit.is_css else "No"},
            "code_distance": {
                "key": "code_distance",
                "value": circuit.code_distance_upper_bound,
                "numeric": True,
            },
            "circuit_distance": {
                "key": "circuit_distance",
                "value": circuit.circuit_distance_upper_bound,
                "numeric": True,
            },
            "detectors": {
                "key": "detectors",
                "value": circuit.num_detectors,
                "numeric": True,
            },
            "errors": {
                "key": "errors",
                "value": circuit.num_errors,
                "numeric": True,
            },
            "results": {
                "key": "results",
                "value": circuit.published_result_count,
                "numeric": True,
            },
            "published": {"key": "published", "value": circuit.published_at},
        }
        rows.append({"cells": cells_for_visible_columns(visible_column_keys, cells)})
    return rows


def _circuit_filter_grid(*, grid_id, priors, css, raw, distributions):
    cells = [
        choice_cell(
            key="randomised_priors",
            label="Randomised priors",
            name="priors",
            value=priors,
            choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
        ),
        choice_cell(
            key="css",
            label="CSS",
            name="css",
            value=css,
            choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
        ),
    ]
    for key, label, minimum, maximum, histogram_label in (
        (
            "code_distance",
            "Code distance upper bound",
            "code_d_min",
            "code_d_max",
            "Code-distance upper bounds",
        ),
        (
            "circuit_distance",
            "Circuit distance upper bound",
            "circuit_d_min",
            "circuit_d_max",
            "Circuit-distance upper bounds",
        ),
        (
            "detectors",
            "Detector count",
            "detector_min",
            "detector_max",
            "Detector counts",
        ),
        ("errors", "Error count", "error_min", "error_max", "Error counts"),
    ):
        cells.append(
            range_cell(
                key=key,
                label=label,
                minimum_name=minimum,
                maximum_name=maximum,
                minimum_value=raw[minimum],
                maximum_value=raw[maximum],
                values=distributions[key],
                histogram_label=histogram_label,
            )
        )
    return filter_grid(grid_id=grid_id, title="Circuit filters", cells=cells)
