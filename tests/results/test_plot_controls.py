from decimal import Decimal
from uuid import UUID

from registry.models import Result
from registry.plot_controls import plot_control_grids
from registry.result_query import FIELD_BY_NAME, metric_component_annotation


def _result(identifier, shots, ler):
    result = Result(
        id=UUID(f"00000000-0000-0000-0000-{identifier:012d}"),
        shots_total=shots,
    )
    result.metric_ler_upper_95_at_5pct_acceptance_v0_1 = ler
    field = FIELD_BY_NAME["score_ler_upper_95_at_5pct_acceptance_v0_1"]
    setattr(
        result,
        metric_component_annotation(field, "lower_bound"),
        ler * Decimal("0.7"),
    )
    setattr(result, metric_component_annotation(field, "upper_bound"), ler)
    return result


def test_plot_controls_declare_main_and_advanced_reusable_grids():
    fields = (
        FIELD_BY_NAME["shots_total"],
        FIELD_BY_NAME["score_ler_upper_95_at_5pct_acceptance_v0_1"],
    )

    main, advanced = plot_control_grids(
        plot_id="test-plot",
        results=[_result(1, 10, Decimal("0.1")), _result(2, 20, Decimal("0.2"))],
        numeric_fields=fields,
        x_field="shots_total",
        y_field="score_ler_upper_95_at_5pct_acceptance_v0_1",
        x_scale="linear",
        y_scale="log",
        x_minimum="",
        x_maximum="20",
        y_minimum="0.05",
        y_maximum="",
        major_gridlines=True,
        minor_gridlines=False,
        marker_style="diamond",
        marker_colour="theme",
    )

    assert main["id"] == "test-plot-main-settings"
    assert main["open"] is True
    assert [cell["type"] for cell in main["cells"]] == [
        "axis",
        "choice",
        "range",
        "axis",
        "choice",
        "range",
    ]
    assert main["cells"][0]["display_value"] == "Shots (shots)"
    assert main["cells"][2]["histogram"]["counts"][-1] == 1
    assert main["cells"][2]["display_maximum"] == "20"
    assert main["cells"][2]["display_value"] == "auto–20"
    assert advanced["open"] is False
    assert advanced["cells"][0]["checked"] is True
    assert advanced["cells"][1]["checked"] is False
    assert advanced["cells"][2]["display_value"] == "Whisker bars"
    assert advanced["cells"][3]["display_value"] == "Diamond"
    assert main["cells"][3]["options"][1]["interval_count"] == 2
    assert main["cells"][3]["options"][1]["interval_label"] == "2 stored intervals"


def test_plot_range_labels_are_compact_without_changing_submitted_values():
    fields = (
        FIELD_BY_NAME["shots_total"],
        FIELD_BY_NAME["score_ler_upper_95_at_5pct_acceptance_v0_1"],
    )

    main, _advanced = plot_control_grids(
        plot_id="test-plot",
        results=[_result(1, 10, Decimal("0.1"))],
        numeric_fields=fields,
        x_field="shots_total",
        y_field="score_ler_upper_95_at_5pct_acceptance_v0_1",
        x_scale="linear",
        y_scale="linear",
        x_minimum="0.002300000000",
        x_maximum="25000000",
        y_minimum="",
        y_maximum="",
        major_gridlines=True,
        minor_gridlines=True,
        marker_style="circle",
        marker_colour="theme",
    )

    range_control = main["cells"][2]
    assert range_control["display_value"] == "2.3e-3–2.5e7"
    assert range_control["minimum_value"] == "0.002300000000"
    assert range_control["maximum_value"] == "25000000"
