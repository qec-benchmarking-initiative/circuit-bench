from urllib.parse import urlencode

from django.db.models import Case, IntegerField, Q, Value, When
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
from registry.models import NoiseModel, Tag
from registry.services.circuits import (
    circuit_catalogue,
    circuit_detail_queryset,
    inherited_circuit_description,
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

    filters = {
        "noise_model_slug": request.GET.get("noise_model", "").strip(),
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
    filter_tags = list(
        Tag.objects.filter(
            namespace__in=[Tag.Namespace.CODE, Tag.Namespace.EXPERIMENT],
            status__in=[Tag.Status.OFFICIAL, Tag.Status.CUSTOM],
        )
        .filter(
            Q(status=Tag.Status.OFFICIAL)
            | Q(code_circuit_revisions__state="published")
            | Q(experiment_circuit_revisions__state="published")
        )
        .annotate(
            official_order=Case(
                When(status=Tag.Status.OFFICIAL, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("namespace", "official_order", "label")
    )
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
            "filter_tags": filter_tags,
            "code_filter_tags": [
                tag for tag in filter_tags if tag.namespace == Tag.Namespace.CODE
            ],
            "experiment_filter_tags": [
                tag for tag in filter_tags if tag.namespace == Tag.Namespace.EXPERIMENT
            ],
            "noise_models": NoiseModel.objects.filter(state="published").order_by(
                "name"
            ),
            "query": query,
            "selected_tag": legacy_tag,
            "selected_code_tags": code_tags,
            "selected_experiment_tags": experiment_tags,
            "code_tag_match": code_tag_match,
            "experiment_tag_match": experiment_tag_match,
            "filters": filters,
            "raw_values": {
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
            },
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
    artifacts = [
        ("Sampling circuit", circuit.sampling_circuit_artifact),
        ("Detector error model", circuit.detector_error_model_artifact),
        ("Manifest", circuit.manifest_artifact),
    ]
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
        },
    )
