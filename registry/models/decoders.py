from django.conf import settings
from django.db import models

from .artifacts import Artifact, SchemaRelease
from .common import PublishedLifecycleModel, UUIDModel


class DecoderVersion(UUIDModel, PublishedLifecycleModel):
    class Preparation(models.TextChoices):
        REQUIRED = "required", "Required"
        NOT_REQUIRED = "not_required", "Not required"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="decoder_versions",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="decoder_versions",
    )
    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=100)
    predecessor = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="successor",
    )
    description = models.TextField(null=True, blank=True)
    revision_description = models.TextField()
    circuit_skeleton_preparation = models.CharField(
        max_length=20,
        choices=Preparation,
    )
    circuit_priors_preparation = models.CharField(
        max_length=20,
        choices=Preparation,
    )
    provides_failure_probability = models.BooleanField()
    hyperparameter_definitions = models.TextField(null=True, blank=True)
    hyperparameter_schema_artifact = models.ForeignKey(
        Artifact,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decoder_hyperparameter_schemas",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_decoder_versions",
    )
    algorithm_tags = models.ManyToManyField(
        "registry.Tag",
        through="registry.DecoderVersionAlgorithmTag",
        related_name="decoder_versions",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "decoder_version"
        constraints = [
            *PublishedLifecycleModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(
                    circuit_skeleton_preparation__in=["required", "not_required"]
                ),
                name="decoder_skeleton_preparation_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    circuit_priors_preparation__in=["required", "not_required"]
                ),
                name="decoder_priors_preparation_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(predecessor__isnull=True)
                    | ~models.Q(predecessor=models.F("id"))
                ),
                name="decoder_version_predecessor_not_self",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.version}"
