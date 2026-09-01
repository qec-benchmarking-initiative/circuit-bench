from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from registry.models import Result
from registry.result_plots import (
    DEFAULT_X_FIELD,
    DEFAULT_Y_FIELD,
    PlotDeclarationError,
    build_result_scatter_plot,
)
from registry.result_query import FIELD_BY_NAME, metric_component_annotation


def _result(identifier: int, x_value, y_value) -> Result:
    result = Result(
        id=UUID(f"00000000-0000-0000-0000-{identifier:012d}"),
        t_1000_ns=x_value,
    )
    result.metric_ler_upper_95_at_5pct_acceptance_v0_1 = y_value
    return result


def _with_y_interval(result, lower, upper, *, estimate=None, confidence="0.95"):
    field = FIELD_BY_NAME[DEFAULT_Y_FIELD]
    for component, value in (
        ("lower_bound", lower),
        ("upper_bound", upper),
        ("point_estimate", estimate),
        ("confidence_level", confidence),
    ):
        setattr(result, metric_component_annotation(field, component), value)
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


def test_stored_metric_intervals_expand_auto_domain_and_declare_whiskers():
    result = _with_y_interval(
        _result(1, 10, Decimal("0.30")),
        Decimal("0.10"),
        Decimal("0.30"),
        estimate=Decimal("0.20"),
    )

    plot = build_result_scatter_plot([result], uncertainty_style="bars")
    interval = plot["points"][0]["y_interval"]

    assert interval["lower_value"] == "0.10"
    assert interval["upper_value"] == "0.30"
    assert interval["point_estimate"] == "0.20"
    assert interval["confidence_display"] == "95%"
    assert Decimal(plot["y_axis"]["minimum"]) < Decimal("0.10")
    assert Decimal(plot["y_axis"]["maximum"]) > Decimal("0.30")
    assert plot["uncertainty"]["y_interval_count"] == 1
    assert plot["uncertainty"]["x_interval_count"] == 0


def test_hidden_uncertainty_does_not_expand_domain_or_declare_intervals():
    result = _with_y_interval(
        _result(1, 10, Decimal("0.30")),
        Decimal("0.10"),
        Decimal("0.30"),
    )

    plot = build_result_scatter_plot([result], uncertainty_style="none")

    assert plot["points"][0]["y_interval"] is None
    assert plot["uncertainty"]["y_interval_count"] == 1
    assert Decimal(plot["y_axis"]["minimum"]) > Decimal("0.10")


def test_incomplete_or_nonpositive_log_intervals_are_not_invented():
    incomplete = _with_y_interval(
        _result(1, 10, Decimal("0.30")),
        None,
        Decimal("0.30"),
    )
    nonpositive = _with_y_interval(
        _result(2, 20, Decimal("0.40")),
        Decimal("0"),
        Decimal("0.40"),
    )

    plot = build_result_scatter_plot(
        [incomplete, nonpositive], y_scale="log", uncertainty_style="areas"
    )

    assert all(point["y_interval"] is None for point in plot["points"])


def test_uncertainty_style_is_a_closed_declaration():
    with pytest.raises(PlotDeclarationError) as caught:
        build_result_scatter_plot(
            [_result(1, 10, Decimal("0.1"))], uncertainty_style="ribbons"
        )

    assert caught.value.code == "invalid_uncertainty_style"


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


