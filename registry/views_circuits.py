from urllib.parse import urlencode

from django.shortcuts import get_object_or_404, render
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
from registry.formatting import format_scientific_value
from registry.models import Machine
from registry.record_pickers import record_picker_context
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
    ColumnSpec("scores", "Evaluator scores", sortable=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)

CIRCUIT_RESULT_SORT_FIELDS = {
    "decoder": "decoder_version__name",
    "version": "decoder_version__version",
    "skeleton": "decoder_version__circuit_skeleton_preparation",
    "priors": "decoder_version__circuit_priors_preparation",
    "probability": "decoder_version__provides_failure_probability",
    "machine_class": "machine__machine_class",
    "machine": "machine__slug",
    "shots": "shots_total",
    "reproduction": "reproduction_status",
    "published": "published_at",
}


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
    noise_model_picker = record_picker_context(
        "noise-models", requested_noise_models
    )
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
    sort_keys = parse_sort(request.GET.get("sort", ""), columns, (("name", "asc"),))
    circuits = list(
        apply_sort(
            circuit_catalogue(
                query=query,
                tag=legacy_tag,
                code_tag_slugs=code_tags,
                experiment_tag_slugs=experiment_tags,
                code_tag_match=code_tag_match,
                experiment_tag_match=experiment_tag_match,
                **filters,
            ),
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
    )
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
        dict.fromkeys(
            tag.strip() for tag in request.GET.getlist("tag") if tag.strip()
        )
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
    sort_keys = parse_sort(
        request.GET.get("sort", ""),
        CIRCUIT_RESULT_COLUMNS,
        (("decoder", "asc"),),
    )
    results = list(
        apply_sort(
            circuit_result_leaderboard(
                circuit=circuit,
                tag_slugs=selected_tags,
                tag_match=tag_match,
                skeleton_preparation=skeleton_preparation,
                priors_preparation=priors_preparation,
                probability_output=probability_output,
                machine_class=machine_class,
            ),
            sort_keys,
            CIRCUIT_RESULT_SORT_FIELDS,
        )
    )
    table = table_context(request, CIRCUIT_RESULT_COLUMNS, sort_keys)
    result_rows = []
    for result in results:
        scores = "; ".join(
            (
                f"{score.score_definition.name}: "
                f"{format_scientific_value(score.value)} "
                f"{score.score_definition.unit}"
            ).rstrip()
            for score in sorted(
                result.scores.all(),
                key=lambda score: score.score_definition.display_order,
            )
        )
        decoder = result.decoder_version
        cell_by_key = {
            "decoder": {
                "key": "decoder",
                "value": decoder.name,
                "url": reverse("decoders:detail", args=[decoder.slug]),
            },
            "version": {"key": "version", "value": decoder.version},
            "algorithm_tags": {
                "key": "algorithm_tags",
                "tags": [
                    {
                        "label": tag.label,
                        "display_color": tag.display_color,
                        "url": f"{detail_url}?{urlencode({'tag': tag.slug})}",
                    }
                    for tag in decoder.display_algorithm_tags
                ],
            },
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
            "machine_class": {
                "key": "machine_class",
                "value": result.machine.get_machine_class_display()
                if result.machine
                else "Unreported",
            },
            "machine": {
                "key": "machine",
                "value": result.machine.slug if result.machine else None,
                "url": (
                    reverse("machines:detail", args=[result.machine.slug])
                    if result.machine
                    else None
                ),
            },
            "shots": {"key": "shots", "value": result.shots_total, "numeric": True},
            "scores": {"key": "scores", "value": scores},
            "reproduction": {
                "key": "reproduction",
                "value": result.get_reproduction_status_display(),
            },
            "published": {"key": "published", "value": result.published_at},
        }
        result_rows.append(
            {
                "cells": cells_for_visible_columns(
                    table["visible_column_keys"], cell_by_key
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
                circuit.previous_revision
                if circuit.previous_revision
                and circuit.previous_revision.state in {"published", "withdrawn"}
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
            "result_count": len(results),
            "result_rows": result_rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            "leaderboard_filters_active": bool(
                selected_tags
                or skeleton_preparation
                or priors_preparation
                or probability_output
                or machine_class
            ),
            "circuit_reset_url": detail_url,
            **table,
        },
    )
