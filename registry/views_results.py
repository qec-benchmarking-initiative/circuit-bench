from django.shortcuts import render
from django.urls import reverse

from registry.explorer import (
    ColumnSpec,
    apply_sort,
    cells_for_visible_columns,
    parse_nonnegative_int,
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
from registry.result_tables import result_cell_map
from registry.services.decoders import catalogue_algorithm_tags
from registry.services.filter_options import public_circuit_filter_options
from registry.services.results import public_result_catalogue

RESULT_COLUMNS = (
    ColumnSpec("result", "Result UUID", default_visible=False),
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
    ColumnSpec("scores", "Evaluator scores", sortable=False),
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
    "reproduction": "reproduction_status",
    "published": "published_at",
}


def result_list(request):
    query = request.GET.get("q", "").strip()
    algorithm_tags = _selected(request, "algorithm_tag")
    algorithm_tag_match = _match(request, "algorithm_tag_match")
    skeleton = request.GET.get("skeleton", "").strip()
    decoder_priors = request.GET.get("decoder_priors", "").strip()
    probability = request.GET.get("probability", "").strip()
    code_tags = _selected(request, "code_tag")
    code_tag_match = _match(request, "code_tag_match")
    experiment_tags = _selected(request, "experiment_tag")
    experiment_tag_match = _match(request, "experiment_tag_match")
    noise_model = request.GET.get("noise_model", "").strip()
    circuit_priors = request.GET.get("circuit_priors", "").strip()
    is_css = request.GET.get("css", "").strip()
    machine_class = request.GET.get("machine_class", "").strip()
    valid_machine_classes = {value for value, _label in Machine.MachineClass.choices}
    if machine_class not in {*valid_machine_classes, "unreported"}:
        machine_class = ""
    raw_ranges = {
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
    parsed_ranges = {
        name: parse_nonnegative_int(value) for name, value in raw_ranges.items()
    }
    sort_keys = parse_sort(
        request.GET.get("sort", ""), RESULT_COLUMNS, (("published", "desc"),)
    )
    results = list(
        apply_sort(
            public_result_catalogue(
                query=query,
                algorithm_tag_slugs=algorithm_tags,
                algorithm_tag_match=algorithm_tag_match,
                skeleton_preparation=skeleton,
                decoder_priors_preparation=decoder_priors,
                probability_output=probability,
                code_tag_slugs=code_tags,
                code_tag_match=code_tag_match,
                experiment_tag_slugs=experiment_tags,
                experiment_tag_match=experiment_tag_match,
                noise_model_slug=noise_model,
                randomises_priors=circuit_priors,
                is_css=is_css,
                code_distance_min=parsed_ranges["code_d_min"],
                code_distance_max=parsed_ranges["code_d_max"],
                circuit_distance_min=parsed_ranges["circuit_d_min"],
                circuit_distance_max=parsed_ranges["circuit_d_max"],
                detector_min=parsed_ranges["detector_min"],
                detector_max=parsed_ranges["detector_max"],
                error_min=parsed_ranges["error_min"],
                error_max=parsed_ranges["error_max"],
                machine_class=machine_class,
            ),
            sort_keys,
            RESULT_SORT_FIELDS,
        )
    )
    table = table_context(request, RESULT_COLUMNS, sort_keys)
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
                noise_models=circuit_options["noise_models"],
                noise_model_slug=noise_model,
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
            "result_count": len(results),
            "table_rows": rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            "filters_active": bool(
                query
                or algorithm_tags
                or skeleton
                or decoder_priors
                or probability
                or code_tags
                or experiment_tags
                or noise_model
                or circuit_priors
                or is_css
                or machine_class
                or any(value is not None for value in parsed_ranges.values())
            ),
            **table,
        },
    )


def _selected(request, name: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value.strip() for value in request.GET.getlist(name) if value.strip()
        )
    )


def _match(request, name: str) -> str:
    value = request.GET.get(name, "all").strip()
    return value if value in {"all", "any"} else "all"
