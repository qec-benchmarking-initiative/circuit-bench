from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.http import QueryDict

from registry.demo import seed_demo_data
from registry.models import RecordHistory, Result, ResultScore
from registry.result_query import (
    MAX_PAGE_SIZE,
    RESULT_RECORD_SCHEMA_VERSION,
    ResultQueryError,
    execute_result_query,
    field_catalogue,
    page_result_query,
    parse_result_query,
    result_record,
)
from registry.services.results import public_result_catalogue

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_results():
    seed_demo_data()
    first = Result.objects.get()
    second = Result.objects.create(
        history=RecordHistory.objects.create(record_kind="result"),
        id=uuid4(),
        schema_release=first.schema_release,
        decoder_version=first.decoder_version,
        circuit_revision=first.circuit_revision,
        evaluator_version=first.evaluator_version,
        machine=first.machine,
        description="Second exact run for query-contract tests.",
        shots_total=50_000,
        successful_shots=49_400,
        logical_failure_shots=500,
        timeout_shots=75,
        decoder_error_shots=25,
        failure_probability_shots=49_900,
        latency_shots=49_900,
        preparation_duration_seconds=Decimal("0.500000000"),
        software_environment="Synthetic query test",
        t_1000_ns=30_000_000,
        reproduction_status="independent_reproduction",
        submitted_by=first.submitted_by,
        state="published",
        published_at=first.published_at + timedelta(seconds=1),
    )
    for score in first.scores.select_related("score_definition"):
        value = (
            Decimal("0.05000000000000000000")
            if score.score_definition.key == "ler-upper-95-at-5pct-acceptance"
            else Decimal("0.03000000000000000000")
        )
        ResultScore.objects.create(
            result=second,
            score_definition=score.score_definition,
            evaluator_version=score.evaluator_version,
            value=value,
            point_estimate=value,
            upper_bound=value,
            confidence_level=score.confidence_level,
            sample_count=score.sample_count,
            event_count=score.event_count,
            details={"fixture": True},
        )
    return first, second


def test_contract_catalogue_pins_scientific_metric_metadata():
    fields = {field["name"]: field for field in field_catalogue()}

    assert RESULT_RECORD_SCHEMA_VERSION == "result-record/0.1"
    assert fields["t_1000_ns"] == {
        "name": "t_1000_ns",
        "label": "t₁₀₀₀",
        "type": "integer",
        "unit": "ns",
        "definition": "/definitions/result/0.1/#preparation-and-timing",
        "nullable": True,
        "filterable": True,
        "sortable": True,
        "selectable": True,
        "direction": "lower_is_better",
    }
    ler = fields["score_ler_upper_95_at_5pct_acceptance_v0_1"]
    assert ler["unit"] == "probability"
    assert ler["direction"] == "lower_is_better"
    assert ler["definition"].endswith("#stored-scores")


def test_score_and_timing_metrics_are_real_sortable_query_fields(two_results):
    first, second = two_results
    by_ler = parse_result_query(
        QueryDict(
            "$filter=score_ler_upper_95_at_5pct_acceptance_v0_1 lt 0.2"
            "&$orderby=score_ler_upper_95_at_5pct_acceptance_v0_1 asc"
        )
    )
    by_timing = parse_result_query(QueryDict("$orderby=t_1000_ns asc"))

    assert [
        item.id for item in page_result_query(execute_result_query(by_ler), by_ler)
    ] == [
        second.id,
        first.id,
    ]
    assert [
        item.id
        for item in page_result_query(execute_result_query(by_timing), by_timing)
    ] == [
        first.id,
        second.id,
    ]


def test_structured_and_odata_filters_produce_same_ordered_result_ids(two_results):
    structured = public_result_catalogue(machine_class="cpu").filter(
        shots_total__gte=75_000
    )
    query = parse_result_query(
        QueryDict(
            "$filter=machine_class eq 'cpu' and shots_total ge 75000"
            "&$orderby=published_at desc"
        )
    )

    expected = list(
        structured.order_by("-published_at", "id").values_list("id", flat=True)
    )
    actual = list(execute_result_query(query).values_list("id", flat=True))
    assert actual == expected


def test_projection_uses_public_names_and_preserves_exact_decimal(two_results):
    query = parse_result_query(
        QueryDict(
            "$select=id,t_1000_ns,score_ler_upper_95_at_5pct_acceptance_v0_1"
            "&$orderby=t_1000_ns asc&$top=1&$count=true"
        )
    )
    [result] = page_result_query(execute_result_query(query), query)

    assert result_record(result, query.select) == {
        "id": str(result.id),
        "t_1000_ns": 25_000_000,
        "score_ler_upper_95_at_5pct_acceptance_v0_1": "0.15000000000000000000",
    }
    assert query.include_count is True
    assert "$select=id,t_1000_ns,score_ler" in query.canonical


@pytest.mark.parametrize(
    ("raw", "code", "position"),
    [
        ("$filter=made_up eq 1", "unknown_field", 0),
        ("$filter=shots_total eq 'many'", "type_mismatch", 15),
        ("$filter=t_1000_ns gt null", "null_comparison", 13),
        ("$orderby=made_up", "unknown_field", None),
        (f"$top={MAX_PAGE_SIZE + 1}", "page_size_too_large", None),
        ("$expand=decoder", "unsupported_option", None),
    ],
)
def test_invalid_or_expensive_queries_have_stable_errors(raw, code, position):
    with pytest.raises(ResultQueryError) as caught:
        parse_result_query(QueryDict(raw))

    assert caught.value.code == code
    assert caught.value.position == position


def test_string_functions_and_parentheses_compile_safely(two_results):
    query = parse_result_query(
        QueryDict(
            "$filter=contains(decoder_name,'Matcher') and "
            "(machine_slug eq 'demo-eight-core-cpu' or machine_slug eq null)"
        )
    )

    assert execute_result_query(query).count() == 2
    assert "contains(decoder_name,'Matcher')" in query.canonical
