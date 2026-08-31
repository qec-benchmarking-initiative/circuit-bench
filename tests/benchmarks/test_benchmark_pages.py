import pytest
from django.urls import reverse
from django.utils import timezone

from registry.demo import seed_demo_data
from registry.models import (
    BenchmarkAttempt,
    BenchmarkAttemptResult,
    BenchmarkRevision,
    BenchmarkRevisionItem,
    DecoderVersion,
)
from registry.services.benchmarks import public_benchmark_catalogue, summarise_attempts

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def benchmark_url_configuration(settings):
    settings.ROOT_URLCONF = "tests.benchmarks.urls"


@pytest.fixture
def demo_benchmark():
    seed_demo_data()
    return BenchmarkRevision.objects.get(slug="memory-smoke-test-0-1")


def test_catalogue_is_searchable_compact_and_deterministic(client, demo_benchmark):
    response = client.get(
        reverse("benchmarks:list"),
        {
            "q": "memory smoke",
            "recognition": "admin_approved",
            "sort": "-attempts,name",
            "columns": "name,recognition,required,optional,attempts",
        },
    )

    assert response.status_code == 200
    assert [item.id for item in response.context["benchmarks"]] == [demo_benchmark.id]
    assert response.context["sort_summary"] == (
        "Attempts descending, Benchmark ascending"
    )
    assert [column["key"] for column in response.context["table_columns"]] == [
        "name",
        "recognition",
        "required",
        "optional",
        "attempts",
    ]
    content = response.content.decode()
    assert "Admin approved" in content
    assert "Table view options (5/7)" in content
    assert "1 exact published benchmark revision" in content


def test_catalogue_never_discovers_nonpublished_revisions(client, demo_benchmark):
    BenchmarkRevision.objects.filter(pk=demo_benchmark.pk).update(
        state="pending_review",
        published_at=None,
    )

    response = client.get(reverse("benchmarks:list"), {"q": "memory"})

    assert response.status_code == 200
    assert list(response.context["benchmarks"]) == []
    assert b"Memory smoke test" not in response.content


def test_detail_renders_exact_revision_and_ordered_manifest(client, demo_benchmark):
    response = client.get(reverse("benchmarks:detail", args=[demo_benchmark.slug]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Benchmark revision" in content
    assert "Memory smoke test" in content
    assert "Admin approved" in content
    assert "first revision" in content
    assert "demo-memory-benchmark-manifest.json" in content
    assert str(demo_benchmark.id) in content
    manifest_item = BenchmarkRevisionItem.objects.get(benchmark_revision=demo_benchmark)
    assert str(manifest_item.circuit_revision_id) in content
    assert content.index("Position") < content.index("Rotated surface-code memory d=5")
    assert "Required" in content


def test_attempt_links_exactly_one_result_for_each_required_circuit(
    client, demo_benchmark
):
    membership = BenchmarkAttemptResult.objects.select_related("result").get()

    response = client.get(reverse("benchmarks:detail", args=[demo_benchmark.slug]))

    summary = response.context["attempt_summaries"][0]
    assert summary.is_complete is True
    assert summary.required_count == 1
    assert summary.required_result_count == 1
    assert summary.items[0].membership == membership
    content = response.content.decode()
    assert "1 of 1 required circuits have exactly one matching public result" in content
    assert str(membership.result_id) in content
    assert "does not pool" in content
    assert "Best score" not in content


def test_missing_required_result_is_reported_without_recomputing(
    client, demo_benchmark
):
    BenchmarkAttemptResult.objects.all().delete()

    response = client.get(reverse("benchmarks:detail", args=[demo_benchmark.slug]))

    summary = response.context["attempt_summaries"][0]
    assert summary.is_complete is False
    assert summary.required_result_count == 0
    assert summary.issues == (
        "Manifest position 1 does not have exactly one public result.",
    )
    assert b"Required circuit does not have exactly one result" in response.content


def test_mismatched_decoder_marks_attempt_inconsistent(client, demo_benchmark):
    membership = BenchmarkAttemptResult.objects.select_related("result").get()
    other_decoder = DecoderVersion.objects.get(slug="clear-matcher-0-1")
    membership.result.decoder_version = other_decoder
    membership.result.save(update_fields=["decoder_version"])

    response = client.get(reverse("benchmarks:detail", args=[demo_benchmark.slug]))

    summary = response.context["attempt_summaries"][0]
    assert summary.is_complete is False
    assert summary.required_result_count == 0
    assert "different decoder" in response.content.decode()


def test_nonpublished_attempts_are_not_exposed(client, demo_benchmark):
    attempt = BenchmarkAttempt.objects.get()
    BenchmarkAttempt.objects.filter(pk=attempt.pk).update(
        state="pending_review",
        published_at=None,
    )

    response = client.get(reverse("benchmarks:detail", args=[demo_benchmark.slug]))

    assert response.context["attempt_summaries"] == ()
    assert str(attempt.id).encode() not in response.content
    assert b"No published attempts" in response.content


def test_withdrawn_exact_revision_resolves_but_leaves_discovery(client, demo_benchmark):
    BenchmarkRevision.objects.filter(pk=demo_benchmark.pk).update(
        state="withdrawn",
        withdrawn_at=timezone.now(),
    )

    detail = client.get(reverse("benchmarks:detail", args=[demo_benchmark.slug]))
    catalogue = client.get(reverse("benchmarks:list"))

    assert detail.status_code == 200
    assert b"Withdrawn" in detail.content
    assert list(catalogue.context["benchmarks"]) == []


def test_catalogue_service_uses_uuid_as_stable_final_ordering(demo_benchmark):
    query = public_benchmark_catalogue().order_by("name", "id")

    assert list(query.values_list("id", flat=True)) == [demo_benchmark.id]


def test_attempt_summary_order_follows_manifest_positions(demo_benchmark):
    benchmark = (
        BenchmarkRevision.objects.filter(pk=demo_benchmark.pk)
        .prefetch_related("items", "attempts__result_memberships")
        .get()
    )
    # The service summary requires the explicitly bounded display attributes.
    from registry.services.benchmarks import public_benchmark_detail

    benchmark = public_benchmark_detail().get(pk=benchmark.pk)
    summary = summarise_attempts(benchmark)[0]

    assert [row.item.position for row in summary.items] == [1]
