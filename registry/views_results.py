from urllib.parse import urlencode

from django.http import QueryDict
from django.shortcuts import render
from django.urls import reverse

from registry.explorer import (
    ColumnSpec,
    SortKey,
    cells_for_visible_columns,
    parse_sort,
    table_context,
    url_without,
)
from registry.filter_grids import (
    algorithm_grid as build_algorithm_grid,
)
from registry.filter_grids import (
    circuit_grid as build_circuit_grid,
)
from registry.filter_grids import (
    machine_grid as build_machine_grid,
)
from registry.models import Machine
from registry.record_pickers import record_picker_context
from registry.result_plots import build_result_scatter_plot
from registry.result_query import (
    ResultQueryError,
    execute_result_query,
    page_result_query,
    parse_result_query,
)
from registry.result_request import result_filter_state
from registry.result_tables import (
    RESULT_METRIC_COLUMNS,
    RESULT_METRIC_SORT_FIELDS,
    result_cell_map,
    with_result_metrics,
)
from registry.services.decoders import catalogue_algorithm_tags
from registry.services.filter_options import public_circuit_filter_options
from registry.services.results import public_result_catalogue

RESULT_COLUMNS = (
    ColumnSpec("result", "Result", help_text="Exact result UUID"),
    ColumnSpec("decoder", "Decoder"),
    ColumnSpec("version", "Version"),
    ColumnSpec("algorithm_tags", "Algorithm tags", sortable=False),
    ColumnSpec("circuit", "Circuit"),
    ColumnSpec("code_tags", "Code tags", sortable=False, default_visible=False),
    ColumnSpec(
        "experiment_tags", "Experiment tags", sortable=False, default_visible=False
    ),
    ColumnSpec("noise_model", "Noise model"),
    ColumnSpec("machine_class", "Machine type"),
    ColumnSpec("machine", "Machine"),
    ColumnSpec("shots", "Shots", numeric=True, default_direction="desc"),
    *RESULT_METRIC_COLUMNS,
    ColumnSpec(
        "scores", "Evaluator scores", sortable=False, default_visible=False
    ),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)

RESULT_SORT_FIELDS = {
    "result": "id",
    "decoder": "decoder_version__name",
    "version": "decoder_version__version",
    "circuit": "circuit_revision__name",
    "noise_model": "circuit_revision__noise_model__name",
    "machine_class": "machine__machine_class",
    "machine": "machine__slug",
    "shots": "shots_total",
    **RESULT_METRIC_SORT_FIELDS,
    "reproduction": "reproduction_status",
    "published": "published_at",
}

TABLE_TO_PUBLIC_FIELD = {
    "result": "id",
    "decoder": "decoder_name",
    "version": "decoder_version",
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
ODATA_OPTIONS = (
    "$filter",
    "$orderby",
    "$select",
    "$top",
    "$skip",
    "$count",
)


def result_list(request):
    filter_state = result_filter_state(request.GET)
    filters = filter_state.service_arguments
    query = filters["query"]
    algorithm_tags = filters["algorithm_tag_slugs"]
    algorithm_tag_match = filters["algorithm_tag_match"]
    skeleton = filters["skeleton_preparation"]
    decoder_priors = filters["decoder_priors_preparation"]
    probability = filters["probability_output"]
    code_tags = filters["code_tag_slugs"]
    code_tag_match = filters["code_tag_match"]
    experiment_tags = filters["experiment_tag_slugs"]
    experiment_tag_match = filters["experiment_tag_match"]
    noise_model_picker = record_picker_context(
        "noise-models", filters["noise_model_slugs"]
    )
    noise_models = tuple(
        record["identifier"] for record in noise_model_picker["selected_records"]
    )
    filters["noise_model_slugs"] = noise_models
    circuit_priors = filters["randomises_priors"]
    is_css = filters["is_css"]
    machine_class = filters["machine_class"]
    raw_ranges = filter_state.raw_ranges
    parsed_ranges = filter_state.parsed_ranges
    sort_keys = parse_sort(
        request.GET.get("sort", ""), RESULT_COLUMNS, (("published", "desc"),)
    )
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

    base_results = with_result_metrics(public_result_catalogue(**filters))
    result_queryset = execute_result_query(scripted_query, queryset=base_results)
    result_count = result_queryset.count()
    results = page_result_query(result_queryset, scripted_query)
    result_plot = build_result_scatter_plot(results)

    if query_error is None and scripted_source is not None:
        visible_script_sorts = _table_sort_keys(scripted_query.order_by)
        if visible_script_sorts:
            sort_keys = visible_script_sorts

    table = table_context(
        request,
        RESULT_COLUMNS,
        sort_keys,
        clear_on_sort=("odata", "last_odata", *ODATA_OPTIONS),
    )
    list_url = reverse("results:list")
    rows = [
        {
            "cells": cells_for_visible_columns(
                table["visible_column_keys"],
                result_cell_map(result, filter_url=list_url),
            )
        }
        for result in results
    ]
    algorithm_filter_tags = list(catalogue_algorithm_tags())
    circuit_options = public_circuit_filter_options()
    return render(
        request,
        "results/list.html",
        {
            "query": query,
            "algorithm_filter_grid": build_algorithm_grid(
                grid_id="result-algorithm-filters",
                picker_id="result-algorithm-tags",
                tags=algorithm_filter_tags,
                selected_tags=algorithm_tags,
                tag_match=algorithm_tag_match,
                skeleton=skeleton,
                priors=decoder_priors,
                probability=probability,
                tag_name="algorithm_tag",
                tag_match_name="algorithm_tag_match",
                priors_name="decoder_priors",
            ),
            "circuit_filter_grid": build_circuit_grid(
                grid_id="result-circuit-filters",
                code_tags=circuit_options["code_tags"],
                selected_code_tags=code_tags,
                code_tag_match=code_tag_match,
                experiment_tags=circuit_options["experiment_tags"],
                selected_experiment_tags=experiment_tags,
                experiment_tag_match=experiment_tag_match,
                noise_model_picker=noise_model_picker,
                randomises_priors=circuit_priors,
                is_css=is_css,
                raw_values=raw_ranges,
                distributions=circuit_options["distributions"],
                priors_name="circuit_priors",
            ),
            "machine_filter_grid": build_machine_grid(
                grid_id="result-machine-filters",
                machine_classes=Machine.MachineClass.choices,
                selected_machine_class=machine_class,
            ),
            "result_count": result_count,
            "ordered_result_ids": [str(result.id) for result in results],
            "result_plot": result_plot,
            "table_rows": rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            "scripted_query_text": scripted_text,
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
            "json_url": _api_url(request, "results:api-json", scripted_query.canonical),
            "csv_url": _api_url(request, "results:api-csv", scripted_query.canonical),
            "filters_active": bool(
                query
                or algorithm_tags
                or skeleton
                or decoder_priors
                or probability
                or code_tags
                or experiment_tags
                or noise_models
                or circuit_priors
                or is_css
                or machine_class
                or any(value is not None for value in parsed_ranges.values())
                or scripted_source is not None
            ),
            **table,
        },
    )


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
            "filters, columns, and sort are URL-backed."
        ),
    }


def _api_url(request, route_name, canonical):
    parameters = [
        (key, value)
        for key in request.GET
        if not key.startswith("$")
        and key not in {"odata", "last_odata", "sort", "columns", "page"}
        for value in request.GET.getlist(key)
    ]
    parameters.extend(tuple(part.split("=", 1)) for part in canonical.split("&"))
    return f"{reverse(route_name)}?{urlencode(parameters)}"
