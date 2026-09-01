from django.conf import settings
from django.db import models

from .artifacts import Artifact, SchemaRelease
from .common import PublishedLifecycleModel, UUIDModel


class NoiseModel(UUIDModel, PublishedLifecycleModel):
    class CurationStatus(models.TextChoices):
        COMMUNITY = "community", "Community"
        OFFICIAL = "official", "Official"
        DEPRECATED = "deprecated", "Deprecated"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="noise_models",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="noise_models",
    )
    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    short_description = models.TextField()
    paper_url = models.URLField(max_length=1000)
    randomises_priors = models.BooleanField()
    supersedes_noise_model = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    curation_status = models.CharField(max_length=20, choices=CurationStatus)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_noise_models",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "noise_model"
        constraints = [
            *PublishedLifecycleModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(
                    curation_status__in=["community", "official", "deprecated"]
                ),
                name="noise_model_curation_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supersedes_noise_model__isnull=True)
                    | ~models.Q(supersedes_noise_model=models.F("id"))
                ),
                name="noise_model_supersedes_not_self",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class CircuitRevision(UUIDModel, PublishedLifecycleModel):
    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="circuit_revisions",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="circuit_revisions",
    )
    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    previous_revision = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="next_revision",
    )
    description = models.TextField(null=True, blank=True)
    revision_description = models.TextField()
    noise_model = models.ForeignKey(
        NoiseModel,
        on_delete=models.PROTECT,
        related_name="circuit_revisions",
    )
    is_css = models.BooleanField()
    code_distance_upper_bound = models.PositiveIntegerField(null=True, blank=True)
    circuit_distance_upper_bound = models.PositiveIntegerField(null=True, blank=True)
    rounds = models.PositiveIntegerField(null=True, blank=True)
    num_detectors = models.BigIntegerField()
    num_errors = models.BigIntegerField()
    num_observables = models.BigIntegerField()
    dem_x_detectors_only = models.BooleanField()
    dem_z_detectors_only = models.BooleanField()
    stim_version = models.TextField()
    dem_generation_method = models.TextField(
        default="stim.Circuit.detector_error_model"
    )
    dem_decompose_errors = models.BooleanField()
    dem_flatten_loops = models.BooleanField()
    dem_allow_gauge_detectors = models.BooleanField()
    dem_approximate_disjoint_errors = models.BooleanField()
    dem_ignore_decomposition_failures = models.BooleanField()
    dem_block_decomposition_from_introducing_remnant_edges = models.BooleanField()
    sampling_circuit_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="sampling_circuits",
    )
    detector_error_model_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="detector_error_models",
    )
    manifest_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="circuit_manifests",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_circuit_revisions",
    )
    code_tags = models.ManyToManyField(
        "registry.Tag",
        through="registry.CircuitRevisionCodeTag",
        related_name="code_circuit_revisions",
    )
    experiment_tags = models.ManyToManyField(
        "registry.Tag",
        through="registry.CircuitRevisionExperimentTag",
        related_name="experiment_circuit_revisions",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "circuit_revision"
        constraints = [
            *PublishedLifecycleModel.Meta.constraints,
            models.CheckConstraint(
                condition=(
                    models.Q(previous_revision__isnull=True)
                    | ~models.Q(previous_revision=models.F("id"))
                ),
                name="circuit_revision_previous_not_self",
            ),
            models.CheckConstraint(
                condition=models.Q(code_distance_upper_bound__isnull=True)
                | models.Q(code_distance_upper_bound__gte=1),
                name="circuit_code_distance_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(circuit_distance_upper_bound__isnull=True)
                | models.Q(circuit_distance_upper_bound__gte=1),
                name="circuit_fault_distance_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(rounds__isnull=True) | models.Q(rounds__gte=1),
                name="circuit_rounds_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(num_detectors__gte=0),
                name="circuit_num_detectors_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(num_errors__gte=0),
                name="circuit_num_errors_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(num_observables__gte=1),
                name="circuit_num_observables_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_css=True)
                    | models.Q(
                        dem_x_detectors_only=False,
                        dem_z_detectors_only=False,
                    )
                ),
                name="circuit_detector_only_implies_css",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(num_detectors=0)
                    | models.Q(dem_x_detectors_only=False)
                    | models.Q(dem_z_detectors_only=False)
                ),
                name="circuit_detector_basis_not_both",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    dem_generation_method="stim.Circuit.detector_error_model"
                ),
                name="circuit_dem_generation_method_fixed",
            ),
        ]

    def __str__(self) -> str:
        return self.name
