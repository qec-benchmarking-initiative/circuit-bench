from django.conf import settings
from django.db import models

from .common import PublishedLifecycleModel, UUIDModel


class CircuitCollection(UUIDModel, PublishedLifecycleModel):
    history = models.ForeignKey(
        "registry.RecordHistory",
        on_delete=models.PROTECT,
        related_name="circuit_collections",
    )
    slug = models.SlugField(max_length=200, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="circuit_collections",
    )
    code_tags = models.ManyToManyField(
        "registry.Tag",
        through="registry.CircuitCollectionCodeTag",
        related_name="code_circuit_collections",
    )
    experiment_tags = models.ManyToManyField(
        "registry.Tag",
        through="registry.CircuitCollectionExperimentTag",
        related_name="experiment_circuit_collections",
    )
    ecz_terms = models.ManyToManyField(
        "registry.EczTerm",
        through="registry.CircuitCollectionEczTerm",
        related_name="circuit_collections",
    )

    class Meta(PublishedLifecycleModel.Meta):
        db_table = "circuit_collection"
        constraints = [*PublishedLifecycleModel.Meta.constraints]
        indexes = [
            models.Index(
                fields=["visibility", "state", "name"],
                name="idx_collection_public_name",
            ),
            models.Index(
                fields=["submitted_by", "-created_at"],
                name="idx_collection_owner_created",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return f"/circuit-collections/{self.slug}/"


class CircuitCollectionMember(UUIDModel):
    collection = models.ForeignKey(
        CircuitCollection,
        on_delete=models.PROTECT,
        related_name="circuit_memberships",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="collection_memberships",
    )
    position = models.PositiveIntegerField()
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_circuits_added",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="collection_circuits_removed",
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "circuit_collection_member"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "circuit_revision"],
                name="collection_circuit_once",
            ),
            models.UniqueConstraint(
                fields=["collection", "position"],
                condition=models.Q(removed_at__isnull=True),
                name="collection_active_circuit_position_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="collection_circuit_position_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(removed_by__isnull=True, removed_at__isnull=True)
                    | models.Q(removed_by__isnull=False, removed_at__isnull=False)
                ),
                name="collection_circuit_removal_valid",
            ),
        ]


class CircuitCollectionChild(UUIDModel):
    collection = models.ForeignKey(
        CircuitCollection,
        on_delete=models.PROTECT,
        related_name="child_memberships",
    )
    child = models.ForeignKey(
        CircuitCollection,
        on_delete=models.PROTECT,
        related_name="parent_memberships",
    )
    position = models.PositiveIntegerField()
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="collection_children_added",
    )
    added_at = models.DateTimeField(auto_now_add=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="collection_children_removed",
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "circuit_collection_child"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "child"],
                name="collection_child_once",
            ),
            models.UniqueConstraint(
                fields=["collection", "position"],
                condition=models.Q(removed_at__isnull=True),
                name="collection_active_child_position_uniq",
            ),
            models.CheckConstraint(
                condition=~models.Q(collection=models.F("child")),
                name="collection_child_not_self",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="collection_child_position_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(removed_by__isnull=True, removed_at__isnull=True)
                    | models.Q(removed_by__isnull=False, removed_at__isnull=False)
                ),
                name="collection_child_removal_valid",
            ),
        ]


class CircuitCollectionCodeTag(UUIDModel):
    collection = models.ForeignKey(
        CircuitCollection,
        on_delete=models.PROTECT,
        related_name="code_tag_memberships",
    )
    tag = models.ForeignKey(
        "registry.Tag",
        on_delete=models.PROTECT,
        related_name="collection_code_memberships",
    )

    class Meta:
        db_table = "circuit_collection_code_tag"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "tag"],
                name="collection_code_tag_uniq",
            )
        ]


class CircuitCollectionExperimentTag(UUIDModel):
    collection = models.ForeignKey(
        CircuitCollection,
        on_delete=models.PROTECT,
        related_name="experiment_tag_memberships",
    )
    tag = models.ForeignKey(
        "registry.Tag",
        on_delete=models.PROTECT,
        related_name="collection_experiment_memberships",
    )

    class Meta:
        db_table = "circuit_collection_experiment_tag"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "tag"],
                name="collection_experiment_tag_uniq",
            )
        ]


class CircuitCollectionEczTerm(UUIDModel):
    collection = models.ForeignKey(
        CircuitCollection,
        on_delete=models.PROTECT,
        related_name="ecz_term_memberships",
    )
    ecz_term = models.ForeignKey(
        "registry.EczTerm",
        on_delete=models.PROTECT,
        related_name="collection_memberships",
    )

    class Meta:
        db_table = "circuit_collection_ecz_term"
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "ecz_term"],
                name="collection_ecz_term_uniq",
            )
        ]


class CircuitBatch(UUIDModel):
    class State(models.TextChoices):
        VALIDATED = "validated", "Validated"
        COMMITTED = "committed", "Committed"
        FAILED = "failed", "Failed"

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="circuit_batches",
    )
    state = models.CharField(max_length=20, choices=State)
    raw_manifest = models.JSONField()
    normalized_manifest = models.JSONField()
    validation_report = models.JSONField(default=dict)
    manifest_sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "circuit_batch"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(state__in=["validated", "committed", "failed"]),
                name="circuit_batch_state_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(manifest_sha256__regex=r"^[0-9a-f]{64}$"),
                name="circuit_batch_digest_valid",
            ),
            models.UniqueConstraint(
                fields=["submitted_by", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="circuit_batch_idempotency_uniq",
            ),
        ]


class CircuitBatchItem(UUIDModel):
    batch = models.ForeignKey(
        CircuitBatch,
        on_delete=models.PROTECT,
        related_name="items",
    )
    position = models.PositiveIntegerField()
    client_id = models.CharField(max_length=200)
    file_name = models.CharField(max_length=500)
    sampling_artifact = models.ForeignKey(
        "registry.Artifact",
        on_delete=models.PROTECT,
        related_name="circuit_batch_items",
    )
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="batch_items",
    )

    class Meta:
        db_table = "circuit_batch_item"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "position"],
                name="circuit_batch_item_position_uniq",
            ),
            models.UniqueConstraint(
                fields=["batch", "client_id"],
                name="circuit_batch_item_client_uniq",
            ),
            models.UniqueConstraint(
                fields=["batch", "file_name"],
                name="circuit_batch_item_file_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(position__gte=1),
                name="circuit_batch_item_position_positive",
            ),
        ]