def test_each_axis_can_use_a_logarithmic_scale_with_numeric_ticks():
    low = _result(1, 10, Decimal("0.01"))
    high = _result(2, 1_000, Decimal("1"))

    plot = build_result_scatter_plot([low, high], x_scale="log", y_scale="log")

    assert plot["x_axis"]["scale"] == "log"
    assert plot["y_axis"]["scale"] == "log"
    major_values = {Decimal(tick["value"]) for tick in plot["x_axis"]["major_ticks"]}
    assert major_values.issuperset({Decimal(10), Decimal(100), Decimal(1000)})
    assert major_values & {Decimal(20), Decimal(50), Decimal(200), Decimal(500)}
    assert all(tick["kind"] == "major" for tick in plot["x_axis"]["major_ticks"])
    assert all(tick["label"] for tick in plot["x_axis"]["major_ticks"])
    assert all(tick["kind"] == "minor" for tick in plot["x_axis"]["minor_ticks"])
    assert all("label" not in tick for tick in plot["x_axis"]["minor_ticks"])
    assert Decimal(30) in {
        Decimal(tick["value"]) for tick in plot["x_axis"]["minor_ticks"]
    }
    assert Decimal(900) in {
        Decimal(tick["value"]) for tick in plot["x_axis"]["minor_ticks"]
    }
    assert Decimal(plot["points"][0]["x"]) < Decimal(plot["points"][1]["x"])


def test_subdecade_log_axis_has_readable_major_labels():
    low = _result(1, 31, Decimal("0.1"))
    high = _result(2, 43, Decimal("0.2"))

    plot = build_result_scatter_plot([low, high], x_scale="log")

    major_values = [Decimal(tick["value"]) for tick in plot["x_axis"]["major_ticks"]]
    assert len(major_values) >= 3
    assert all(tick["label"] for tick in plot["x_axis"]["major_ticks"])
    assert min(major_values) >= Decimal("30")
    assert max(major_values) <= Decimal("45")


def test_linear_axes_use_readable_major_and_minor_multiples():
    low = _result(1, 13, Decimal("0.13"))
    high = _result(2, 87, Decimal("0.87"))

    plot = build_result_scatter_plot([low, high])

    assert [Decimal(tick["value"]) for tick in plot["x_axis"]["major_ticks"]] == [
        Decimal(20),
        Decimal(40),
        Decimal(60),
        Decimal(80),
    ]
    assert Decimal(15) in {
        Decimal(tick["value"]) for tick in plot["x_axis"]["minor_ticks"]
    }
    assert Decimal(85) in {
        Decimal(tick["value"]) for tick in plot["x_axis"]["minor_ticks"]
    }
    assert all(tick["kind"] in {"major", "minor"} for tick in plot["x_axis"]["ticks"])


def test_explicit_axis_bounds_set_the_domain_and_omit_out_of_range_points():
    outside = _result(1, 10, Decimal("0.1"))
    inside = _result(2, 30, Decimal("0.2"))

    plot = build_result_scatter_plot(
        [outside, inside],
        x_min="20",
        x_max="40",
        y_min=Decimal("0.15"),
        y_max=Decimal("0.25"),
    )

    assert plot["plotted_result_ids"] == [str(inside.id)]
    assert plot["range_omission_count"] == 1
    assert plot["omitted_count"] == 1
    assert "outside the explicit axis limits" in plot["omitted_explanation"]
    assert plot["x_axis"]["minimum"] == "20"
    assert plot["x_axis"]["maximum"] == "40"
    assert plot["x_axis"]["minimum_is_explicit"] is True
    assert plot["x_axis"]["maximum_is_explicit"] is True
    assert plot["y_axis"]["minimum"] == "0.15"
    assert plot["y_axis"]["maximum"] == "0.25"


@pytest.mark.parametrize(
    ("arguments", "expected_minimum", "expected_maximum"),
    [
        ({"x_min": "100"}, Decimal("100"), Decimal("105")),
        ({"x_max": "-100"}, Decimal("-105"), Decimal("-100")),
    ],
)
def test_one_sided_bound_beyond_all_data_produces_a_finite_empty_domain(
    arguments,
    expected_minimum,
    expected_maximum,
):
    plot = build_result_scatter_plot(
        [_result(1, 10, Decimal("0.1"))],
        **arguments,
    )

    assert plot["plotted_count"] == 0
    assert plot["range_omission_count"] == 1
    assert Decimal(plot["x_axis"]["minimum"]) == expected_minimum
    assert Decimal(plot["x_axis"]["maximum"]) == expected_maximum
    assert Decimal(plot["x_axis"]["minimum"]).is_finite()
    assert Decimal(plot["x_axis"]["maximum"]).is_finite()


