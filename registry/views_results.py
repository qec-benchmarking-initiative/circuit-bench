from django.shortcuts import render
from django.urls import reverse

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
from registry.result_comparison import (
    api_parameters_from_request,
    result_comparison_context,
)
from registry.result_request import result_filter_state
from registry.result_tables import (
    RESULT_METRIC_COLUMNS,
    result_cell_map,
)
from registry.services.decoders import catalogue_algorithm_tags
from registry.services.filter_options import public_circuit_filter_options
from registry.services.results import public_result_catalogue
from registry.table_controls import (
    ColumnSpec,
    cells_for_visible_columns,
)

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
    ColumnSpec("scores", "Evaluator scores", sortable=False, default_visible=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
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
    comparison = result_comparison_context(
        request,
        queryset=public_result_catalogue(**filters),
        columns=RESULT_COLUMNS,
        default_sort=(("published", "desc"),),
        plot_id="all-results-scatter",
        point_context="results",
        api_parameters=api_parameters_from_request(request.GET),
    )
    results = comparison["results"]
    list_url = reverse("results:list")
    rows = [
        {
            "cells": cells_for_visible_columns(
                comparison["visible_column_keys"],
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
            "table_rows": rows,
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
                or comparison["scripted_query_active"]
            ),
            **comparison,
        },
    )
