from django.conf import settings
from django.db import models

from .artifacts import Artifact, SchemaRelease
from .common import PublishedLifecycleModel, UUIDModel


class Machine(UUIDModel, PublishedLifecycleModel):
    class MachineClass(models.TextChoices):
        CPU = "cpu", "CPU"
        GPU = "gpu", "GPU"
        FPGA = "fpga", "FPGA"
        ASIC = "asic", "ASIC"
        HYBRID = "hybrid", "Hybrid"

    class EvidenceStatus(models.TextChoices):
        PHYSICAL = "physical", "Physical"
        SIMULATED = "simulated", "Simulated"
        ESTIMATED = "estimated", "Estimated"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="machines",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="machines",
    )
    slug = models.SlugField(max_length=200, unique=True)
    machine_class = models.CharField(
        db_column="class",
        max_length=10,
        choices=MachineClass,
    )
    description = models.TextField()
    status = models.CharField(max_length=20, choices=EvidenceStatus)
    supersedes_machine = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_machines",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "machine"
        constraints = [
            *PublishedLifecycleModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(
                    machine_class__in=["cpu", "gpu", "fpga", "asic", "hybrid"]
                ),
                name="machine_class_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["physical", "simulated", "estimated"]),
                name="machine_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supersedes_machine__isnull=True)
                    | ~models.Q(supersedes_machine=models.F("id"))
                ),
                name="machine_supersedes_not_self",
            ),
        ]

    def __str__(self) -> str:
        return self.slug


class EvaluatorRelease(UUIDModel):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        WITHDRAWN = "withdrawn", "Withdrawn"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="evaluator_releases",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="evaluator_releases",
    )
    version = models.TextField(unique=True)
    source_url = models.URLField(max_length=1000)
    source_revision = models.TextField()
    source_bundle_artifact = models.ForeignKey(
        Artifact,
        on_delete=models.PROTECT,
        related_name="evaluator_source_bundles",
    )
    input_contract_url = models.URLField(max_length=1000)
    summary_contract_url = models.URLField(max_length=1000)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_evaluator_releases",
    )
    state = models.CharField(max_length=20, choices=State, default=State.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "evaluator_release"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state="draft",
                        published_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | models.Q(
                        state="published",
                        published_at__isnull=False,
                        withdrawn_at__isnull=True,
                    )
                    | models.Q(
                        state="withdrawn",
                        published_at__isnull=False,
                        withdrawn_at__isnull=False,
                    )
                ),
                name="evaluator_release_lifecycle_timestamps",
            )
        ]

    def __str__(self) -> str:
        return self.version


