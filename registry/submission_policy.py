"""Versioned policy decisions for registry submissions.

Validation answers whether a record is scientifically and structurally admissible.
This module separately answers what governance step follows a valid submission.
Keeping those questions apart lets policy change without changing forms or records.
"""

from dataclasses import dataclass
from enum import StrEnum

from accounts.models import Account
from registry.models.common import LifecycleState


class SubmissionKind(StrEnum):
    DECODER = "decoder"
    CIRCUIT = "circuit"
    RESULT = "result"
    MACHINE = "machine"


class ApprovalRoute(StrEnum):
    ADMIN_REVIEW = "admin_review"
    IMMEDIATE_PUBLICATION = "immediate_publication"


@dataclass(frozen=True)
class ApprovalDecision:
    policy_version: str
    route: ApprovalRoute
    initial_state: str
    explanation: str

    @property
    def requires_review(self) -> bool:
        return self.route == ApprovalRoute.ADMIN_REVIEW


POLICY_VERSION = "0.1"


def approval_decision(
    kind: SubmissionKind | str,
    submitter: Account,
    *,
    reapproval: bool = False,
) -> ApprovalDecision:
    """Return the current explicit route for this kind and submitter.

    ``submitter`` is deliberately part of the interface although policy 0.1 does
    not grant admins a shortcut. Future versions can add trusted-uploader or
    record-owner rules without altering the submission service.
    """

    kind = SubmissionKind(kind)
    if not submitter.is_active:
        raise ValueError("Inactive accounts cannot submit records.")

    if reapproval:
        return ApprovalDecision(
            policy_version=POLICY_VERSION,
            route=ApprovalRoute.ADMIN_REVIEW,
            initial_state=LifecycleState.PENDING_REAPPROVAL,
            explanation=(
                "A successor to a withdrawn record requires admin reapproval, "
                "including when its record kind normally publishes immediately."
            ),
        )

    if kind is SubmissionKind.MACHINE:
        return ApprovalDecision(
            policy_version=POLICY_VERSION,
            route=ApprovalRoute.IMMEDIATE_PUBLICATION,
            initial_state=LifecycleState.PUBLISHED,
            explanation=(
                "Machine records publish immediately after validation; they do not "
                "enter the approval queue."
            ),
        )

    return ApprovalDecision(
        policy_version=POLICY_VERSION,
        route=ApprovalRoute.ADMIN_REVIEW,
        initial_state=LifecycleState.PENDING_REVIEW,
        explanation=(
            "Decoder, circuit, and result submissions require admin approval under "
            "policy 0.1, including submissions made by admins."
        ),
    )
