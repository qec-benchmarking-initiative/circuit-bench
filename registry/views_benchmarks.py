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
from registry.filter_grids import algorithm_grid as build_algorithm_grid
from registry.filter_grids import circuit_grid as build_circuit_grid
from registry.filter_grids import machine_grid as build_machine_grid
from registry.models import BenchmarkRevision, Machine
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
from registry.services.benchmarks import (
    inherited_benchmark_description,
    public_benchmark_catalogue,
    public_benchmark_detail,
    public_benchmark_predecessor,
    public_benchmark_successor,
    summarise_attempts,
)
from registry.services.decoders import catalogue_algorithm_tags
from registry.services.filter_options import public_circuit_filter_options
from registry.services.results import public_result_catalogue
from registry.table_controls import (
    ColumnSpec,
    apply_sort,
    cells_for_visible_columns,
    parse_sort,
    table_context,
    url_without,
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

BENCHMARK_RESULT_COLUMNS = (
    ColumnSpec("result", "Result UUID", default_visible=False),
    ColumnSpec("decoder", "Decoder"),
    ColumnSpec("version", "Version"),
    ColumnSpec("algorithm_tags", "Algorithm tags", sortable=False),
    ColumnSpec("circuit", "Circuit"),
    ColumnSpec("noise_model", "Noise model"),
    ColumnSpec("machine_class", "Machine type"),
    ColumnSpec("machine", "Machine"),
    ColumnSpec("shots", "Shots", numeric=True, default_direction="desc"),
    *RESULT_METRIC_COLUMNS,
    ColumnSpec("scores", "Evaluator scores", sortable=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)


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
    benchmark = get_object_or_404(public_benchmark_detail(request.user), slug=slug)
    description_source = inherited_benchmark_description(benchmark)
    predecessor = public_benchmark_predecessor(benchmark)
    successor = public_benchmark_successor(benchmark)
    attempt_summaries = summarise_attempts(benchmark)
    public_item_count = len(benchmark.public_items)
    filter_state = result_filter_state(request.GET)
    filters = filter_state.service_arguments
    noise_model_picker = record_picker_context(
        "noise-models", filters["noise_model_slugs"]
    )
    filters["noise_model_slugs"] = tuple(
        record["identifier"] for record in noise_model_picker["selected_records"]
    )
    filters["benchmark_slug"] = benchmark.slug
    comparison = result_comparison_context(
        request,
        queryset=public_result_catalogue(viewer=request.user, **filters),
        columns=BENCHMARK_RESULT_COLUMNS,
        default_sort=(("decoder", "asc"), ("circuit", "asc")),
        plot_id="benchmark-results-scatter",
        point_context="benchmark",
        api_parameters=api_parameters_from_request(
            request.GET,
            overrides=(("scope_benchmark", benchmark.slug),),
        ),
    )
    detail_url = reverse("benchmarks:detail", args=[benchmark.slug])
    result_rows = [
        {
            "cells": cells_for_visible_columns(
                comparison["visible_column_keys"],
                result_cell_map(result, filter_url=detail_url),
            )
        }
        for result in comparison["results"]
    ]
    algorithm_tags = list(catalogue_algorithm_tags())
    circuit_options = public_circuit_filter_options()
    result_filters_active = bool(
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
        "benchmarks/detail.html",
        {
            "benchmark": benchmark,
            "record": {
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
            "algorithm_filter_grid": build_algorithm_grid(
                grid_id="benchmark-result-algorithm-filters",
                picker_id="benchmark-result-algorithm-tags",
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
                grid_id="benchmark-result-circuit-filters",
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
            "machine_filter_grid": build_machine_grid(
                grid_id="benchmark-result-machine-filters",
                machine_classes=Machine.MachineClass.choices,
                selected_machine_class=filters["machine_class"],
            ),
            "result_rows": result_rows,
            "result_filters_active": result_filters_active,
            "result_reset_url": detail_url,
            **comparison,
        },
    )


def _result_detail_base_url() -> str:
    """Prefer the result-detail route once integrated; retain a stable fallback."""

    try:
        marker = "00000000-0000-0000-0000-000000000000"
        return reverse("results:detail", args=[marker]).removesuffix(f"{marker}/")
    except NoReverseMatch:
        return f"{reverse('results:list')}"
