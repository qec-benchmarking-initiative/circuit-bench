from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

from .artifacts import SchemaRelease
from .common import UUIDModel


class Tag(UUIDModel):
    class Namespace(models.TextChoices):
        ALGORITHM = "algorithm", "Algorithm"
        EXPERIMENT = "experiment", "Experiment"
        CODE = "code", "Code"

    class Status(models.TextChoices):
        CUSTOM = "custom", "Custom"
        OFFICIAL = "official", "Official"
        DEPRECATED = "deprecated", "Deprecated"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="tags",
    )
    namespace = models.CharField(max_length=20, choices=Namespace)
    slug = models.SlugField(max_length=200)
    label = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status, default=Status.CUSTOM)
    display_color = models.CharField(
        max_length=7,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^#[0-9A-Fa-f]{6}$",
                message="Use a six-digit hexadecimal colour such as #315f7d.",
            )
        ],
        help_text="Optional admin-selected colour for an official tag.",
    )
    canonical_tag = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="aliases",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_tags",
    )
    curated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="curated_tags",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    curated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tag"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(namespace__in=["algorithm", "experiment", "code"]),
                name="tag_namespace_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["custom", "official", "deprecated"]),
                name="tag_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(display_color__isnull=True)
                    | models.Q(display_color__regex=r"^#[0-9A-Fa-f]{6}$")
                ),
                name="tag_display_color_hex",
            ),
            models.UniqueConstraint(
                fields=["namespace", "slug"],
                name="tag_namespace_slug_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(slug__regex=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
                name="tag_slug_format",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(canonical_tag__isnull=True)
                    | ~models.Q(canonical_tag=models.F("id"))
                ),
                name="tag_canonical_not_self",
            ),
        ]
        indexes = [
            models.Index(
                fields=["namespace", "status", "label"],
                name="idx_tag_search",
            )
        ]

    def __str__(self) -> str:
        return self.label


class DecoderVersionAlgorithmTag(models.Model):
    pk = models.CompositePrimaryKey("decoder_version_id", "tag_id")
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        on_delete=models.PROTECT,
        related_name="algorithm_tag_memberships",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.PROTECT,
        related_name="decoder_memberships",
    )

    class Meta:
        db_table = "decoder_version_algorithm_tag"


class CircuitRevisionCodeTag(models.Model):
    pk = models.CompositePrimaryKey("circuit_revision_id", "tag_id")
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="code_tag_memberships",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.PROTECT,
        related_name="circuit_code_memberships",
    )

    class Meta:
        db_table = "circuit_revision_code_tag"


class CircuitRevisionExperimentTag(models.Model):
    pk = models.CompositePrimaryKey("circuit_revision_id", "tag_id")
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="experiment_tag_memberships",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.PROTECT,
        related_name="circuit_experiment_memberships",
    )

    class Meta:
        db_table = "circuit_revision_experiment_tag"
