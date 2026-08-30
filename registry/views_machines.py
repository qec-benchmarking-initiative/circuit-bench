from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from registry.explorer import (
    ColumnSpec,
    apply_sort,
    cells_for_visible_columns,
    parse_sort,
    table_context,
    url_without,
)
from registry.models import Machine
from registry.result_tables import result_cell_map
from registry.services.results import public_result_catalogue

MACHINE_RESULT_COLUMNS = (
    ColumnSpec("result", "Result UUID", default_visible=False),
    ColumnSpec("decoder", "Decoder"),
    ColumnSpec("version", "Version"),
    ColumnSpec("algorithm_tags", "Algorithm tags", sortable=False),
    ColumnSpec("circuit", "Circuit"),
    ColumnSpec("noise_model", "Noise model"),
    ColumnSpec("shots", "Shots", numeric=True, default_direction="desc"),
    ColumnSpec("scores", "Evaluator scores", sortable=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)

MACHINE_RESULT_SORT_FIELDS = {
    "result": "id",
    "decoder": "decoder_version__name",
    "version": "decoder_version__version",
    "circuit": "circuit_revision__name",
    "noise_model": "circuit_revision__noise_model__name",
    "shots": "shots_total",
    "reproduction": "reproduction_status",
    "published": "published_at",
}


def machine_detail(request, slug):
    machine = get_object_or_404(
        Machine.objects.select_related("schema_release", "submitted_by"),
        slug=slug,
        state__in=["published", "withdrawn"],
    )
    sort_keys = parse_sort(
        request.GET.get("sort", ""),
        MACHINE_RESULT_COLUMNS,
        (("published", "desc"),),
    )
    results = list(
        apply_sort(
            public_result_catalogue(machine=machine),
            sort_keys,
            MACHINE_RESULT_SORT_FIELDS,
        )
    )
    table = table_context(request, MACHINE_RESULT_COLUMNS, sort_keys)
    detail_url = reverse("machines:detail", args=[machine.slug])
    rows = [
        {
            "cells": cells_for_visible_columns(
                table["visible_column_keys"],
                result_cell_map(result, filter_url=detail_url),
            )
        }
        for result in results
    ]
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
            "result_count": len(results),
            "result_rows": rows,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            **table,
        },
    )