def test_one_sided_log_bound_beyond_all_data_produces_a_finite_empty_domain():
    plot = build_result_scatter_plot(
        [_result(1, 10, Decimal("0.1"))],
        x_scale="log",
        x_min="1000",
    )

    minimum = Decimal(plot["x_axis"]["minimum"])
    maximum = Decimal(plot["x_axis"]["maximum"])
    assert plot["plotted_count"] == 0
    assert plot["range_omission_count"] == 1
    assert minimum == Decimal(1000)
    assert minimum < maximum
    assert minimum.is_finite() and maximum.is_finite()


@pytest.mark.parametrize(
    ("arguments", "error_code"),
    [
        ({"x_min": "not-a-number"}, "invalid_axis_bound"),
        ({"x_max": "NaN"}, "invalid_axis_bound"),
        ({"x_min": "10", "x_max": "10"}, "invalid_axis_domain"),
        ({"x_min": "11", "x_max": "10"}, "invalid_axis_domain"),
        ({"x_scale": "log", "x_min": "0"}, "nonpositive_log_bound"),
        ({"y_scale": "log", "y_max": "-1"}, "nonpositive_log_bound"),
    ],
)
def test_invalid_explicit_axis_bounds_have_stable_errors(arguments, error_code):
    with pytest.raises(PlotDeclarationError) as caught:
        build_result_scatter_plot(
            [_result(1, 10, Decimal("0.1"))],
            **arguments,
        )

    assert caught.value.code == error_code


def test_explicit_log_bounds_keep_decade_ticks_exact():
    plot = build_result_scatter_plot(
        [_result(1, 10, Decimal("0.1"))],
        x_scale="log",
        x_min="0.5",
        x_max="500",
    )

    assert [Decimal(tick["value"]) for tick in plot["x_axis"]["major_ticks"]] == [
        Decimal(1),
        Decimal(10),
        Decimal(100),
    ]
    assert {
        Decimal(tick["value"]) for tick in plot["x_axis"]["minor_ticks"]
    }.issuperset({Decimal("0.5"), Decimal(2), Decimal(90), Decimal(500)})


def test_log_scale_omits_nonpositive_values_and_explains_why():
    zero = _result(1, 0, Decimal("0.1"))
    positive = _result(2, 10, Decimal("0.2"))

    plot = build_result_scatter_plot([zero, positive], x_scale="log")

    assert plot["plotted_count"] == 1
    assert plot["log_omission_count"] == 1
    assert "non-positive value" in plot["omitted_explanation"]


