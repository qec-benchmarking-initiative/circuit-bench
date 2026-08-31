import pytest
from django.urls import reverse

from registry.demo_plotting import seed_plot_demo_data

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def plotting_population():
    seed_plot_demo_data()


@pytest.mark.parametrize(
    ("route_name", "slug", "expected_count", "plot_id"),
    [
        ("circuits:detail", "rotated-memory-d5", 7, "circuit-results-scatter"),
        ("decoders:detail", "clear-matcher-0-2", 8, "decoder-results-scatter"),
        ("machines:detail", "demo-eight-core-cpu", 16, "machine-results-scatter"),
        ("benchmarks:detail", "memory-smoke-test-0-1", 1, "benchmark-results-scatter"),
    ],
)
def test_every_result_bearing_data_view_has_query_plot_and_exports(
    client, route_name, slug, expected_count, plot_id
):
    response = client.get(reverse(route_name, args=[slug]))

    assert response.status_code == 200
    assert response.context["result_count"] == expected_count
    content = response.content.decode()
    assert "Scripted query (OData 4.01 subset)" in content
    assert f'id="{plot_id}"' in content
    assert 'name="plot_x"' in content
    assert 'name="plot_y"' in content
    assert "Logarithmic" in content
    assert "Download SVG" in content
    assert 'aria-label="Plot data formats"' in content
    assert ">JSON</a>" in content
    assert ">CSV</a>" in content
    assert "js/result-plot.js" in content


def test_scoped_scripted_query_drives_circuit_table_plot_and_api(client):
    response = client.get(
        reverse("circuits:detail", args=["rotated-memory-d5"]),
        {"odata": "$filter=decoder_name eq 'Streaming Cluster'"},
    )

    assert response.status_code == 200
    assert response.context["result_count"] == 1
    assert response.context["result_plot"]["total_count"] == 1
    [point] = response.context["result_plot"]["points"]
    assert point["label"] == "Streaming Cluster v0.1"
    assert point["link_url"] == reverse(
        "decoders:detail", args=["streaming-cluster-0-1"]
    )

    api = client.get(response.context["result_plot"]["json_url"])
    assert api.status_code == 200
    assert api.json()["ordered_result_ids"] == response.context["ordered_result_ids"]
    assert "scope_circuit=rotated-memory-d5" in response.context["json_url"]


def test_decoder_plot_labels_points_by_circuit_and_supports_axis_controls(client):
    response = client.get(
        reverse("decoders:detail", args=["clear-matcher-0-2"]),
        {
            "plot_x": "shots_total",
            "plot_y": "score_brier_loss_upper_95_v0_1",
            "plot_x_scale": "log",
            "plot_y_scale": "log",
            "plot_open": "1",
        },
    )

    plot = response.context["result_plot"]
    assert plot["x_axis"]["field"] == "shots_total"
    assert plot["y_axis"]["field"] == "score_brier_loss_upper_95_v0_1"
    assert plot["x_axis"]["scale"] == plot["y_axis"]["scale"] == "log"
    assert plot["is_open"] is True
    assert {point["label"] for point in plot["points"]} >= {
        "Rotated surface-code memory d=5",
        "Bivariate bicycle 144 memory",
    }
    assert all(tick["label"] for tick in plot["x_axis"]["ticks"])


def test_result_page_points_name_both_decoder_and_circuit(client):
    response = client.get(reverse("results:list"), {"$top": "2", "plot_open": "1"})

    assert response.status_code == 200
    assert response.context["result_plot"]["total_count"] == 2
    for point in response.context["result_plot"]["points"]:
        assert " v0." in point["label"]
        assert " · " in point["label"]
    content = response.content.decode()
    assert 'data-summary-id="all-results-scatter-summary-' in content
    assert "Selected point" in content
