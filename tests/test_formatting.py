import json
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.template.loader import render_to_string

from registry.filter_grids import range_cell
from registry.formatting import (
    format_scientific_range,
    format_scientific_value,
    scientific_number_display,
)

CASES_PATH = Path(__file__).parent / "fixtures" / "scientific_numbers.json"


def test_scientific_values_use_compact_significant_digits():
    assert format_scientific_value(Decimal("0.02300000000000000000")) == "2.3 · 10⁻²"
    assert format_scientific_value(Decimal("0.00230000000000000000")) == "2.3 · 10⁻³"
    assert format_scientific_value(Decimal("0.15000000000000000000")) == "0.15"
    assert format_scientific_value(Decimal("1.23456")) == "1.235"
    assert format_scientific_value(Decimal("12340")) == "1.234 · 10⁴"
    assert format_scientific_value(Decimal("-12340")) == "-1.234 · 10⁴"
    assert format_scientific_value(Decimal("99995")) == "1 · 10⁵"
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
        == "2.3 · 10⁻³–2.5 · 10⁷"
    )
    assert format_scientific_range("", "25000000") == "0–2.5 · 10⁷"


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

    assert cell["display_minimum"] == "1 · 10⁴"
    assert cell["display_maximum"] == "2.5 · 10⁷"
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

    assert 'data-raw="12340"' in rendered
    assert "1.234" in rendered
    assert "10<sup>4</sup>" in rendered


def test_structured_number_retains_raw_precision_and_accessible_parts():
    number = scientific_number_display(Decimal("0.002300000"), unit="s")

    assert number.raw == "0.002300000"
    assert number.mantissa == "2.3"
    assert number.exponent == -3
    assert number.text == "2.3 · 10⁻³"
    assert number.accessible_text == "2.3 times ten to the power of -3"
    assert number.unit == "s"


def test_python_renderer_matches_shared_conformance_cases():
    cases = json.loads(CASES_PATH.read_text())

    for case in cases:
        assert (
            format_scientific_value(case["value"], profile=case["profile"])
            == case["text"]
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_javascript_renderer_matches_shared_conformance_cases():
    script_path = Path(__file__).parents[1] / "static" / "js" / "scientific-format.js"
    javascript = """
const fs = require("fs");
eval(fs.readFileSync(process.argv[1], "utf8"));
const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
process.stdout.write(JSON.stringify(cases.map((item) =>
  CircuitBenchNumber.format(item.value, { profile: item.profile })
)));
"""
    completed = subprocess.run(
        ["node", "-e", javascript, str(script_path), str(CASES_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = json.loads(completed.stdout)
    expected = [case["text"] for case in json.loads(CASES_PATH.read_text())]

    assert actual == expected


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