class ScoreDefinition(UUIDModel):
    class Direction(models.TextChoices):
        LOWER_IS_BETTER = "lower_is_better", "Lower is better"
        HIGHER_IS_BETTER = "higher_is_better", "Higher is better"
        NOT_RANKED = "not_ranked", "Not ranked"

    class PrimaryValueKind(models.TextChoices):
        ESTIMATE = "estimate", "Estimate"
        LOWER_BOUND = "lower_bound", "Lower bound"
        UPPER_BOUND = "upper_bound", "Upper bound"

    evaluator_release = models.ForeignKey(
        EvaluatorRelease,
        on_delete=models.PROTECT,
        related_name="score_definitions",
    )
    key = models.SlugField(max_length=200)
    version = models.TextField()
    name = models.CharField(max_length=200)
    description = models.TextField()
    definition_url = models.URLField(max_length=1000)
    direction = models.CharField(max_length=20, choices=Direction)
    unit = models.TextField()
    primary_value_kind = models.CharField(max_length=20, choices=PrimaryValueKind)
    required_inputs = models.JSONField()
    parameters = models.JSONField()
    is_provisional = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField()

    class Meta:
        db_table = "score_definition"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    direction__in=[
                        "lower_is_better",
                        "higher_is_better",
                        "not_ranked",
                    ]
                ),
                name="score_definition_direction_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    primary_value_kind__in=[
                        "estimate",
                        "lower_bound",
                        "upper_bound",
                    ]
                ),
                name="score_definition_primary_kind_valid",
            ),
            models.UniqueConstraint(
                fields=["evaluator_release", "key"],
                name="score_definition_release_key_uniq",
            ),
            models.UniqueConstraint(
                fields=["evaluator_release", "display_order"],
                name="score_definition_release_order_uniq",
            ),
            models.UniqueConstraint(
                fields=["id", "evaluator_release"],
                name="score_definition_id_release_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(display_order__gte=1),
                name="score_definition_display_order_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Result(UUIDModel, PublishedLifecycleModel):
    class ReproductionStatus(models.TextChoices):
        INDEPENDENT = "independent_reproduction", "Independent reproduction"
        AUTHOR_VERIFIED = "decoder_author_verified", "Decoder author verified"

    schema_release = models.ForeignKey(
        SchemaRelease,
        on_delete=models.PROTECT,
        related_name="results",
    )
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="results",
    )
    decoder_version = models.ForeignKey(
        "registry.DecoderVersion",
        on_delete=models.PROTECT,
        related_name="results",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="results",
    )
    evaluator_version = models.ForeignKey(
        EvaluatorRelease,
        on_delete=models.PROTECT,
        related_name="results",
    )
    machine = models.ForeignKey(
        Machine,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="results",
    )
    description = models.TextField(null=True, blank=True)
    hyperparameter_values = models.TextField(null=True, blank=True)
    hyperparameter_values_artifact = models.ForeignKey(
        Artifact,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="result_hyperparameter_values",
    )
    shots_total = models.BigIntegerField()
    successful_shots = models.BigIntegerField()
    logical_failure_shots = models.BigIntegerField()
    timeout_shots = models.BigIntegerField()
    decoder_error_shots = models.BigIntegerField()
    failure_probability_shots = models.BigIntegerField()
    latency_shots = models.BigIntegerField()
    preparation_duration_seconds = models.DecimalField(
        max_digits=24,
        decimal_places=9,
        null=True,
        blank=True,
    )
    training_workload_description = models.TextField(null=True, blank=True)
    software_environment = models.TextField(null=True, blank=True)
    t_1000_ns = models.BigIntegerField(null=True, blank=True)
    supersedes_result = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by",
    )
    reproduction_status = models.CharField(max_length=30, choices=ReproductionStatus)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="submitted_results",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "result"
        constraints = [
            *PublishedLifecycleModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(
                    reproduction_status__in=[
                        "independent_reproduction",
                        "decoder_author_verified",
                    ]
                ),
                name="result_reproduction_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(shots_total__gte=1),
                name="result_shots_total_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(successful_shots__gte=0)
                    & models.Q(logical_failure_shots__gte=0)
                    & models.Q(timeout_shots__gte=0)
                    & models.Q(decoder_error_shots__gte=0)
                    & models.Q(failure_probability_shots__gte=0)
                    & models.Q(latency_shots__gte=0)
                ),
                name="result_shot_counts_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    shots_total=(
                        models.F("successful_shots")
                        + models.F("logical_failure_shots")
                        + models.F("timeout_shots")
                        + models.F("decoder_error_shots")
                    )
                ),
                name="result_outcome_counts_sum",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    failure_probability_shots__lte=(
                        models.F("successful_shots")
                        + models.F("logical_failure_shots")
                    )
                ),
                name="result_probability_shots_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    latency_shots__lte=(
                        models.F("successful_shots")
                        + models.F("logical_failure_shots")
                    )
                ),
                name="result_latency_shots_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(preparation_duration_seconds__isnull=True)
                    | models.Q(preparation_duration_seconds__gte=0)
                ),
                name="result_preparation_duration_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(t_1000_ns__isnull=True)
                | models.Q(t_1000_ns__gt=0),
                name="result_t_1000_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supersedes_result__isnull=True)
                    | ~models.Q(supersedes_result=models.F("id"))
                ),
                name="result_supersedes_not_self",
            ),
            models.UniqueConstraint(
                fields=["id", "evaluator_version"],
                name="result_id_evaluator_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["circuit_revision", "state", "-created_at"],
                name="idx_result_circuit_state",
            ),
            models.Index(
                fields=["decoder_version", "state", "-created_at"],
                name="idx_result_decoder_state",
            ),
            models.Index(
                fields=["machine", "state"],
                condition=models.Q(machine__isnull=False),
                name="idx_result_machine",
            ),
            models.Index(
                fields=["supersedes_result"],
                condition=models.Q(supersedes_result__isnull=False),
                name="idx_result_supersedes",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


class ResultScore(models.Model):
    pk = models.CompositePrimaryKey("result_id", "score_definition_id")
    result = models.ForeignKey(
        Result,
        on_delete=models.PROTECT,
        related_name="scores",
    )
    score_definition = models.ForeignKey(
        ScoreDefinition,
        on_delete=models.PROTECT,
        related_name="result_scores",
    )
    evaluator_version = models.ForeignKey(
        EvaluatorRelease,
        on_delete=models.PROTECT,
        related_name="result_scores",
    )
    value = models.DecimalField(max_digits=38, decimal_places=20)
    point_estimate = models.DecimalField(
        max_digits=38,
        decimal_places=20,
        null=True,
        blank=True,
    )
    lower_bound = models.DecimalField(
        max_digits=38,
        decimal_places=20,
        null=True,
        blank=True,
    )
    upper_bound = models.DecimalField(
        max_digits=38,
        decimal_places=20,
        null=True,
        blank=True,
    )
    confidence_level = models.DecimalField(
        max_digits=8,
        decimal_places=7,
        null=True,
        blank=True,
    )
    sample_count = models.BigIntegerField(null=True, blank=True)
    event_count = models.BigIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict)

    class Meta:
        db_table = "result_score"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(confidence_level__isnull=True)
                    | (
                        models.Q(confidence_level__gt=0)
                        & models.Q(confidence_level__lt=1)
                    )
                ),
                name="result_score_confidence_range",
            ),
            models.CheckConstraint(
                condition=models.Q(sample_count__isnull=True)
                | models.Q(sample_count__gte=0),
                name="result_score_sample_count_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(event_count__isnull=True)
                | models.Q(event_count__gte=0),
                name="result_score_event_count_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["score_definition", "value", "result"],
                name="idx_result_score_ranking",
            )
        ]


class ResultAuthorApprovalEvent(UUIDModel):
    class Action(models.TextChoices):
        APPROVE = "approve", "Approve"
        REVOKE = "revoke", "Revoke"

    result = models.ForeignKey(
        Result,
        on_delete=models.PROTECT,
        related_name="author_approval_events",
    )
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="result_author_approval_events",
    )
    action = models.CharField(max_length=10, choices=Action)
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "result_author_approval_event"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action__in=["approve", "revoke"]),
                name="result_author_approval_action_valid",
            )
        ]
