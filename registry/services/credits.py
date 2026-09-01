"""Transactional scientific-credit claims and decoder-author approvals."""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from accounts.models import Account
from registry.models import Credit, CreditClaim, Result, ResultAuthorApprovalEvent
from registry.models.attribution import CREDIT_SUBJECT_FIELDS
from registry.models.common import LifecycleState


class CreditError(Exception):
    """Base class for attribution workflow errors."""


class CreditStateError(CreditError):
    """The requested transition is not valid for the current stored state."""


class CreditPermissionError(CreditError):
    """The actor is not allowed to perform the requested transition."""


@dataclass(frozen=True)
class CreditSubject:
    field: str
    kind: str
    label: str
    record: object
    uploader: Account


SUBJECT_PRESENTATION = {
    "decoder_version": ("Decoder version", lambda item: f"{item.name} {item.version}"),
    "noise_model": ("Noise model", lambda item: item.name),
    "circuit_revision": ("Circuit revision", lambda item: item.name),
    "result": (
        "Result",
        lambda item: f"{item.decoder_version} on {item.circuit_revision}",
    ),
    "benchmark_revision": (
        "Benchmark revision",
        lambda item: f"{item.name} {item.version}",
    ),
}

PUBLIC_SUBJECT = (
    Q(decoder_version__state=LifecycleState.PUBLISHED)
    | Q(noise_model__state=LifecycleState.PUBLISHED)
    | Q(circuit_revision__state=LifecycleState.PUBLISHED)
    | Q(result__state=LifecycleState.PUBLISHED)
    | Q(benchmark_revision__state=LifecycleState.PUBLISHED)
)


def searchable_name_credits(query: str) -> QuerySet[Credit]:
    """Return unresolved, public, visible name-only credits matching a name."""

    query = query.strip()
    if not query:
        return Credit.objects.none()
    return claimable_name_credits().filter(display_name__icontains=query).order_by(
        "display_name", "position", "id"
    )


def claimable_name_credits() -> QuerySet[Credit]:
    """Return the public name-credit scope accepted by the write service."""

    return (
        _credits_with_subjects()
        .filter(
            PUBLIC_SUBJECT,
            display_name__isnull=False,
            account__isnull=True,
            hidden_at__isnull=True,
        )
        .exclude(claims__state=CreditClaim.State.APPROVED)
        .distinct()
    )


def describe_credit_subject(credit: Credit) -> CreditSubject:
    field, record = _subject(credit)
    kind, labeler = SUBJECT_PRESENTATION[field]
    return CreditSubject(
        field=field,
        kind=kind,
        label=labeler(record),
        record=record,
        uploader=record.submitted_by,
    )


@transaction.atomic
def submit_credit_claim(
    name_credit_id,
    *,
    claimant: Account,
    retain_name_credit: bool,
) -> CreditClaim:
    _require_active(claimant)
    try:
        name_credit = _credits_with_subjects(for_update=True).get(id=name_credit_id)
    except Credit.DoesNotExist as error:
        raise CreditStateError("The name credit does not exist.") from error
    _require_claimable_name_credit(name_credit)
    subject = describe_credit_subject(name_credit)
    if _account_credit_exists(subject.field, subject.record, claimant):
        raise CreditStateError("This account is already credited on that exact record.")
    existing = CreditClaim.objects.filter(
        name_credit=name_credit,
        claimant_account=claimant,
        state=CreditClaim.State.PENDING,
    ).first()
    if existing is not None and existing.retain_name_credit == retain_name_credit:
        return existing
    if existing is not None:
        raise CreditStateError(
            "This account already has a pending claim for that name."
        )
    return CreditClaim.objects.create(
        name_credit=name_credit,
        claimant_account=claimant,
        retain_name_credit=retain_name_credit,
    )


@transaction.atomic
def cancel_credit_claim(claim_id, *, claimant: Account) -> CreditClaim:
    _require_active(claimant)
    claim = _locked_claim(claim_id)
    if claim.claimant_account_id != claimant.id:
        raise CreditPermissionError("Only the claimant may cancel this claim.")
    if claim.state == CreditClaim.State.CANCELLED:
        return claim
    if claim.state != CreditClaim.State.PENDING:
        raise CreditStateError("Only pending claims may be cancelled.")
    claim.state = CreditClaim.State.CANCELLED
    claim.save(update_fields=["state"])
    return claim


def can_review_credit_claim(claim: CreditClaim, reviewer: Account) -> bool:
    if not reviewer.is_active:
        return False
    subject = describe_credit_subject(claim.name_credit)
    return reviewer.is_admin or subject.uploader.id == reviewer.id


