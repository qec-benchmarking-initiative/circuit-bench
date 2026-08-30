from django.conf import settings
from django.db import models

from .common import UUIDModel, exactly_one_not_null

MODERATION_SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "machine",
    "result",
    "tag",
    "benchmark_revision",
    "evaluator_release",
)


class ModerationEvent(UUIDModel):
    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REQUESTED_CHANGES = "requested_changes", "Requested changes"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Withdrawn"
        PROMOTED_OFFICIAL = "promoted_official", "Promoted official"
        DEPRECATED = "deprecated", "Deprecated"
        MERGED = "merged", "Merged"
        ADMIN_CREDIT_OVERRIDE = (
            "admin_credit_claim_override",
            "Admin credit claim override",
        )

    actor_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    noise_model = models.ForeignKey(
        "registry.NoiseModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    machine = models.ForeignKey(
        "registry.Machine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    result = models.ForeignKey(
        "registry.Result",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    tag = models.ForeignKey(
        "registry.Tag",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    benchmark_revision = models.ForeignKey(
        "registry.BenchmarkRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    evaluator_release = models.ForeignKey(
        "registry.EvaluatorRelease",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="moderation_events",
    )
    action = models.CharField(max_length=40, choices=Action)
    note = models.TextField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "moderation_event"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    action__in=[
                        "submitted",
                        "requested_changes",
                        "approved",
                        "rejected",
                        "published",
                        "withdrawn",
                        "promoted_official",
                        "deprecated",
                        "merged",
                        "admin_credit_claim_override",
                    ]
                ),
                name="moderation_event_action_valid",
            ),
            models.CheckConstraint(
                condition=exactly_one_not_null(*MODERATION_SUBJECT_FIELDS),
                name="moderation_event_one_subject",
            )
        ]
