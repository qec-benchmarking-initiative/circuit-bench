from django.conf import settings
from django.db import models

from .common import UUIDModel, exactly_one_not_null

RECORD_EVENT_SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "machine",
    "result",
    "tag",
    "benchmark_revision",
    "benchmark_attempt",
    "evaluator_release",
)


class RecordHistory(UUIDModel):
    class RecordKind(models.TextChoices):
        DECODER = "decoder", "Decoder version"
        NOISE_MODEL = "noise_model", "Noise model"
        CIRCUIT = "circuit", "Circuit revision"
        MACHINE = "machine", "Machine"
        RESULT = "result", "Result"
        TAG = "tag", "Tag"
        BENCHMARK = "benchmark", "Benchmark revision"
        BENCHMARK_ATTEMPT = "benchmark_attempt", "Benchmark attempt"
        EVALUATOR = "evaluator", "Evaluator release"

    record_kind = models.CharField(max_length=30, choices=RecordKind)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "record_history"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    record_kind__in=[
                        "decoder",
                        "noise_model",
                        "circuit",
                        "machine",
                        "result",
                        "tag",
                        "benchmark",
                        "benchmark_attempt",
                        "evaluator",
                    ]
                ),
                name="record_history_kind_valid",
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_record_kind_display()} history {self.id}"


class RecordEvent(UUIDModel):
    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        EDITED = "edited", "Edited"
        RESUBMITTED = "resubmitted", "Resubmitted"
        REQUESTED_CHANGES = "requested_changes", "Requested changes"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Withdrawn"
        RESTORED = "restored", "Restored"
        REVISION_CREATED = "revision_created", "Revision created"
        PROMOTED_OFFICIAL = "promoted_official", "Promoted official"
        DEPRECATED = "deprecated", "Deprecated"
        RETIRED = "retired", "Retired"
        MERGED = "merged", "Merged"
        ADDED_ALIAS = "added_alias", "Added alias"
        REMOVED_ALIAS = "removed_alias", "Removed alias"
        ADMIN_CREDIT_OVERRIDE = (
            "admin_credit_claim_override",
            "Admin credit claim override",
        )

    class ActorType(models.TextChoices):
        ACCOUNT = "account", "Account"
        SYSTEM = "system", "System"

    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        UPLOADER = "uploader", "Uploader and administrators"
        ADMIN = "admin", "Administrators only"

    history = models.ForeignKey(
        RecordHistory,
        on_delete=models.PROTECT,
        related_name="events",
    )
    sequence = models.PositiveIntegerField()
    actor_type = models.CharField(max_length=10, choices=ActorType)
    actor_account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    actor_system = models.CharField(max_length=100, null=True, blank=True)
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    noise_model = models.ForeignKey(
        "registry.NoiseModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    machine = models.ForeignKey(
        "registry.Machine",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    result = models.ForeignKey(
        "registry.Result",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    tag = models.ForeignKey(
        "registry.Tag",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    benchmark_revision = models.ForeignKey(
        "registry.BenchmarkRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    benchmark_attempt = models.ForeignKey(
        "registry.BenchmarkAttempt",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    evaluator_release = models.ForeignKey(
        "registry.EvaluatorRelease",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="record_events",
    )
    action = models.CharField(max_length=40, choices=Action)
    note = models.TextField()
    details = models.JSONField(default=dict)
    event_schema_version = models.CharField(max_length=20, default="0.1")
    payload_snapshot = models.JSONField(null=True, blank=True)
    caused_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="consequences",
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility,
        default=Visibility.PUBLIC,
    )
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "record_event"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    action__in=[
                        "submitted",
                        "edited",
                        "resubmitted",
                        "requested_changes",
                        "approved",
                        "rejected",
                        "published",
                        "withdrawn",
                        "restored",
                        "revision_created",
                        "promoted_official",
                        "deprecated",
                        "retired",
                        "merged",
                        "added_alias",
                        "removed_alias",
                        "admin_credit_claim_override",
                    ]
                ),
                name="record_event_action_valid",
            ),
            models.CheckConstraint(
                condition=exactly_one_not_null(*RECORD_EVENT_SUBJECT_FIELDS),
                name="record_event_one_subject",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        actor_type="account",
                        actor_account__isnull=False,
                        actor_system__isnull=True,
                    )
                    | models.Q(
                        actor_type="system",
                        actor_account__isnull=True,
                        actor_system__isnull=False,
                    )
                ),
                name="record_event_actor_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(sequence__gte=1),
                name="record_event_sequence_positive",
            ),
            models.UniqueConstraint(
                fields=["history", "sequence"],
                name="record_event_history_sequence_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["history", "occurred_at"],
                name="idx_event_history_time",
            ),
            models.Index(
                fields=["action", "occurred_at"],
                name="idx_event_action_time",
            ),
            models.Index(
                fields=["actor_account"],
                name="idx_event_actor_account",
            ),
        ]

    @property
    def actor_label(self) -> str:
        if self.actor_type == self.ActorType.SYSTEM:
            return "System"
        return self.actor_account.display_name
