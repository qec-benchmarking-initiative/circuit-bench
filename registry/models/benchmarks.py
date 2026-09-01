from django.conf import settings
from django.db import models

from .artifacts import Artifact, SchemaRelease
from .common import PublishedLifecycleModel, UUIDModel


class BenchmarkRevision(UUIDModel, PublishedLifecycleModel):
    class RecognitionStatus(models.TextChoices):
        COMMUNITY_SUBMITTED = "community_submitted", "Community submitted"
        ADMIN_APPROVED = "admin_approved", "Admin approved"
        OFFICIAL = "official", "Official"
        DEPRECATED = "deprecated", "Deprecated"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="benchmark_revisions",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="benchmark_revisions",
    )
    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    version = models.TextField()
    predecessor = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successor",
    )
    description = models.TextField(null=True, blank=True)
    revision_description = models.TextField()
    recognition_status = models.CharField(max_length=30, choices=RecognitionStatus)
    manifest_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="benchmark_manifests",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_benchmark_revisions",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "benchmark_revision"
        constraints = [
            *PublishedLifecycleModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(
                    recognition_status__in=[
                        "community_submitted",
                        "admin_approved",
                        "official",
                        "deprecated",
                    ]
                ),
                name="benchmark_recognition_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(predecessor__isnull=True)
                    | ~models.Q(predecessor=models.F("id"))
                ),
                name="benchmark_revision_predecessor_not_self",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.version}"


class BenchmarkRevisionItem(models.Model):
    pk = models.CompositePrimaryKey("benchmark_revision_id", "circuit_revision_id")
    benchmark_revision = models.ForeignKey(
        BenchmarkRevision,
        on_delete=models.PROTECT,
        related_name="items",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="benchmark_items",
    )
    position = models.PositiveIntegerField()
    is_required = models.BooleanField(default=True)

    class Meta:
        db_table = "benchmark_revision_item"
        constraints = [
            models.UniqueConstraint(
                fields=["benchmark_revision", "position"],
                name="benchmark_item_revision_position_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="benchmark_item_position_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=["benchmark_revision", "position"],
                name="idx_benchmark_item_position",
            )
        ]


class BenchmarkAttempt(UUIDModel, PublishedLifecycleModel):
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="benchmark_attempts",
    )
    benchmark_revision = models.ForeignKey(
        BenchmarkRevision,
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        on_delete=models.PROTECT,
        related_name="benchmark_attempts",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_benchmark_attempts",
    )
    description = models.TextField(null=True, blank=True)

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "benchmark_attempt"
        constraints = [*PublishedLifecycleModel.Meta.constraints]

    def __str__(self) -> str:
        return str(self.id)


class BenchmarkAttemptResult(models.Model):
    pk = models.CompositePrimaryKey("benchmark_attempt_id", "circuit_revision_id")
    benchmark_attempt = models.ForeignKey(
        BenchmarkAttempt,
        on_delete=models.PROTECT,
        related_name="result_memberships",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="benchmark_attempt_memberships",
    )
    result = models.ForeignKey(
        "registry.Result",
        on_delete=models.PROTECT,
        related_name="benchmark_attempt_memberships",
    )

    class Meta:
        db_table = "benchmark_attempt_result"
        constraints = [
            models.UniqueConstraint(
                fields=["benchmark_attempt", "result"],
                name="benchmark_attempt_result_uniq",
            )
        ]
