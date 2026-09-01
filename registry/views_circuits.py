from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from registry.curation import (
    CatalogueKind,
    CatalogueOrderingMode,
    apply_featured_ordering,
    apply_search_relevance,
    ordering_metadata,
    select_catalogue_ordering,
)
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
from registry.record_pickers import record_picker_context
from registry.result_comparison import (
    api_parameters_from_request,
    result_comparison_context,
)
from registry.result_tables import (
    RESULT_METRIC_COLUMNS,
    result_cell_map,
)
from registry.services.circuits import (
    circuit_catalogue,
    circuit_detail_queryset,
    circuit_result_leaderboard,
    inherited_circuit_description,
)
from registry.services.decoders import catalogue_algorithm_tags
from registry.services.filter_options import public_circuit_filter_options

CIRCUIT_RESULT_COLUMNS = (
    ColumnSpec("decoder", "Decoder"),
    ColumnSpec("version", "Version"),
    ColumnSpec("algorithm_tags", "Algorithm tags", sortable=False),
    ColumnSpec(
        "skeleton",
        "Skeleton preparation",
        default_visible=False,
    ),
    ColumnSpec("priors", "Prior preparation", default_visible=False),
    ColumnSpec("probability", "Failure probability", default_visible=False),
    ColumnSpec("machine_class", "Machine type"),
    ColumnSpec("machine", "Machine"),
    ColumnSpec("shots", "Shots", numeric=True, default_direction="desc"),
    *RESULT_METRIC_COLUMNS,
    ColumnSpec("scores", "Evaluator scores", sortable=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)


def circuit_list(request):
    query = request.GET.get("q", "").strip()
    legacy_tag = request.GET.get("tag", "").strip()
    code_tags = tuple(
        dict.fromkeys(
            value.strip() for value in request.GET.getlist("code_tag") if value.strip()
        )
    )
    experiment_tags = tuple(
        dict.fromkeys(
            value.strip()
            for value in request.GET.getlist("experiment_tag")
            if value.strip()
        )
    )
    legacy_namespace, separator, legacy_slug = legacy_tag.partition(":")
    if separator and legacy_namespace == "code" and legacy_slug not in code_tags:
        code_tags = (*code_tags, legacy_slug)
    if (
        separator
        and legacy_namespace == "experiment"
        and legacy_slug not in experiment_tags
    ):
        experiment_tags = (*experiment_tags, legacy_slug)
    code_tag_match = request.GET.get("code_tag_match", "all").strip()
    if code_tag_match not in {"all", "any"}:
        code_tag_match = "all"
    experiment_tag_match = request.GET.get("experiment_tag_match", "all").strip()
    if experiment_tag_match not in {"all", "any"}:
        experiment_tag_match = "all"
    requested_noise_models = tuple(
        dict.fromkeys(
            value.strip()
            for value in request.GET.getlist("noise_model")
            if value.strip()
        )
    )
    noise_model_picker = record_picker_context("noise-models", requested_noise_models)
    noise_models = tuple(
        record["identifier"] for record in noise_model_picker["selected_records"]
    )

    filters = {
        "noise_model_slugs": noise_models,
        "randomises_priors": request.GET.get("priors", "").strip(),
        "is_css": request.GET.get("css", "").strip(),
        "code_distance_min": parse_nonnegative_int(request.GET.get("code_d_min", "")),
        "code_distance_max": parse_nonnegative_int(request.GET.get("code_d_max", "")),
        "circuit_distance_min": parse_nonnegative_int(
            request.GET.get("circuit_d_min", "")
        ),
        "circuit_distance_max": parse_nonnegative_int(
            request.GET.get("circuit_d_max", "")
        ),
        "detector_min": parse_nonnegative_int(request.GET.get("detector_min", "")),
        "detector_max": parse_nonnegative_int(request.GET.get("detector_max", "")),
        "error_min": parse_nonnegative_int(request.GET.get("error_min", "")),
        "error_max": parse_nonnegative_int(request.GET.get("error_max", "")),
    }
    columns = (
        ColumnSpec("name", "Circuit"),
        ColumnSpec("code_tags", "Code tags", sortable=False),
        ColumnSpec("experiment_tags", "Experiment tags", sortable=False),
        ColumnSpec("noise_model", "Noise model"),
        ColumnSpec("priors", "Randomised priors"),
        ColumnSpec("css", "CSS"),
        ColumnSpec("code_distance", "Code d ≤", numeric=True),
        ColumnSpec("circuit_distance", "Circuit d ≤", numeric=True),
        ColumnSpec("detectors", "Detectors", numeric=True),
        ColumnSpec("errors", "Errors", numeric=True),
        ColumnSpec("results", "Results", numeric=True, default_direction="desc"),
        ColumnSpec("rounds", "Rounds", numeric=True, default_visible=False),
        ColumnSpec("observables", "Observables", numeric=True, default_visible=False),
        ColumnSpec(
            "published", "Published", default_direction="desc", default_visible=False
        ),
    )
    raw_sort = request.GET.get("sort", "")
    ordering_selection = select_catalogue_ordering(
        search_query=query,
        raw_sort=raw_sort,
    )
    sort_keys = parse_sort(raw_sort, columns, (("name", "asc"),))
    circuit_queryset = circuit_catalogue(
        query=query,
        tag=legacy_tag,
        code_tag_slugs=code_tags,
        experiment_tag_slugs=experiment_tags,
        code_tag_match=code_tag_match,
        experiment_tag_match=experiment_tag_match,
        **filters,
    )
    if ordering_selection.mode == CatalogueOrderingMode.MANUAL:
        circuit_queryset = apply_sort(
            circuit_queryset,
            sort_keys,
            {
                "name": "name",
                "noise_model": "noise_model__name",
                "priors": "noise_model__randomises_priors",
                "css": "is_css",
                "code_distance": "code_distance_upper_bound",
                "circuit_distance": "circuit_distance_upper_bound",
                "detectors": "num_detectors",
                "errors": "num_errors",
                "results": "published_result_count",
                "rounds": "rounds",
                "observables": "num_observables",
                "published": "published_at",
            },
        )
    elif ordering_selection.mode == CatalogueOrderingMode.SEARCH_RELEVANCE:
        sort_keys = ()
        circuit_queryset = apply_search_relevance(
            circuit_queryset,
            CatalogueKind.CIRCUIT,
            ordering_selection.search_query,
        )
    else:
        sort_keys = ()
        circuit_queryset = apply_featured_ordering(
            circuit_queryset, CatalogueKind.CIRCUIT
        )
    circuits = list(circuit_queryset)
    filter_options = public_circuit_filter_options()
    code_filter_tags = filter_options["code_tags"]
    experiment_filter_tags = filter_options["experiment_tags"]
    raw_values = {
        key: request.GET.get(key, "")
        for key in (
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
    distributions = filter_options["distributions"]
    table = table_context(request, columns, sort_keys)
    discovery_ordering = ordering_metadata(
        ordering_selection, CatalogueKind.CIRCUIT
    ).as_context()
    if ordering_selection.mode != CatalogueOrderingMode.MANUAL:
        table["sort_summary"] = discovery_ordering["label"]
    list_url = reverse("circuits:list")
    rows = []
    for circuit in circuits:
        cell_by_key = {
            "name": {
                "key": "name",
                "value": circuit.name,
                "url": reverse("circuits:detail", args=[circuit.slug]),
            },
            "code_tags": {
                "key": "code_tags",
                "tags": [
                    {
                        "label": tag.label,
                        "url": f"{list_url}?{urlencode({'code_tag': tag.slug})}",
                        "display_color": tag.display_color,
                    }
                    for tag in circuit.code_tags.all()
                ],
            },
            "experiment_tags": {
                "key": "experiment_tags",
                "tags": [
                    {
                        "label": tag.label,
                        "url": f"{list_url}?{urlencode({'experiment_tag': tag.slug})}",
                        "display_color": tag.display_color,
                    }
                    for tag in circuit.experiment_tags.all()
                ],
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
            "errors": {"key": "errors", "value": circuit.num_errors, "numeric": True},
            "results": {
                "key": "results",
                "value": circuit.published_result_count,
                "numeric": True,
            },
            "rounds": {"key": "rounds", "value": circuit.rounds, "numeric": True},
            "observables": {
                "key": "observables",
                "value": circuit.num_observables,
                "numeric": True,
            },
            "published": {"key": "published", "value": circuit.published_at},
        }
        rows.append(
            {
                "cells": cells_for_visible_columns(
                    table["visible_column_keys"], cell_by_key
                )
            }
        )
    return render(
        request,
        "circuits/list.html",
        {
            "circuits": circuits,
            "code_filter_tags": code_filter_tags,
            "experiment_filter_tags": experiment_filter_tags,
            "circuit_filter_grid": build_circuit_grid(
                grid_id="circuit-filters",
                code_tags=code_filter_tags,
                selected_code_tags=code_tags,
                code_tag_match=code_tag_match,
                experiment_tags=experiment_filter_tags,
                selected_experiment_tags=experiment_tags,
                experiment_tag_match=experiment_tag_match,
                noise_model_picker=noise_model_picker,
                randomises_priors=filters["randomises_priors"],
                is_css=filters["is_css"],
                raw_values=raw_values,
                distributions=distributions,
            ),
            "query": query,
            "selected_tag": legacy_tag,
            "selected_code_tags": code_tags,
            "selected_experiment_tags": experiment_tags,
            "selected_noise_models": noise_models,
            "code_tag_match": code_tag_match,
            "experiment_tag_match": experiment_tag_match,
            "filters": filters,
            "raw_values": raw_values,
            "result_count": len(circuits),
            "table_rows": rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            "discovery_ordering": discovery_ordering,
            "filters_active": bool(
                query
                or legacy_tag
                or code_tags
                or experiment_tags
                or any(filters.values())
            ),
            **table,
        },
    )


def circuit_detail(request, slug):
    circuit = get_object_or_404(circuit_detail_queryset(), slug=slug)
    list_url = reverse("circuits:list")
    detail_url = reverse("circuits:detail", args=[circuit.slug])
    selected_tags = tuple(
        dict.fromkeys(tag.strip() for tag in request.GET.getlist("tag") if tag.strip())
    )
    tag_match = request.GET.get("tag_match", "all").strip()
    if tag_match not in {"all", "any"}:
        tag_match = "all"
    skeleton_preparation = request.GET.get("skeleton", "").strip()
    priors_preparation = request.GET.get("priors", "").strip()
    probability_output = request.GET.get("probability", "").strip()
    machine_class = request.GET.get("machine_class", "").strip()
    valid_machine_classes = {value for value, _label in Machine.MachineClass.choices}
    if machine_class not in {*valid_machine_classes, "unreported"}:
        machine_class = ""
    comparison = result_comparison_context(
        request,
        queryset=circuit_result_leaderboard(
            circuit=circuit,
            tag_slugs=selected_tags,
            tag_match=tag_match,
            skeleton_preparation=skeleton_preparation,
            priors_preparation=priors_preparation,
            probability_output=probability_output,
            machine_class=machine_class,
        ),
        columns=CIRCUIT_RESULT_COLUMNS,
        default_sort=(("decoder", "asc"),),
        plot_id="circuit-results-scatter",
        point_context="circuit",
        api_parameters=api_parameters_from_request(
            request.GET,
            overrides=(
                ("scope_circuit", circuit.slug),
                *(("algorithm_tag", tag) for tag in selected_tags),
                ("algorithm_tag_match", tag_match if selected_tags else ""),
                ("skeleton", skeleton_preparation),
                ("decoder_priors", priors_preparation),
                ("probability", probability_output),
                ("machine_class", machine_class),
            ),
        ),
    )
    results = comparison["results"]
    result_rows = []
    for result in results:
        decoder = result.decoder_version
        cell_by_key = result_cell_map(
            result,
            filter_url=detail_url,
            algorithm_tag_name="tag",
        )
        cell_by_key.update(
            {
                "skeleton": {
                    "key": "skeleton",
                    "value": decoder.get_circuit_skeleton_preparation_display(),
                },
                "priors": {
                    "key": "priors",
                    "value": decoder.get_circuit_priors_preparation_display(),
                },
                "probability": {
                    "key": "probability",
                    "value": "Yes" if decoder.provides_failure_probability else "No",
                },
            }
        )
        result_rows.append(
            {
                "cells": cells_for_visible_columns(
                    comparison["visible_column_keys"], cell_by_key
                )
            }
        )
    artifacts = [
        ("Sampling circuit", circuit.sampling_circuit_artifact),
        ("Detector error model", circuit.detector_error_model_artifact),
        ("Manifest", circuit.manifest_artifact),
    ]
    algorithm_filter_tags = list(catalogue_algorithm_tags())
    return render(
        request,
        "circuits/detail.html",
        {
            "circuit": circuit,
            "description": inherited_circuit_description(circuit),
            "artifacts": artifacts,
            "entity": {
                "kind": "Circuit revision",
                "name": circuit.name,
                "version": None,
                "status": circuit.state,
                "status_label": circuit.get_state_display(),
                "tags": [
                    *[
                        {
                            "label": tag.label,
                            "status": tag.status,
                            "display_color": tag.display_color,
                            "url": (
                                f"{list_url}?{urlencode({'tag': f'code:{tag.slug}'})}"
                            ),
                        }
                        for tag in circuit.code_tags.all()
                    ],
                    *[
                        {
                            "label": tag.label,
                            "status": tag.status,
                            "display_color": tag.display_color,
                            "url": (
                                f"{list_url}?"
                                f"{urlencode({'tag': f'experiment:{tag.slug}'})}"
                            ),
                        }
                        for tag in circuit.experiment_tags.all()
                    ],
                ],
            },
            "previous_revision": (
                circuit.predecessor
                if circuit.predecessor
                and circuit.predecessor.state in {"published", "withdrawn"}
                else None
            ),
            "algorithm_filter_tags": algorithm_filter_tags,
            "algorithm_filter_grid": build_algorithm_grid(
                grid_id="circuit-result-algorithm-filters",
                picker_id="circuit-result-algorithm-tags",
                tags=algorithm_filter_tags,
                selected_tags=selected_tags,
                tag_match=tag_match,
                skeleton=skeleton_preparation,
                priors=priors_preparation,
                probability=probability_output,
            ),
            "selected_tags": selected_tags,
            "tag_match": tag_match,
            "selected_skeleton": skeleton_preparation,
            "selected_priors": priors_preparation,
            "selected_probability": probability_output,
            "machine_classes": Machine.MachineClass.choices,
            "selected_machine_class": machine_class,
            "machine_filter_grid": build_machine_grid(
                grid_id="circuit-result-machine-filters",
                machine_classes=Machine.MachineClass.choices,
                selected_machine_class=machine_class,
            ),
            "result_rows": result_rows,
            "leaderboard_filters_active": bool(
                selected_tags
                or skeleton_preparation
                or priors_preparation
                or probability_output
                or machine_class
                or comparison["scripted_query_active"]
            ),
            "circuit_reset_url": detail_url,
            **comparison,
        },
    )
