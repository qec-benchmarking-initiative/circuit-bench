from django.conf import settings
from django.db import models

from .common import UUIDModel, exactly_one_not_null


class Artifact(UUIDModel):
    class StorageBackend(models.TextChoices):
        LOCAL = "local", "Local"
        R2 = "r2", "Cloudflare R2"

    sha256 = models.CharField(max_length=64, unique=True)
    byte_size = models.BigIntegerField()
    media_type = models.TextField()
    original_filename = models.TextField()
    storage_backend = models.CharField(max_length=10, choices=StorageBackend)
    object_key = models.TextField()
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_artifacts",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "artifact"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(storage_backend__in=["local", "r2"]),
                name="artifact_storage_backend_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(sha256__regex=r"^[0-9a-f]{64}$"),
                name="artifact_sha256_format",
            ),
            models.CheckConstraint(
                condition=models.Q(byte_size__gte=0),
                name="artifact_byte_size_nonnegative",
            ),
            models.UniqueConstraint(
                fields=["storage_backend", "object_key"],
                name="artifact_backend_object_key_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.original_filename


class SchemaRelease(UUIDModel):
    class RecordType(models.TextChoices):
        DECODER = "decoder", "Decoder"
        TAG = "tag", "Tag"
        NOISE_MODEL = "noise_model", "Noise model"
        CIRCUIT = "circuit", "Circuit"
        MACHINE = "machine", "Machine"
        EVALUATOR = "evaluator", "Evaluator"
        RESULT = "result", "Result"
        BENCHMARK = "benchmark", "Benchmark"

    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        FROZEN = "frozen", "Frozen"
        RETIRED = "retired", "Retired"

    record_type = models.CharField(max_length=20, choices=RecordType)
    version = models.TextField()
    json_schema_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="json_schema_releases",
    )
    definitions_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="definition_releases",
    )
    permanent_url = models.URLField(max_length=500, unique=True)
    state = models.CharField(max_length=10, choices=State, default=State.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    frozen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "schema_release"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    record_type__in=[
                        "decoder",
                        "tag",
                        "noise_model",
                        "circuit",
                        "machine",
                        "evaluator",
                        "result",
                        "benchmark",
                    ]
                ),
                name="schema_release_record_type_valid",
            ),
            models.UniqueConstraint(
                fields=["record_type", "version"],
                name="schema_release_record_type_version_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(state="draft", frozen_at__isnull=True)
                    | models.Q(
                        state__in=["frozen", "retired"],
                        frozen_at__isnull=False,
                    )
                ),
                name="schema_release_frozen_timestamp",
            ),
        ]

    @property
    def public_name(self) -> str:
        return f"{self.record_type}/{self.version}"

    def __str__(self) -> str:
        return self.public_name


SUBJECT_FIELDS = (
    "decoder_version",
    "noise_model",
    "circuit_revision",
    "result",
    "evaluator_release",
    "benchmark_revision",
)


class ArtifactAttachment(UUIDModel):
    artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="attachments",
    )
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artifact_attachments",
    )
    noise_model = models.ForeignKey(
        "registry.NoiseModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artifact_attachments",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artifact_attachments",
    )
    result = models.ForeignKey(
        "registry.Result",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artifact_attachments",
    )
    evaluator_release = models.ForeignKey(
        "registry.EvaluatorRelease",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artifact_attachments",
    )
    benchmark_revision = models.ForeignKey(
        "registry.BenchmarkRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="artifact_attachments",
    )
    role = models.TextField()
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "artifact_attachment"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    role__in=[
                        "source_archive",
                        "documentation",
                        "configuration",
                        "reproduction_bundle",
                        "other",
                    ]
                ),
                name="artifact_attachment_role_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="artifact_attachment_position_positive",
            ),
            models.CheckConstraint(
                condition=exactly_one_not_null(*SUBJECT_FIELDS),
                name="artifact_attachment_one_subject",
            ),
            *[
                models.UniqueConstraint(
                    fields=[subject, "role", "position"],
                    condition=models.Q(**{f"{subject}__isnull": False}),
                    name=f"attachment_{subject}_role_position_uniq",
                )
                for subject in SUBJECT_FIELDS
            ],
            *[
                models.UniqueConstraint(
                    fields=[subject, "artifact"],
                    condition=models.Q(**{f"{subject}__isnull": False}),
                    name=f"attachment_{subject}_artifact_uniq",
                )
                for subject in SUBJECT_FIELDS
            ],
        ]


class ExternalLink(UUIDModel):
    class Kind(models.TextChoices):
        PAPER = "paper", "Paper"
        SOURCE = "source", "Source"
        DOCUMENTATION = "documentation", "Documentation"
        ARTIFACT = "artifact", "File"
        CONFIGURATION = "configuration", "Configuration"
        RAW_TRACE = "raw_trace", "Raw trace"
        OTHER = "other", "Other"

    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="external_links",
    )
    noise_model = models.ForeignKey(
        "registry.NoiseModel",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="external_links",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="external_links",
    )
    result = models.ForeignKey(
        "registry.Result",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="external_links",
    )
    evaluator_release = models.ForeignKey(
        "registry.EvaluatorRelease",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="external_links",
    )
    benchmark_revision = models.ForeignKey(
        "registry.BenchmarkRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="external_links",
    )
    kind = models.CharField(max_length=20, choices=Kind)
    url = models.URLField(max_length=1000)
    label = models.CharField(max_length=200, null=True, blank=True)
    position = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "external_link"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    kind__in=[
                        "paper",
                        "source",
                        "documentation",
                        "artifact",
                        "configuration",
                        "raw_trace",
                        "other",
                    ]
                ),
                name="external_link_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="external_link_position_positive",
            ),
            models.CheckConstraint(
                condition=exactly_one_not_null(*SUBJECT_FIELDS),
                name="external_link_one_subject",
            ),
            *[
                models.UniqueConstraint(
                    fields=[subject, "url"],
                    condition=models.Q(**{f"{subject}__isnull": False}),
                    name=f"external_link_{subject}_url_uniq",
                )
                for subject in SUBJECT_FIELDS
            ],
        ]