@transaction.atomic
def review_credit_claim(
    claim_id,
    *,
    reviewer: Account,
    approve: bool,
    note: str = "",
) -> CreditClaim:
    _require_active(reviewer)
    claim = _locked_claim(claim_id)
    name_credit = _credits_with_subjects().get(id=claim.name_credit_id)
    claim.name_credit = name_credit
    if not can_review_credit_claim(claim, reviewer):
        raise CreditPermissionError(
            "Only the record uploader or an administrator may review this claim."
        )

    intended_state = (
        CreditClaim.State.APPROVED if approve else CreditClaim.State.REJECTED
    )
    if claim.state == intended_state:
        return claim
    if claim.state != CreditClaim.State.PENDING:
        raise CreditStateError("Only pending claims may be reviewed.")

    reviewed_at = timezone.now()
    note = note.strip() or None
    if not approve:
        claim.state = CreditClaim.State.REJECTED
        claim.reviewed_by = reviewer
        claim.reviewed_at = reviewed_at
        claim.review_note = note
        claim.save(
            update_fields=["state", "reviewed_by", "reviewed_at", "review_note"]
        )
        return claim

    subject = describe_credit_subject(name_credit)
    type(subject.record).objects.select_for_update().get(id=subject.record.id)
    _lock_subject_credits(subject.field, subject.record)
    name_credit.refresh_from_db()
    _require_claimable_name_credit(name_credit)
    if CreditClaim.objects.filter(
        name_credit=name_credit,
        state=CreditClaim.State.APPROVED,
    ).exclude(id=claim.id).exists():
        raise CreditStateError("That name credit has already been claimed.")
    if _account_credit_exists(subject.field, subject.record, claim.claimant_account):
        raise CreditStateError("The claimant is already credited on that exact record.")

    if claim.retain_name_credit:
        position = _next_visible_position(subject.field, subject.record)
    else:
        position = name_credit.position
        name_credit.hidden_at = reviewed_at
        name_credit.save(update_fields=["hidden_at"])

    account_credit = Credit.objects.create(
        **{
            subject.field: subject.record,
            "position": position,
            "account": claim.claimant_account,
        }
    )
    claim.state = CreditClaim.State.APPROVED
    claim.reviewed_by = reviewer
    claim.reviewed_at = reviewed_at
    claim.review_note = note
    claim.created_account_credit = account_credit
    claim.save(
        update_fields=[
            "state",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_account_credit",
        ]
    )
    return claim


def current_result_author_approval(
    result: Result, account: Account
) -> ResultAuthorApprovalEvent | None:
    return (
        ResultAuthorApprovalEvent.objects.filter(result=result, account=account)
        .order_by("-created_at", "-id")
        .first()
    )


def is_exact_decoder_author(account: Account, result: Result) -> bool:
    return Credit.objects.filter(
        decoder_version=result.decoder_version,
        account=account,
        hidden_at__isnull=True,
    ).exists()


@transaction.atomic
def set_result_author_approval(
    result_id,
    *,
    account: Account,
    approve: bool,
    note: str = "",
) -> ResultAuthorApprovalEvent:
    _require_active(account)
    try:
        result = (
            Result.objects.select_for_update()
            .select_related("decoder_version", "circuit_revision")
            .get(id=result_id)
        )
    except Result.DoesNotExist as error:
        raise CreditStateError("The result does not exist.") from error
    if result.state != LifecycleState.PUBLISHED:
        raise CreditStateError("Only published results may receive author approval.")
    if not is_exact_decoder_author(account, result):
        raise CreditPermissionError(
            "Only an author credited on this exact decoder version may act."
        )

    action = (
        ResultAuthorApprovalEvent.Action.APPROVE
        if approve
        else ResultAuthorApprovalEvent.Action.REVOKE
    )
    current = current_result_author_approval(result, account)
    if current is not None and current.action == action:
        return current
    if not approve and current is None:
        raise CreditStateError("There is no author approval to revoke.")
    return ResultAuthorApprovalEvent.objects.create(
        result=result,
        account=account,
        action=action,
        note=note.strip() or None,
    )


def _credits_with_subjects(*, for_update: bool = False) -> QuerySet[Credit]:
    queryset = Credit.objects.select_related(
        "account",
        "decoder_version__submitted_by",
        "noise_model__submitted_by",
        "circuit_revision__submitted_by",
        "result__submitted_by",
        "result__decoder_version",
        "result__circuit_revision",
        "benchmark_revision__submitted_by",
    )
    return queryset.select_for_update(of=("self",)) if for_update else queryset


def _locked_claim(claim_id) -> CreditClaim:
    try:
        return (
            CreditClaim.objects.select_for_update(of=("self",))
            .select_related("claimant_account", "reviewed_by", "created_account_credit")
            .get(id=claim_id)
        )
    except CreditClaim.DoesNotExist as error:
        raise CreditStateError("The credit claim does not exist.") from error


def _subject(credit: Credit) -> tuple[str, object]:
    for field in CREDIT_SUBJECT_FIELDS:
        record = getattr(credit, field)
        if record is not None:
            return field, record
    raise CreditStateError("The credit has no scientific record.")


def _require_claimable_name_credit(credit: Credit) -> None:
    if credit.account_id is not None or credit.display_name is None:
        raise CreditStateError("Only a name-only credit may be claimed.")
    if credit.hidden_at is not None:
        raise CreditStateError("A hidden name credit may not be claimed.")
    subject = describe_credit_subject(credit)
    if subject.record.state != LifecycleState.PUBLISHED:
        raise CreditStateError("Only credits on published records may be claimed.")
    if CreditClaim.objects.filter(
        name_credit=credit, state=CreditClaim.State.APPROVED
    ).exists():
        raise CreditStateError("That name credit has already been claimed.")


def _require_active(account: Account) -> None:
    if not account.is_active:
        raise CreditPermissionError("An active account is required.")


def _subject_filter(field: str, record) -> dict[str, object]:
    return {field: record}


def _account_credit_exists(field: str, record, account: Account) -> bool:
    return Credit.objects.filter(
        **_subject_filter(field, record), account=account, hidden_at__isnull=True
    ).exists()


def _lock_subject_credits(field: str, record) -> list[Credit]:
    return list(
        Credit.objects.select_for_update()
        .filter(**_subject_filter(field, record))
        .order_by("position", "id")
    )


def _next_visible_position(field: str, record) -> int:
    maximum = (
        Credit.objects.filter(
            **_subject_filter(field, record), hidden_at__isnull=True
        ).aggregate(maximum=Max("position"))["maximum"]
        or 0
    )
    return maximum + 1
