from django.conf import settings
from django.db import models

from .common import UUIDModel, exactly_one_not_null

CREDIT_SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "result",
    "benchmark_revision",
)


class Credit(UUIDModel):
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    noise_model = models.ForeignKey(
        "registry.NoiseModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    result = models.ForeignKey(
        "registry.Result",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    benchmark_revision = models.ForeignKey(
        "registry.BenchmarkRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    position = models.PositiveIntegerField()
    display_name = models.CharField(max_length=200, null=True, blank=True)
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credits",
    )
    hidden_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "credit"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="credit_position_positive",
            ),
            models.CheckConstraint(
                condition=exactly_one_not_null(*CREDIT_SUBJECT_FIELDS),
                name="credit_one_subject",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(display_name__isnull=False, account__isnull=True)
                    | models.Q(display_name__isnull=True, account__isnull=False)
                ),
                name="credit_one_identity_form",
            ),
            models.CheckConstraint(
                condition=models.Q(account__isnull=True)
                | models.Q(hidden_at__isnull=True),
                name="credit_account_not_hidden",
            ),
            *[
                models.UniqueConstraint(
                    fields=[subject, "position"],
                    condition=(
                        models.Q(**{f"{subject}__isnull": False})
                        & models.Q(hidden_at__isnull=True)
                    ),
                    name=f"credit_{subject}_visible_position_uniq",
                )
                for subject in CREDIT_SUBJECT_FIELDS
            ],
            *[
                models.UniqueConstraint(
                    fields=[subject, "account"],
                    condition=(
                        models.Q(**{f"{subject}__isnull": False})
                        & models.Q(account__isnull=False)
                        & models.Q(hidden_at__isnull=True)
                    ),
                    name=f"credit_{subject}_visible_account_uniq",
                )
                for subject in CREDIT_SUBJECT_FIELDS
            ],
        ]
        indexes = [
            models.Index(
                fields=["account"],
                condition=(
                    models.Q(account__isnull=False) & models.Q(hidden_at__isnull=True)
                ),
                name="idx_credit_account",
            )
        ]

    def __str__(self) -> str:
        return self.display_name or str(self.account)


class CreditClaim(UUIDModel):
    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    name_credit = models.ForeignKey(
        Credit,
        on_delete=models.PROTECT,
        related_name="claims",
    )
    claimant_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="credit_claims",
    )
    retain_name_credit = models.BooleanField()
    state = models.CharField(max_length=20, choices=State, default=State.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_credit_claims",
    )
    created_account_credit = models.ForeignKey(
        Credit,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_by_claims",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "credit_claim"
        constraints = [
            models.UniqueConstraint(
                fields=["name_credit", "claimant_account"],
                condition=models.Q(state="pending"),
                name="credit_claim_one_pending_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state__in=["pending", "cancelled"],
                        reviewed_by__isnull=True,
                        reviewed_at__isnull=True,
                    )
                    | models.Q(
                        state__in=["approved", "rejected"],
                        reviewed_by__isnull=False,
                        reviewed_at__isnull=False,
                    )
                ),
                name="credit_claim_review_state",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="approved",
                        created_account_credit__isnull=False,
                    )
                    | (
                        ~models.Q(state="approved")
                        & models.Q(created_account_credit__isnull=True)
                    )
                ),
                name="credit_claim_created_credit_state",
            ),
        ]
