"""Versioned machine-readable views of the public ResultRecord projection."""

import csv
from io import StringIO
from urllib.parse import urlencode

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from registry.result_query import (
    FIELD_BY_NAME,
    RESULT_RECORD_SCHEMA_VERSION,
    ResultQueryError,
    execute_result_query,
    field_catalogue,
    page_result_query,
    parse_result_query,
    result_record,
)
from registry.result_request import result_filter_state
from registry.services.results import public_result_catalogue


@require_GET
def result_records_json(request: HttpRequest) -> JsonResponse:
    try:
        query = parse_result_query(request.GET)
    except ResultQueryError as error:
        return JsonResponse({"error": error.as_dict()}, status=400)

    filters = result_filter_state(request.GET)
    queryset = execute_result_query(
        query,
        queryset=public_result_catalogue(**filters.service_arguments),
    )
    total_count = queryset.count()
    results = page_result_query(queryset, query)
    records = [result_record(result, query.select) for result in results]
    return JsonResponse(
        _response_envelope(request, query, total_count, records),
        json_dumps_params={"indent": 2},
    )


@require_GET
def result_records_csv(request: HttpRequest) -> HttpResponse:
    try:
        query = parse_result_query(request.GET)
    except ResultQueryError as error:
        return JsonResponse({"error": error.as_dict()}, status=400)

    filters = result_filter_state(request.GET)
    queryset = execute_result_query(
        query,
        queryset=public_result_catalogue(**filters.service_arguments),
    )
    total_count = queryset.count()
    results = page_result_query(queryset, query)
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=query.select, extrasaction="raise")
    writer.writeheader()
    for result in results:
        writer.writerow(result_record(result, query.select))

    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="circuit-bench-results.csv"'
    response["X-Circuit-Bench-Schema"] = RESULT_RECORD_SCHEMA_VERSION
    response["X-Circuit-Bench-Canonical-Query"] = query.canonical
    response["X-Total-Count"] = str(total_count)
    response["Content-Location"] = _format_url(
        request, "results:api-csv", query.canonical
    )
    return response


@require_GET
def result_record_schema(request: HttpRequest) -> JsonResponse:
    return JsonResponse(
        {
            "schema_version": RESULT_RECORD_SCHEMA_VERSION,
            "live": True,
            "fields": field_catalogue(),
            "limits": {
                "default_page_size": 100,
                "maximum_page_size": 1000,
                "maximum_order_fields": 5,
                "maximum_filter_characters": 2000,
                "maximum_filter_nodes": 100,
            },
            "documentation": request.build_absolute_uri(reverse("pages:query-syntax")),
        },
        json_dumps_params={"indent": 2},
    )


def _response_envelope(request, query, total_count, records):
    return {
        "schema_version": RESULT_RECORD_SCHEMA_VERSION,
        "generated_at": timezone.now().isoformat(),
        "live": True,
        "canonical_query": query.canonical,
        "count": total_count,
        "offset": query.skip,
        "limit": query.top,
        "selected_fields": [
            {
                "name": name,
                "type": FIELD_BY_NAME[name].kind,
                "unit": FIELD_BY_NAME[name].unit,
                "definition": FIELD_BY_NAME[name].definition,
            }
            for name in query.select
        ],
        "ordered_result_ids": [record["id"] for record in records if "id" in record],
        "records": records,
        "links": {
            "self": _format_url(request, "results:api-json", query.canonical),
            "csv": _format_url(request, "results:api-csv", query.canonical),
            "schema": request.build_absolute_uri(reverse("results:api-schema")),
        },
    }


def _format_url(request: HttpRequest, route_name: str, canonical: str) -> str:
    parameters = [
        (key, value)
        for key in request.GET
        if not key.startswith("$")
        and key not in {"odata", "last_odata", "sort", "columns", "page"}
        for value in request.GET.getlist(key)
    ]
    for part in canonical.split("&"):
        key, value = part.split("=", 1)
        parameters.append((key, value))
    path = reverse(route_name)
    return request.build_absolute_uri(f"{path}?{urlencode(parameters)}")
