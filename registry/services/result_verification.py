"""Server-derived reproduction status for exact result records."""

from django.db import transaction
from django.db.models import OuterRef, Q, Subquery

from registry.models import Credit, Result, ResultAuthorApprovalEvent


def account_is_credited_on_decoder(*, account_id, decoder_version_id) -> bool:
    """Return whether an account has a visible credit on one exact decoder."""

    return Credit.objects.filter(
        decoder_version_id=decoder_version_id,
        account_id=account_id,
        hidden_at__isnull=True,
    ).exists()


def derive_result_reproduction_status(result: Result) -> str:
    """Derive the status from current exact-version credits and approvals."""

    if account_is_credited_on_decoder(
        account_id=result.submitted_by_id,
        decoder_version_id=result.decoder_version_id,
    ):
        return Result.ReproductionStatus.AUTHOR_VERIFIED

    latest_action = (
        ResultAuthorApprovalEvent.objects.filter(
            result_id=result.id,
            account_id=OuterRef("account_id"),
        )
        .order_by("-created_at", "-id")
        .values("action")[:1]
    )
    has_active_author_approval = (
        Credit.objects.filter(
            decoder_version_id=result.decoder_version_id,
            account__isnull=False,
            hidden_at__isnull=True,
        )
        .annotate(latest_result_action=Subquery(latest_action))
        .filter(latest_result_action=ResultAuthorApprovalEvent.Action.APPROVE)
        .exists()
    )
    if has_active_author_approval:
        return Result.ReproductionStatus.AUTHOR_VERIFIED
    return Result.ReproductionStatus.INDEPENDENT


def recompute_result_reproduction_status(result: Result) -> str:
    """Persist the current derived status when the stored value is stale."""

    status = derive_result_reproduction_status(result)
    if result.reproduction_status != status:
        Result.objects.filter(id=result.id).update(reproduction_status=status)
        result.reproduction_status = status
    return status


@transaction.atomic
def recompute_decoder_results_for_account(*, decoder_version_id, account_id) -> int:
    """Recompute results whose status can change when one decoder credit changes."""

    affected_ids = (
        Result.objects.filter(decoder_version_id=decoder_version_id)
        .filter(
            Q(submitted_by_id=account_id)
            | Q(author_approval_events__account_id=account_id)
        )
        .values("id")
    )
    affected = (
        Result.objects.select_for_update()
        .filter(decoder_version_id=decoder_version_id)
        .filter(id__in=Subquery(affected_ids))
        .order_by("id")
    )
    changed = 0
    for result in affected:
        previous = result.reproduction_status
        recompute_result_reproduction_status(result)
        changed += result.reproduction_status != previous
    return changed
