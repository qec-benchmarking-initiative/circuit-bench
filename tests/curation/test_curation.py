from uuid import UUID

import pytest

from registry.curation import (
    FEATURED_POLICIES,
    CatalogueKind,
    CatalogueOrderingMode,
    CurationPolicy,
    apply_featured_ordering,
    apply_search_relevance,
    featured_policy,
    featured_reason,
    ordering_metadata,
    select_catalogue_ordering,
)
from registry.demo import seed_demo_data
from registry.models import DecoderVersion, NoiseModel
from registry.services.benchmarks import public_benchmark_catalogue
from registry.services.circuits import circuit_catalogue, noise_model_catalogue
from registry.services.decoders import public_decoder_catalogue


def test_ordering_mode_keeps_featured_search_and_manual_separate():
    featured = select_catalogue_ordering(search_query="", raw_sort="")
    search = select_catalogue_ordering(search_query="  memory  ", raw_sort="")
    manual = select_catalogue_ordering(
        search_query="memory",
        raw_sort="-published,name",
    )

    assert featured.mode == CatalogueOrderingMode.FEATURED
    assert search.mode == CatalogueOrderingMode.SEARCH_RELEVANCE
    assert search.search_query == "memory"
    assert manual.mode == CatalogueOrderingMode.MANUAL


def test_each_catalogue_has_a_named_disclosed_provisional_policy():
    assert set(FEATURED_POLICIES) == set(CatalogueKind)

    for kind in CatalogueKind:
        policy = featured_policy(kind)
        assert isinstance(policy, CurationPolicy)
        assert policy.key.startswith("provisional-featured-")
        assert "provisional" in policy.label.lower()
        assert "scientific ranking" in policy.explanation.lower()
        assert policy.ordering[-1] == "id"
        assert policy.required_annotations


def test_ordering_metadata_is_suitable_for_visible_disclosure():
    featured = select_catalogue_ordering(search_query="", raw_sort="")
    search = select_catalogue_ordering(search_query="memory", raw_sort="")
    manual = select_catalogue_ordering(search_query="", raw_sort="name")

    featured_context = ordering_metadata(featured, "circuit").as_context()
    search_context = ordering_metadata(search, "circuit").as_context()
    manual_context = ordering_metadata(manual, "circuit").as_context()

    assert featured_context == {
        "key": "featured",
        "label": "Featured circuits (provisional)",
        "explanation": (
            "Discovery order uses published-result activity, then publication "
            "date, name, and record ID. It is not a scientific ranking."
        ),
        "provisional": True,
        "policy_key": "provisional-featured-circuits-0.1",
    }
    assert search_context["label"] == "Search relevance"
    assert search_context["provisional"] is False
    assert manual_context["label"] == "Selected table order"
    assert manual_context["policy_key"] is None


@pytest.fixture
def demo_catalogues(db):
    seed_demo_data()


def test_featured_policies_use_existing_catalogue_annotations(demo_catalogues):
    decoders = list(apply_featured_ordering(public_decoder_catalogue(), "decoder"))
    circuits = list(apply_featured_ordering(circuit_catalogue(), "circuit"))
    noise_models = list(apply_featured_ordering(noise_model_catalogue(), "noise_model"))
    benchmarks = list(
        apply_featured_ordering(public_benchmark_catalogue(), "benchmark")
    )

    assert [decoder.slug for decoder in decoders] == [
        "clear-matcher-0-2",
        "clear-matcher-0-1",
    ]
    assert [circuit.slug for circuit in circuits] == ["rotated-memory-d5"]
    assert [noise_model.slug for noise_model in noise_models] == [
        "fixed-phenomenological",
        "randomised-phenomenological",
    ]
    assert [benchmark.slug for benchmark in benchmarks] == ["memory-smoke-test-0-1"]


def test_featured_policy_fails_clearly_without_its_catalogue_annotation(
    demo_catalogues,
):
    with pytest.raises(ValueError, match="published_result_count"):
        apply_featured_ordering(DecoderVersion.objects.all(), "decoder")


def test_featured_ties_end_in_stable_uuid_order(demo_catalogues):
    source = DecoderVersion.objects.get(slug="clear-matcher-0-1")
    shared = {
        "schema_release": source.schema_release,
        "name": "Tied decoder",
        "version": "0.1",
        "description": "Fixture for deterministic curation ordering.",
        "revision_description": "first revision",
        "circuit_skeleton_preparation": "not_required",
        "circuit_priors_preparation": "not_required",
        "provides_failure_probability": True,
        "submitted_by": source.submitted_by,
        "state": "published",
        "published_at": source.published_at,
    }
    later_id = UUID("00000000-0000-0000-0000-000000000002")
    earlier_id = UUID("00000000-0000-0000-0000-000000000001")
    DecoderVersion.objects.create(id=later_id, slug="tied-decoder-b", **shared)
    DecoderVersion.objects.create(id=earlier_id, slug="tied-decoder-a", **shared)

    tied = apply_featured_ordering(
        public_decoder_catalogue(query="Tied decoder"),
        "decoder",
    )

    assert list(tied.values_list("id", flat=True)) == [earlier_id, later_id]


def test_featured_reasons_expose_the_fields_that_determined_position(
    demo_catalogues,
):
    decoder = apply_featured_ordering(public_decoder_catalogue(), "decoder").first()
    noise_model = apply_featured_ordering(
        noise_model_catalogue(), "noise_model"
    ).first()
    benchmark = apply_featured_ordering(
        public_benchmark_catalogue(), "benchmark"
    ).first()

    assert featured_reason(decoder, "decoder").as_context() == {
        "label": "1 published result",
        "detail": (
            "This provisional decoder order uses published-result activity; "
            "equal counts use publication date, name, then record ID."
        ),
    }
    assert featured_reason(noise_model, "noise_model").label == (
        "Official · 1 published circuit"
    )
    assert featured_reason(benchmark, "benchmark").label == (
        "Admin approved · 1 published attempt"
    )


def test_search_relevance_is_exact_then_prefix_then_stably_tied(demo_catalogues):
    exact = NoiseModel.objects.get(slug="randomised-phenomenological")
    exact.name = "Phenomenological"
    exact.save(update_fields=["name"])

    queryset = noise_model_catalogue(query="phenomenological")
    ordered = apply_search_relevance(
        queryset,
        "noise_model",
        "phenomenological",
    )

    assert [item.slug for item in ordered] == [
        "randomised-phenomenological",
        "fixed-phenomenological",
    ]
    assert ordered.query.order_by[-1] == "id"


def test_empty_search_cannot_silently_become_a_relevance_order(demo_catalogues):
    with pytest.raises(ValueError, match="non-empty query"):
        apply_search_relevance(noise_model_catalogue(), "noise_model", "  ")
