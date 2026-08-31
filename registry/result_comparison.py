"""Shared HTTP orchestration for exact ResultRecord comparison surfaces."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from urllib.parse import urlencode

from django.http import QueryDict
from django.urls import NoReverseMatch, reverse

from registry.explorer import ColumnSpec, SortKey, parse_sort, table_context
from registry.result_plots import (
    DEFAULT_X_FIELD,
    DEFAULT_Y_FIELD,
    build_result_scatter_plot,
)
from registry.result_query import (
    RESULT_FIELDS,
    ResultQueryError,
    execute_result_query,
    page_result_query,
    parse_result_query,
)

ODATA_OPTIONS = (
    "$filter",
    "$orderby",
    "$select",
    "$top",
    "$skip",
    "$count",
)
PLOT_PARAMETER_ORDER = (
    "plot_x",
    "plot_y",
    "plot_x_scale",
    "plot_y_scale",
    "plot_open",
)
PLOT_PARAMETER_NAMES = set(PLOT_PARAMETER_ORDER)
API_FILTER_PARAMETER_NAMES = {
    "q",
    "algorithm_tag",
    "algorithm_tag_match",
    "skeleton",
    "decoder_priors",
    "probability",
    "code_tag",
    "code_tag_match",
    "experiment_tag",
    "experiment_tag_match",
    "noise_model",
    "circuit_priors",
    "css",
    "code_d_min",
    "code_d_max",
    "circuit_d_min",
    "circuit_d_max",
    "detector_min",
    "detector_max",
    "error_min",
    "error_max",
    "machine_class",
    "scope_circuit",
    "scope_decoder",
    "scope_machine",
    "scope_benchmark",
}
TABLE_TO_PUBLIC_FIELD = {
    "result": "id",
    "decoder": "decoder_name",
    "version": "decoder_version",
    "skeleton": "skeleton_preparation",
    "priors": "prior_preparation",
    "probability": "provides_failure_probability",
    "circuit": "circuit_name",
    "noise_model": "noise_model",
    "machine_class": "machine_class",
    "machine": "machine_slug",
    "shots": "shots_total",
    "score_ler_upper_95_at_5pct_acceptance_v0_1": (
        "score_ler_upper_95_at_5pct_acceptance_v0_1"
    ),
    "t_1000_ns": "t_1000_ns",
    "score_brier_loss_upper_95_v0_1": "score_brier_loss_upper_95_v0_1",
    "reproduction": "reproduction_status",
    "published": "published_at",
}
PUBLIC_TO_TABLE_FIELD = {
    public: table for table, public in TABLE_TO_PUBLIC_FIELD.items()
}
NUMERIC_PLOT_FIELDS = tuple(
    field for field in RESULT_FIELDS if field.kind in {"integer", "decimal"}
)


def result_comparison_context(
    request,
    *,
    queryset,
    columns: Sequence[ColumnSpec],
    default_sort: tuple[tuple[str, str], ...],
    plot_id: str,
    point_context: str,
    api_parameters: Iterable[tuple[str, object]] = (),
) -> dict[str, object]:
    """Apply one query to the table, plot, and machine-readable links."""

    sort_keys = parse_sort(request.GET.get("sort", ""), columns, default_sort)
    scripted_text = request.GET.get("odata", "").strip()
    last_scripted_text = request.GET.get("last_odata", "").strip()
    query_error = None
    scripted_query = None
    scripted_source = _scripted_source(request.GET, scripted_text)
    if scripted_source is not None:
        try:
            scripted_query = parse_result_query(scripted_source)
        except ResultQueryError as error:
            query_error = error
            if last_scripted_text:
                try:
                    scripted_query = parse_result_query(
                        QueryDict(last_scripted_text.removeprefix("?"))
                    )
                except ResultQueryError:
                    scripted_query = None

    if scripted_query is None:
        scripted_query = parse_result_query(_query_from_table_sort(sort_keys))

    result_queryset = execute_result_query(scripted_query, queryset=queryset)
    result_count = result_queryset.count()
    results = page_result_query(result_queryset, scripted_query)

    if query_error is None and scripted_source is not None:
        visible_script_sorts = _table_sort_keys(scripted_query.order_by)
        if visible_script_sorts:
            sort_keys = visible_script_sorts

    table = table_context(
        request,
        columns,
        sort_keys,
        clear_on_sort=("odata", "last_odata", *ODATA_OPTIONS),
    )
    x_field, y_field, x_scale, y_scale, plot_configuration_error = _plot_options(
        request.GET
    )
    json_url, csv_url = _api_urls(api_parameters, scripted_query.canonical)
    plot = build_result_scatter_plot(
        results,
        x_field=x_field,
        y_field=y_field,
        x_scale=x_scale,
        y_scale=y_scale,
        plot_id=plot_id,
        point_context=point_context,
    )
    plot.update(
        {
            "axis_options": [
                {
                    "name": field.name,
                    "label": field.label,
                    "unit": field.unit,
                }
                for field in NUMERIC_PLOT_FIELDS
            ],
            "selected_x_field": x_field,
            "selected_y_field": y_field,
            "selected_x_scale": x_scale,
            "selected_y_scale": y_scale,
            "configuration_error": plot_configuration_error,
            "json_url": json_url,
            "csv_url": csv_url,
            "schema_url": _reverse_or_default(
                "results:api-schema", "/results/api/v0.1/schema.json"
            ),
            "action_url": request.path,
            "preserved_parameters": _preserved_plot_parameters(request.GET),
            "is_open": bool(
                request.GET.get("plot_open")
                or any(name in request.GET for name in PLOT_PARAMETER_NAMES)
            ),
            "download_filename": f"circuit-bench-{plot_id}.svg",
        }
    )
    return {
        "results": results,
        "result_count": result_count,
        "ordered_result_ids": [str(result.id) for result in results],
        "result_plot": plot,
        "plot_control_parameters": [
            (name, value)
            for name in PLOT_PARAMETER_ORDER
            if name != "plot_open"
            for value in request.GET.getlist(name)
        ],
        "scripted_query_text": scripted_text,
        "scripted_query_active": scripted_source is not None,
        "last_valid_scripted_query": (
            scripted_text
            if scripted_source is not None and query_error is None
            else last_scripted_text
        ),
        "scripted_query_status": _query_status(
            query_error,
            scripted_source is not None,
            result_count,
        ),
        "json_url": json_url,
        "csv_url": csv_url,
        "reset_sort_url": _url_without(request, "sort"),
        "raw_sort": request.GET.get("sort", ""),
        "raw_columns": request.GET.get("columns", ""),
        **table,
    }


def api_parameters_from_request(parameters, *, overrides=()):
    """Copy only public structured result filters, then apply scoped overrides."""

    overridden_names = {name for name, _value in overrides}
    copied = [
        (name, value)
        for name in parameters
        if name in API_FILTER_PARAMETER_NAMES and name not in overridden_names
        for value in parameters.getlist(name)
    ]
    copied.extend((name, value) for name, value in overrides if value not in {None, ""})
    return copied


def _scripted_source(parameters, scripted_text):
    if scripted_text:
        return QueryDict(scripted_text.removeprefix("?"))
    if any(name in parameters for name in ODATA_OPTIONS):
        return parameters
    return None


def _query_from_table_sort(sort_keys):
    query = QueryDict("", mutable=True)
    query["$orderby"] = ",".join(
        f"{TABLE_TO_PUBLIC_FIELD[item.key]} {item.direction}" for item in sort_keys
    )
    query["$top"] = "1000"
    return query


def _table_sort_keys(order_by):
    return tuple(
        SortKey(PUBLIC_TO_TABLE_FIELD[name], direction)
        for name, direction in order_by
        if name in PUBLIC_TO_TABLE_FIELD
    )


def _query_status(error, scripted, result_count):
    if error is not None:
        position = (
            f" at character {error.position}" if error.position is not None else ""
        )
        return {
            "kind": "error",
            "message": f"{error.message}{position} Last valid results remain visible.",
        }
    if scripted:
        return {
            "kind": "success",
            "message": (
                f"Valid ResultRecord 0.1 query · {result_count} matching results."
            ),
        }
    plural = "s" if result_count != 1 else ""
    return {
        "kind": "plain",
        "message": (
            f"{result_count} exact published result{plural} · "
            "filters, query, plot, and sort describe one population."
        ),
    }


def _plot_options(parameters):
    error_messages = []
    x_field = parameters.get("plot_x", DEFAULT_X_FIELD).strip()
    y_field = parameters.get("plot_y", DEFAULT_Y_FIELD).strip()
    if x_field not in {field.name for field in NUMERIC_PLOT_FIELDS}:
        error_messages.append(f"Unknown numeric x-axis field: {x_field}")
        x_field = DEFAULT_X_FIELD
    if y_field not in {field.name for field in NUMERIC_PLOT_FIELDS}:
        error_messages.append(f"Unknown numeric y-axis field: {y_field}")
        y_field = DEFAULT_Y_FIELD
    x_scale = parameters.get("plot_x_scale", "linear").strip().lower()
    y_scale = parameters.get("plot_y_scale", "linear").strip().lower()
    if x_scale not in {"linear", "log"}:
        error_messages.append(f"Unknown x-axis scale: {x_scale}")
        x_scale = "linear"
    if y_scale not in {"linear", "log"}:
        error_messages.append(f"Unknown y-axis scale: {y_scale}")
        y_scale = "linear"
    return x_field, y_field, x_scale, y_scale, "; ".join(error_messages)


def _api_urls(parameters, canonical):
    query_parameters = list(parameters)
    query_parameters.extend(tuple(part.split("=", 1)) for part in canonical.split("&"))
    encoded = urlencode(query_parameters)
    json_path = _reverse_or_default(
        "results:api-json", "/results/api/v0.1/results.json"
    )
    csv_path = _reverse_or_default("results:api-csv", "/results/api/v0.1/results.csv")
    return (
        f"{json_path}?{encoded}",
        f"{csv_path}?{encoded}",
    )


def _reverse_or_default(name, default):
    try:
        return reverse(name)
    except NoReverseMatch:
        return default


def _preserved_plot_parameters(parameters):
    excluded = {*PLOT_PARAMETER_NAMES, "page"}
    return [
        (name, value)
        for name in parameters
        if name not in excluded
        for value in parameters.getlist(name)
    ]


def _url_without(request, *names):
    query = request.GET.copy()
    for name in names:
        query.pop(name, None)
    encoded = query.urlencode()
    return f"{request.path}?{encoded}" if encoded else request.path