def test_invalid_plot_scale_has_a_stable_error():
    with pytest.raises(PlotDeclarationError) as caught:
        build_result_scatter_plot([_result(1, 10, Decimal("0.1"))], x_scale="sqrt")

    assert caught.value.code == "invalid_scale"


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
    first = _with_y_interval(
        _result(1, 25_000_000, Decimal("0.15")),
        Decimal("0.09"),
        Decimal("0.15"),
    )
    missing = _result(2, None, Decimal("0.1"))
    plot = build_result_scatter_plot([first, missing], plot_id="comparison")

    rendered = render_to_string("components/result_plot.html", {"plot": plot})
    rendered_text = " ".join(strip_tags(rendered).split())

    assert 'role="img"' in rendered
    assert 'aria-label="LER upper 95% @ 5% acceptance against t₁₀₀₀"' in rendered
    assert 'aria-describedby="comparison-svg-description"' in rendered
    assert "1 of 2 results plotted" in rendered_text
    assert "1 omitted" in rendered_text
    assert f'id="comparison-point-{first.id}"' in rendered
    assert f'id="comparison-point-{missing.id}"' not in rendered
    assert rendered.count(f'data-result-id="{first.id}"') == 2
    assert "Tabular data for this plot (1 rows)" in rendered_text
    assert "plot-tick-label" in rendered
    assert "data-download-plot" in rendered
    assert "data-plot-crosshair" in rendered
    assert "data-plot-interaction-surface" in rendered
    assert "data-plot-selection-guides" in rendered
    assert (
        'data-plot-selection-guides data-plot-export-exclude aria-hidden="true"'
        in rendered
    )
    assert rendered.count("data-plot-selection-x") == 1
    assert rendered.count("data-plot-selection-y") == 1
    assert rendered.count("data-plot-selection-halo-x") == 1
    assert rendered.count("data-plot-selection-halo-y") == 1
    assert "plot-selection-guide-halo" in rendered
    assert "plot-selection-guide-stroke" in rendered
    halo_markup = rendered.split('class="plot-selection-guide-halo"', 1)[1].split(
        "</g>", 1
    )[0]
    stroke_markup = rendered.split('class="plot-selection-guide-stroke"', 1)[1].split(
        "</g>", 1
    )[0]
    assert "data-plot-selection-x" not in halo_markup
    assert "data-plot-selection-y" not in halo_markup
    assert "data-plot-selection-x" in stroke_markup
    assert "data-plot-selection-y" in stroke_markup
    assert rendered.count("data-plot-export-exclude") == 4
    assert 'data-plot-x-minimum="' in rendered
    assert 'data-plot-y-maximum="' in rendered
    assert "data-plot-tooltip" not in rendered
    assert "<title" not in rendered
    assert "plot-error-bar-y" in rendered
    assert "y stored interval (95%)" in rendered
    assert 'class="result-plot-point' in rendered
    assert 'class="result-plot-point marker-circle"' in rendered
    assert "/definitions/result/0.1/#preparation-and-timing" in rendered
    assert "/definitions/result/0.1/#stored-scores" in rendered
    assert 'data-raw="25000000"' in rendered
    assert "10<sup>7</sup>" in rendered
    assert "0.15 probability" in rendered


def test_plot_selection_uses_delegation_and_does_not_capture_plain_clicks():
    source = (
        Path(__file__).resolve().parents[2] / "static/js/result-plot.js"
    ).read_text()

    assert 'point.addEventListener("click"' not in source
    assert 'graphic?.addEventListener("click"' in source
    assert "summaries.forEach" not in source

    pointerdown = source.split('svg.addEventListener("pointerdown"', 1)[1].split(
        'svg.addEventListener("pointermove"', 1
    )[0]
    pointermove = source.split('svg.addEventListener("pointermove"', 2)[2].split(
        'svg.addEventListener("pointerup"', 1
    )[0]
    assert "setPointerCapture" not in pointerdown
    assert "setPointerCapture" in pointermove


def test_plot_cursor_is_scoped_to_static_plot_targets():
    root = Path(__file__).resolve().parents[2]
    source = (root / "static/js/result-plot.js").read_text()
    styles = (root / "static/css/site.css").read_text()

    assert "has-plot-crosshair" not in source
    assert ".result-plot-svg.has-plot-crosshair" not in styles
    assert ".plot-interaction-surface,\n.result-plot-point {\n  cursor: none;" in styles
    assert "body {\n  min-height: 100vh;\n  margin: 0;\n  cursor: default;" in styles


def test_component_renders_shaded_extents_as_a_distinct_option():
    result = _with_y_interval(
        _result(1, 25_000_000, Decimal("0.15")),
        Decimal("0.09"),
        Decimal("0.15"),
    )
    plot = build_result_scatter_plot([result], uncertainty_style="areas")

    rendered = render_to_string("components/result_plot.html", {"plot": plot})

    assert "plot-uncertainty-areas" in rendered
    assert "plot-error-bar" not in rendered
