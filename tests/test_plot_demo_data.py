import pytest

from registry.demo import demo_id
from registry.demo_plotting import plot_demo_counts, seed_plot_demo_data
from registry.models import Result
from registry.result_plots import build_result_scatter_plot
from registry.result_tables import with_result_metrics
from registry.services.results import public_result_catalogue


@pytest.mark.django_db(transaction=True)
def test_plot_demo_data_is_rich_idempotent_and_plot_ready():
    first_counts = seed_plot_demo_data()
    second_counts = seed_plot_demo_data()

    assert (
        first_counts
        == second_counts
        == {
            "circuits": 8,
            "decoders": 8,
            "machines": 3,
            "results": 56,
            "scores": 112,
            "tags": 14,
        }
    )
    assert plot_demo_counts() == first_counts
    assert Result.objects.values("decoder_version").distinct().count() == 7
    assert Result.objects.values("circuit_revision").distinct().count() == 8

    results = list(with_result_metrics(public_result_catalogue()).order_by("id"))
    plot = build_result_scatter_plot(results)

    assert plot["total_count"] == 56
    assert plot["plotted_count"] == 54
    assert plot["omitted_count"] == 2
    assert len({point["x_value"] for point in plot["points"]}) > 20
    assert len({point["y_value"] for point in plot["points"]}) > 20


@pytest.mark.django_db
def test_plot_demo_records_are_explicitly_synthetic():
    seed_plot_demo_data()

    synthetic_results = Result.objects.exclude(
        id=demo_id("result/clear-matcher-rotated-memory")
    )
    assert synthetic_results.count() == 55
    assert not synthetic_results.exclude(description__icontains="synthetic").exists()
