from decimal import Decimal
from types import SimpleNamespace

from django.template.loader import render_to_string

from registry.filter_grids import range_cell
from registry.formatting import format_scientific_range, format_scientific_value


def test_scientific_values_use_compact_significant_digits():
    assert format_scientific_value(Decimal("0.02300000000000000000")) == "2.3e-2"
    assert format_scientific_value(Decimal("0.00230000000000000000")) == "2.3e-3"
    assert format_scientific_value(Decimal("0.15000000000000000000")) == "0.15"
    assert format_scientific_value(Decimal("1.23456")) == "1.235"
    assert format_scientific_value(Decimal("12340")) == "1.234e4"
    assert format_scientific_value(Decimal("-12340")) == "-1.234e4"
    assert format_scientific_value(Decimal("99995")) == "1e5"
    assert format_scientific_value(Decimal("0")) == "0"


def test_scientific_value_formatter_leaves_non_numbers_readable():
    assert format_scientific_value("not reported") == "not reported"


def test_scientific_ranges_have_contextual_empty_bounds():
    assert format_scientific_range("", "", empty_label="Auto") == "Auto"
    assert (
        format_scientific_range(
            "0.0023000000",
            "25000000",
            minimum_fallback="auto",
            maximum_fallback="auto",
        )
        == "2.3e-3–2.5e7"
    )
    assert format_scientific_range("", "25000000") == "0–2.5e7"


def test_filter_range_displays_compact_values_but_retains_exact_inputs():
    cell = range_cell(
        key="detectors",
        label="Detectors",
        minimum_name="detector_min",
        maximum_name="detector_max",
        minimum_value="10000",
        maximum_value="25000000",
        values=(10000, 25000000),
        histogram_label="Detector counts",
    )

    assert cell["display_minimum"] == "1e4"
    assert cell["display_maximum"] == "2.5e7"
    assert cell["minimum_value"] == "10000"
    assert cell["maximum_value"] == "25000000"


def test_numeric_data_table_cells_use_the_shared_formatter():
    rendered = render_to_string(
        "components/data_table.html",
        {
            "columns": [{"key": "value", "label": "Value", "numeric": True}],
            "rows": [
                {
                    "cells": [
                        {
                            "key": "value",
                            "value": Decimal("12340"),
                            "numeric": True,
                        }
                    ]
                }
            ],
        },
    )

    assert ">1.234e4<" in rendered


def test_tag_filter_has_per_tag_removal_without_a_panel_clear_button():
    tag = SimpleNamespace(
        slug="matching",
        label="Matching",
        status="official",
        display_color="#884422",
    )
    rendered = render_to_string(
        "components/filters/grid_cell.html",
        {
            "cell": {
                "type": "tags",
                "key": "algorithm_tags",
                "label": "Algorithm tags",
                "picker_id": "tag-test",
                "input_name": "algorithm_tag",
                "tags": [tag],
                "selected_keys": (tag.slug,),
                "match_name": "algorithm_tag_match",
                "match_value": "all",
                "match_label": "all of",
                "filtered": True,
            }
        },
    )

    assert "data-filter-clear" not in rendered
    assert rendered.count('data-tag-remove="matching"') == 2
