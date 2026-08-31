"""Public benchmark catalogue and exact-revision views."""

from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, reverse

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
    parse_sort,
    table_context,
    url_without,
)
from registry.models import BenchmarkRevision
from registry.services.benchmarks import (
    inherited_benchmark_description,
    public_benchmark_catalogue,
    public_benchmark_detail,
    public_benchmark_predecessor,
    public_benchmark_successor,
    summarise_attempts,
)

BENCHMARK_COLUMNS = (
    ColumnSpec("name", "Benchmark"),
    ColumnSpec("version", "Version"),
    ColumnSpec("recognition", "Recognition"),
    ColumnSpec("required", "Required circuits", numeric=True),
    ColumnSpec("optional", "Optional circuits", numeric=True),
    ColumnSpec("attempts", "Attempts", numeric=True, default_direction="desc"),
    ColumnSpec(
        "published", "Published", default_direction="desc", default_visible=False
    ),
)

BENCHMARK_SORT_FIELDS = {
    "name": "name",
    "version": "version",
    "recognition": "recognition_status",
    "required": "required_item_count",
    "optional": "optional_item_count",
    "attempts": "published_attempt_count",
    "published": "published_at",
}


def benchmark_list(request):
    query = request.GET.get("q", "").strip()
    recognition = request.GET.get("recognition", "").strip()
    if recognition not in BenchmarkRevision.RecognitionStatus.values:
        recognition = ""
    raw_sort = request.GET.get("sort", "")
    ordering_selection = select_catalogue_ordering(
        search_query=query,
        raw_sort=raw_sort,
    )
    sort_keys = parse_sort(
        raw_sort,
        BENCHMARK_COLUMNS,
        (("name", "asc"),),
    )
    benchmark_queryset = public_benchmark_catalogue(
        query=query,
        recognition_status=recognition,
    )
    if ordering_selection.mode == CatalogueOrderingMode.MANUAL:
        benchmark_queryset = apply_sort(
            benchmark_queryset,
            sort_keys,
            BENCHMARK_SORT_FIELDS,
        )
    elif ordering_selection.mode == CatalogueOrderingMode.SEARCH_RELEVANCE:
        sort_keys = ()
        benchmark_queryset = apply_search_relevance(
            benchmark_queryset,
            CatalogueKind.BENCHMARK,
            ordering_selection.search_query,
        )
    else:
        sort_keys = ()
        benchmark_queryset = apply_featured_ordering(
            benchmark_queryset, CatalogueKind.BENCHMARK
        )
    benchmarks = list(benchmark_queryset)
    table = table_context(request, BENCHMARK_COLUMNS, sort_keys)
    discovery_ordering = ordering_metadata(
        ordering_selection, CatalogueKind.BENCHMARK
    ).as_context()
    if ordering_selection.mode != CatalogueOrderingMode.MANUAL:
        table["sort_summary"] = discovery_ordering["label"]
    rows = []
    for benchmark in benchmarks:
        cell_by_key = {
            "name": {
                "key": "name",
                "value": benchmark.name,
                "url": reverse("benchmarks:detail", args=[benchmark.slug]),
            },
            "version": {"key": "version", "value": benchmark.version},
            "recognition": {
                "key": "recognition",
                "value": benchmark.get_recognition_status_display(),
            },
            "required": {
                "key": "required",
                "value": benchmark.required_item_count,
                "numeric": True,
            },
            "optional": {
                "key": "optional",
                "value": benchmark.optional_item_count,
                "numeric": True,
            },
            "attempts": {
                "key": "attempts",
                "value": benchmark.published_attempt_count,
                "numeric": True,
            },
            "published": {
                "key": "published",
                "value": benchmark.published_at,
            },
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
        "benchmarks/list.html",
        {
            "benchmarks": benchmarks,
            "query": query,
            "selected_recognition": recognition,
            "recognition_choices": BenchmarkRevision.RecognitionStatus.choices,
            "result_count": len(benchmarks),
            "table_rows": rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            "discovery_ordering": discovery_ordering,
            "filters_active": bool(query or recognition),
            **table,
        },
    )


def benchmark_detail(request, slug):
    benchmark = get_object_or_404(public_benchmark_detail(), slug=slug)
    description_source = inherited_benchmark_description(benchmark)
    predecessor = public_benchmark_predecessor(benchmark)
    successor = public_benchmark_successor(benchmark)
    attempt_summaries = summarise_attempts(benchmark)
    public_item_count = len(benchmark.public_items)

    return render(
        request,
        "benchmarks/detail.html",
        {
            "benchmark": benchmark,
            "entity": {
                "kind": "Benchmark revision",
                "name": benchmark.name,
                "version": benchmark.version,
                "status": benchmark.state,
                "status_label": benchmark.get_state_display(),
                "tags": [],
            },
            "description_source": description_source,
            "predecessor": predecessor,
            "successor": successor,
            "public_items": benchmark.public_items,
            "manifest_has_hidden_items": (
                benchmark.manifest_item_count != public_item_count
            ),
            "attempt_summaries": attempt_summaries,
            "result_detail_base_url": _result_detail_base_url(),
        },
    )


def _result_detail_base_url() -> str:
    """Prefer the result-detail route once integrated; retain a stable fallback."""

    try:
        marker = "00000000-0000-0000-0000-000000000000"
        return reverse("results:detail", args=[marker]).removesuffix(f"{marker}/")
    except NoReverseMatch:
        return f"{reverse('results:list')}"
