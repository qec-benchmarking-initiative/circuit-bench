from decimal import Decimal
from uuid import UUID

import pytest
from django.template.loader import render_to_string

from registry.models import Result
from registry.result_plots import (
    DEFAULT_X_FIELD,
    DEFAULT_Y_FIELD,
    PlotDeclarationError,
    build_result_scatter_plot,
)


def _result(identifier: int, x_value, y_value) -> Result:
    result = Result(
        id=UUID(f"00000000-0000-0000-0000-{identifier:012d}"),
        t_1000_ns=x_value,
    )
    result.metric_ler_upper_95_at_5pct_acceptance_v0_1 = y_value
    return result


def test_default_plot_preserves_population_order_and_omits_null_points():
    first = _result(1, 10, Decimal("0.20"))
    missing = _result(2, None, Decimal("0.15"))
    third = _result(3, 30, Decimal("0.10"))

    plot = build_result_scatter_plot([third, missing, first])

    assert plot["x_axis"]["field"] == DEFAULT_X_FIELD
    assert plot["x_axis"]["unit"] == "ns"
    assert plot["x_axis"]["definition"].endswith("#preparation-and-timing")
    assert plot["y_axis"]["field"] == DEFAULT_Y_FIELD
    assert plot["y_axis"]["unit"] == "probability"
    assert plot["y_axis"]["definition"].endswith("#stored-scores")
    assert plot["result_ids"] == [str(third.id), str(missing.id), str(first.id)]
    assert plot["plotted_result_ids"] == [str(third.id), str(first.id)]
    assert plot["total_count"] == 3
    assert plot["plotted_count"] == 2
    assert plot["omitted_count"] == 1


def test_plot_geometry_is_deterministic_and_y_axis_increases_upwards():
    low = _result(1, 10, Decimal("0.10"))
    high = _result(2, 30, Decimal("0.30"))

    first = build_result_scatter_plot([low, high])
    second = build_result_scatter_plot([low, high])

    assert first == second
    assert Decimal(first["points"][0]["x"]) < Decimal(first["points"][1]["x"])
    assert Decimal(first["points"][0]["y"]) > Decimal(first["points"][1]["y"])


@pytest.mark.parametrize(
    ("x_value", "y_value"),
    [(0, Decimal("0")), (25_000_000, Decimal("0.15"))],
)
def test_singleton_and_equal_domains_have_finite_centred_coordinates(x_value, y_value):
    one = _result(1, x_value, y_value)
    two = _result(2, x_value, y_value)

    plot = build_result_scatter_plot([one, two])

    assert plot["x_axis"]["minimum"] != plot["x_axis"]["maximum"]
    assert plot["y_axis"]["minimum"] != plot["y_axis"]["maximum"]
    assert plot["points"][0]["x"] == plot["points"][1]["x"]
    assert plot["points"][0]["y"] == plot["points"][1]["y"]
    assert plot["points"][0]["x"] == plot["plot_centre_x"]
    assert plot["points"][0]["y"] == plot["plot_centre_y"]


def test_axes_must_be_whitelisted_numeric_result_record_fields():
    result = _result(1, 10, Decimal("0.1"))

    with pytest.raises(PlotDeclarationError, match="Unknown ResultRecord") as unknown:
        build_result_scatter_plot([result], x_field="not_a_field")
    assert unknown.value.code == "unknown_field"

    with pytest.raises(PlotDeclarationError, match="cannot be used") as nonnumeric:
        build_result_scatter_plot([result], x_field="decoder_name")
    assert nonnumeric.value.code == "nonnumeric_axis"


def test_missing_metric_annotation_is_reported_without_querying():
    result = Result(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        t_1000_ns=10,
    )

    with pytest.raises(PlotDeclarationError) as caught:
        build_result_scatter_plot([result])

    assert caught.value.code == "missing_projection"


def test_builder_rejects_an_unmaterialized_queryset_without_evaluating_it(
    django_assert_num_queries,
    db,
):
    queryset = Result.objects.all()

    with django_assert_num_queries(0), pytest.raises(PlotDeclarationError) as caught:
        build_result_scatter_plot(queryset)

    assert caught.value.code == "unmaterialized_population"


def test_component_renders_accessible_svg_and_the_same_tabular_points():
    first = _result(1, 25_000_000, Decimal("0.15"))
    missing = _result(2, None, Decimal("0.1"))
    plot = build_result_scatter_plot([first, missing], plot_id="comparison")

    rendered = render_to_string("components/result_plot.html", {"plot": plot})

    assert 'role="img"' in rendered
    labelled_by = 'aria-labelledby="comparison-svg-title comparison-svg-description"'
    assert labelled_by in rendered
    assert "1 of 2 results plotted" in rendered
    assert "1 omitted" in rendered
    assert f'id="comparison-point-{first.id}"' in rendered
    assert f'id="comparison-point-{missing.id}"' not in rendered
    assert rendered.count(f'data-result-id="{first.id}"') == 2
    assert "Tabular data for this plot (1 rows)" in rendered
    assert "/definitions/result/0.1/#preparation-and-timing" in rendered
    assert "/definitions/result/0.1/#stored-scores" in rendered
    assert "2.5e7 ns" in rendered
    assert "0.15 probability" in rendered
