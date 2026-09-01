import pytest

from registry.demo import demo_counts, seed_demo_data
from registry.models import BenchmarkAttemptResult, DecoderVersion, Result


@pytest.mark.django_db(transaction=True)
def test_demo_data_is_complete_and_idempotent():
    first_counts = seed_demo_data()
    second_counts = seed_demo_data()

    assert (
        first_counts
        == second_counts
        == {
            "accounts": 2,
            "artifacts": 21,
            "benchmarks": 1,
            "circuits": 1,
            "decoders": 2,
            "noise_models": 2,
            "results": 1,
            "scores": 2,
            "tags": 4,
        }
    )
    decoder = DecoderVersion.objects.get(slug="clear-matcher-0-2")
    assert decoder.description is None
    assert decoder.previous_version.description.startswith("A compact matching")

    result = Result.objects.get()
    assert result.shots_total == (
        result.successful_shots
        + result.logical_failure_shots
        + result.timeout_shots
        + result.decoder_error_shots
    )
    assert BenchmarkAttemptResult.objects.get().result == result
    assert demo_counts() == first_counts
