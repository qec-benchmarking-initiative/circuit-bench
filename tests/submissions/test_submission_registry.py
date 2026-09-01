import pytest

from registry.models.common import (
    EDITABLE_CANDIDATE_STATES,
    REVIEW_QUEUE_STATES,
    LifecycleState,
)
from registry.submission_policy import ENABLED_SUBMISSION_KINDS, SubmissionKind
from registry.submission_registry import (
    LINEAGE_FIELD_BY_KIND,
    MODEL_BY_KIND,
    enabled_submission_registrations,
    submission_registration,
)


def test_enabled_submission_kinds_have_one_complete_registration():
    registrations = enabled_submission_registrations()

    assert tuple(item.kind for item in registrations) == ENABLED_SUBMISSION_KINDS
    assert set(MODEL_BY_KIND) == set(ENABLED_SUBMISSION_KINDS)
    assert set(LINEAGE_FIELD_BY_KIND) == set(ENABLED_SUBMISSION_KINDS)
    assert all(item.public_route_name for item in registrations)
    assert all(item.public_argument_attribute for item in registrations)


@pytest.mark.parametrize(
    "kind",
    [
        SubmissionKind.TAG,
        SubmissionKind.NOISE_MODEL,
        SubmissionKind.BENCHMARK,
        SubmissionKind.BENCHMARK_ATTEMPT,
    ],
)
def test_incomplete_submission_kinds_are_not_exposed(kind):
    with pytest.raises(KeyError, match="not enabled"):
        submission_registration(kind)


def test_review_and_edit_state_sets_have_distinct_meanings():
    assert REVIEW_QUEUE_STATES == (
        LifecycleState.PENDING_REVIEW,
        LifecycleState.PENDING_REAPPROVAL,
    )
    assert EDITABLE_CANDIDATE_STATES == (
        *REVIEW_QUEUE_STATES,
        LifecycleState.CHANGES_REQUESTED,
    )
    assert LifecycleState.REJECTED not in EDITABLE_CANDIDATE_STATES
