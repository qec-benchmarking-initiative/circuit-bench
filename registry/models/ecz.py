from django.conf import settings
from django.db import models

from .common import UUIDModel


class EczSyncRun(UUIDModel):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        NO_CHANGE = "no_change", "No change"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status)
    source_repository = models.URLField(max_length=500)
    source_commit = models.CharField(max_length=40, null=True, blank=True)
    workflow_run_id = models.BigIntegerField(null=True, blank=True)
    workflow_run_url = models.URLField(max_length=1000, null=True, blank=True)
    archive_sha256 = models.CharField(max_length=64, null=True, blank=True)
    previous_source_commit = models.CharField(max_length=40, null=True, blank=True)
    terms_added = models.PositiveIntegerField(default=0)
    terms_retired = models.PositiveIntegerField(default=0)
    names_changed = models.PositiveIntegerField(default=0)
    parent_edges_added = models.PositiveIntegerField(default=0)
    parent_edges_removed = models.PositiveIntegerField(default=0)
    terms_restored = models.PositiveIntegerField(default=0)
    diagnostics = models.JSONField(default=dict)

    class Meta:
        db_table = "ecz_sync_run"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["applied", "no_change", "rejected", "failed"]
                ),
                name="ecz_sync_run_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_commit__isnull=True)
                    | models.Q(source_commit__regex=r"^[0-9a-f]{40}$")
                ),
                name="ecz_sync_run_commit_sha_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(archive_sha256__isnull=True)
                    | models.Q(archive_sha256__regex=r"^[0-9a-f]{64}$")
                ),
                name="ecz_sync_run_archive_sha_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["-started_at"], name="idx_ecz_sync_started"),
            models.Index(fields=["status", "-finished_at"], name="idx_ecz_sync_status"),
        ]

    def __str__(self) -> str:
        revision = self.source_commit[:12] if self.source_commit else "local source"
        return f"ECZ sync {revision}: {self.get_status_display()}"


class EczTerm(UUIDModel):
    class Status(models.TextChoices):
        CURRENT = "current", "Current"
        RETIRED = "retired", "Retired"

    ecz_code_id = models.CharField(max_length=200, unique=True)
    raw_name = models.TextField()
    display_name = models.CharField(max_length=500)
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.CURRENT,
    )
    first_seen_run = models.ForeignKey(
        EczSyncRun,
        on_delete=models.PROTECT,
        related_name="terms_first_seen",
    )
    last_seen_run = models.ForeignKey(
        EczSyncRun,
        on_delete=models.PROTECT,
        related_name="terms_last_seen",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    parents = models.ManyToManyField(
        "self",
        through="EczParent",
        through_fields=("child", "parent"),
        symmetrical=False,
        related_name="children",
    )

    class Meta:
        db_table = "ecz_term"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ecz_code_id__regex=r"^[a-z0-9][a-z0-9_-]*$"),
                name="ecz_term_code_id_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["current", "retired"]),
                name="ecz_term_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "display_name"], name="idx_ecz_term_search")
        ]

    @property
    def canonical_url(self) -> str:
        return f"https://errorcorrectionzoo.org/c/{self.ecz_code_id}"

    def get_absolute_url(self) -> str:
        return f"/ecz/{self.ecz_code_id}/"

    def __str__(self) -> str:
        return self.display_name


class EczParent(models.Model):
    pk = models.CompositePrimaryKey("child_id", "parent_id")
    child = models.ForeignKey(
        EczTerm,
        on_delete=models.PROTECT,
        related_name="parent_memberships",
    )
    parent = models.ForeignKey(
        EczTerm,
        on_delete=models.PROTECT,
        related_name="child_memberships",
    )

    class Meta:
        db_table = "ecz_parent"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(child=models.F("parent")),
                name="ecz_parent_not_self",
            )
        ]


class CircuitRevisionEczTerm(models.Model):
    pk = models.CompositePrimaryKey("circuit_revision_id", "ecz_term_id")
    circuit_revision = models.ForeignKey(
        "registry.CircuitRevision",
        on_delete=models.PROTECT,
        related_name="ecz_term_memberships",
    )
    ecz_term = models.ForeignKey(
        EczTerm,
        on_delete=models.PROTECT,
        related_name="circuit_memberships",
    )

    class Meta:
        db_table = "circuit_revision_ecz_term"


class TagEczParent(models.Model):
    pk = models.CompositePrimaryKey("tag_id", "ecz_term_id")
    tag = models.ForeignKey(
        "registry.Tag",
        on_delete=models.PROTECT,
        related_name="ecz_parent_memberships",
    )
    ecz_term = models.ForeignKey(
        EczTerm,
        on_delete=models.PROTECT,
        related_name="native_child_memberships",
    )

    class Meta:
        db_table = "tag_ecz_parent"


class TagEczMapping(UUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"

    tag = models.ForeignKey(
        "registry.Tag",
        on_delete=models.PROTECT,
        related_name="ecz_mappings",
    )
    ecz_term = models.ForeignKey(
        EczTerm,
        on_delete=models.PROTECT,
        related_name="native_tag_mappings",
    )
    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.ACTIVE,
    )
    mapped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ecz_mappings_created",
    )
    mapped_at = models.DateTimeField()
    mapping_note = models.TextField()
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ecz_mappings_revoked",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_note = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tag_ecz_mapping"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "revoked"]),
                name="tag_ecz_mapping_status_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status="active",
                        revoked_by__isnull=True,
                        revoked_at__isnull=True,
                        revocation_note__isnull=True,
                    )
                    | models.Q(
                        status="revoked",
                        revoked_by__isnull=False,
                        revoked_at__isnull=False,
                        revocation_note__isnull=False,
                    )
                ),
                name="tag_ecz_mapping_revocation_valid",
            ),
            models.UniqueConstraint(
                fields=["tag"],
                condition=models.Q(status="active"),
                name="tag_one_active_ecz_mapping",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "ecz_term"], name="idx_tag_ecz_mapping_status"
            )
        ]

    def __str__(self) -> str:
        return f"{self.tag} = {self.ecz_term} ({self.get_status_display()})"
