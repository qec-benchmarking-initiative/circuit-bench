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
from registry.filter_grids import noise_model_grid as build_noise_model_grid
from registry.services.circuits import (
    noise_model_catalogue,
    noise_model_detail_queryset,
)


def noise_model_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    allowed_statuses = {"community", "official", "deprecated"}
    if status not in allowed_statuses:
        status = ""
    randomises_priors = request.GET.get("priors", "").strip()
    circuit_min = parse_nonnegative_int(request.GET.get("circuit_min", ""))
    circuit_max = parse_nonnegative_int(request.GET.get("circuit_max", ""))
    columns = (
        ColumnSpec("name", "Noise model"),
        ColumnSpec("curation", "Curation"),
        ColumnSpec("priors", "Randomises priors"),
        ColumnSpec("circuits", "Circuits", numeric=True, default_direction="desc"),
        ColumnSpec("paper", "Source paper", sortable=False),
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
    noise_model_queryset = noise_model_catalogue(
        query=query,
        status=status,
        randomises_priors=randomises_priors,
        circuit_min=circuit_min,
        circuit_max=circuit_max,
    )
    if ordering_selection.mode == CatalogueOrderingMode.MANUAL:
        noise_model_queryset = apply_sort(
            noise_model_queryset,
            sort_keys,
            {
                "name": "name",
                "curation": "curation_status",
                "priors": "randomises_priors",
                "circuits": "circuit_count",
                "published": "published_at",
            },
        )
    elif ordering_selection.mode == CatalogueOrderingMode.SEARCH_RELEVANCE:
        sort_keys = ()
        noise_model_queryset = apply_search_relevance(
            noise_model_queryset,
            CatalogueKind.NOISE_MODEL,
            ordering_selection.search_query,
        )
    else:
        sort_keys = ()
        noise_model_queryset = apply_featured_ordering(
            noise_model_queryset, CatalogueKind.NOISE_MODEL
        )
    noise_models = list(noise_model_queryset)
    circuit_values = list(
        noise_model_catalogue().values_list("circuit_count", flat=True)
    )
    table = table_context(request, columns, sort_keys)
    discovery_ordering = ordering_metadata(
        ordering_selection, CatalogueKind.NOISE_MODEL
    ).as_context()
    if ordering_selection.mode != CatalogueOrderingMode.MANUAL:
        table["sort_summary"] = discovery_ordering["label"]
    rows = []
    for noise_model in noise_models:
        cell_by_key = {
            "name": {
                "key": "name",
                "value": noise_model.name,
                "url": reverse("noise-models:detail", args=[noise_model.slug]),
            },
            "curation": {
                "key": "curation",
                "value": noise_model.get_curation_status_display(),
            },
            "priors": {
                "key": "priors",
                "value": "Yes" if noise_model.randomises_priors else "No",
            },
            "circuits": {
                "key": "circuits",
                "value": noise_model.circuit_count,
                "numeric": True,
            },
            "paper": {
                "key": "paper",
                "value": "Paper",
                "url": noise_model.paper_url,
            },
            "published": {"key": "published", "value": noise_model.published_at},
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
        "noise_models/list.html",
        {
            "noise_models": noise_models,
            "query": query,
            "selected_status": status,
            "selected_priors": randomises_priors,
            "circuit_min": request.GET.get("circuit_min", ""),
            "circuit_max": request.GET.get("circuit_max", ""),
            "noise_model_filter_grid": build_noise_model_grid(
                grid_id="noise-model-filters",
                status=status,
                priors=randomises_priors,
                circuit_minimum=request.GET.get("circuit_min", ""),
                circuit_maximum=request.GET.get("circuit_max", ""),
                circuit_values=circuit_values,
            ),
            "result_count": len(noise_models),
            "table_rows": rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            "discovery_ordering": discovery_ordering,
            "filters_active": bool(
                query
                or status
                or randomises_priors
                or circuit_min is not None
                or circuit_max is not None
            ),
            **table,
        },
    )


def noise_model_detail(request, slug):
    noise_model = get_object_or_404(noise_model_detail_queryset(), slug=slug)
    return render(
        request,
        "noise_models/detail.html",
        {
            "noise_model": noise_model,
            "circuits": noise_model.published_circuits,
            "entity": {
                "kind": "Noise model",
                "name": noise_model.name,
                "version": None,
                "status": noise_model.curation_status,
                "status_label": noise_model.get_curation_status_display(),
                "tags": [],
            },
            "supersedes_noise_model": (
                noise_model.supersedes_noise_model
                if noise_model.supersedes_noise_model
                and noise_model.supersedes_noise_model.state
                in {"published", "withdrawn"}
                else None
            ),
        },
    )
