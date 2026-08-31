from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from registry.explorer import (
    ColumnSpec,
    cells_for_visible_columns,
)
from registry.filter_grids import algorithm_grid as build_algorithm_grid
from registry.filter_grids import circuit_grid as build_circuit_grid
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

MACHINE_RESULT_COLUMNS = (
    ColumnSpec("result", "Result UUID", default_visible=False),
    ColumnSpec("decoder", "Decoder"),
    ColumnSpec("version", "Version"),
    ColumnSpec("algorithm_tags", "Algorithm tags", sortable=False),
    ColumnSpec("circuit", "Circuit"),
    ColumnSpec("noise_model", "Noise model"),
    ColumnSpec("shots", "Shots", numeric=True, default_direction="desc"),
    *RESULT_METRIC_COLUMNS,
    ColumnSpec("scores", "Evaluator scores", sortable=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)


def machine_detail(request, slug):
    machine = get_object_or_404(
        Machine.objects.select_related("schema_release", "submitted_by"),
        slug=slug,
        state__in=["published", "withdrawn"],
    )
    filter_state = result_filter_state(request.GET)
    filters = filter_state.service_arguments
    noise_model_picker = record_picker_context(
        "noise-models", filters["noise_model_slugs"]
    )
    filters["noise_model_slugs"] = tuple(
        record["identifier"] for record in noise_model_picker["selected_records"]
    )
    comparison = result_comparison_context(
        request,
        queryset=public_result_catalogue(machine=machine, **filters),
        columns=MACHINE_RESULT_COLUMNS,
        default_sort=(("published", "desc"),),
        plot_id="machine-results-scatter",
        point_context="machine",
        api_parameters=api_parameters_from_request(
            request.GET,
            overrides=(("scope_machine", machine.slug),),
        ),
    )
    results = comparison["results"]
    detail_url = reverse("machines:detail", args=[machine.slug])
    rows = [
        {
            "cells": cells_for_visible_columns(
                comparison["visible_column_keys"],
                result_cell_map(result, filter_url=detail_url),
            )
        }
        for result in results
    ]
    algorithm_tags = list(catalogue_algorithm_tags())
    circuit_options = public_circuit_filter_options()
    filters_active = bool(
        filters["query"]
        or filters["algorithm_tag_slugs"]
        or filters["skeleton_preparation"]
        or filters["decoder_priors_preparation"]
        or filters["probability_output"]
        or filters["code_tag_slugs"]
        or filters["experiment_tag_slugs"]
        or filters["noise_model_slugs"]
        or filters["randomises_priors"]
        or filters["is_css"]
        or filters["machine_class"]
        or any(value is not None for value in filter_state.parsed_ranges.values())
        or comparison["scripted_query_active"]
    )
    return render(
        request,
        "machines/detail.html",
        {
            "machine": machine,
            "entity": {
                "kind": "Machine",
                "name": machine.slug,
                "version": None,
                "status": machine.state,
                "status_label": machine.get_state_display(),
                "tags": [],
            },
            "metadata": [
                {"label": "Stable slug", "value": machine.slug},
                {"label": "Machine UUID", "value": machine.id},
                {
                    "label": "Machine class",
                    "value": machine.get_machine_class_display(),
                },
                {"label": "Evidence", "value": machine.get_status_display()},
                {"label": "Schema", "value": machine.schema_release.public_name},
                {"label": "Submitted by", "value": machine.submitted_by.display_name},
                {"label": "Created", "value": machine.created_at},
                {"label": "Published", "value": machine.published_at},
            ],
            "algorithm_filter_grid": build_algorithm_grid(
                grid_id="machine-result-algorithm-filters",
                picker_id="machine-result-algorithm-tags",
                tags=algorithm_tags,
                selected_tags=filters["algorithm_tag_slugs"],
                tag_match=filters["algorithm_tag_match"],
                skeleton=filters["skeleton_preparation"],
                priors=filters["decoder_priors_preparation"],
                probability=filters["probability_output"],
                tag_name="algorithm_tag",
                tag_match_name="algorithm_tag_match",
                priors_name="decoder_priors",
            ),
            "circuit_filter_grid": build_circuit_grid(
                grid_id="machine-result-circuit-filters",
                code_tags=circuit_options["code_tags"],
                selected_code_tags=filters["code_tag_slugs"],
                code_tag_match=filters["code_tag_match"],
                experiment_tags=circuit_options["experiment_tags"],
                selected_experiment_tags=filters["experiment_tag_slugs"],
                experiment_tag_match=filters["experiment_tag_match"],
                noise_model_picker=noise_model_picker,
                randomises_priors=filters["randomises_priors"],
                is_css=filters["is_css"],
                raw_values=filter_state.raw_ranges,
                distributions=circuit_options["distributions"],
                priors_name="circuit_priors",
            ),
            "result_filters_active": filters_active,
            "result_reset_url": detail_url,
            "result_rows": rows,
            **comparison,
        },
    )
