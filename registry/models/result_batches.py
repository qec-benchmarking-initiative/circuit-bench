from django.conf import settings
from django.db import models

from .common import UUIDModel


class ResultBatch(UUIDModel):
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    normalized_manifest = models.JSONField()
    manifest_sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    @property
    def state(self):
        return "committed" if self.committed_at else "validated"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submitted_by", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="result_batch_idempotency_unique",
            )
        ]


class ResultBatchItem(UUIDModel):
    batch = models.ForeignKey(
        ResultBatch, on_delete=models.PROTECT, related_name="items"
    )
    file_name = models.CharField(max_length=255)
    position = models.PositiveIntegerField()
    payload = models.JSONField()
    result = models.ForeignKey(
        "registry.Result",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="batch_items",
    )

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "file_name"], name="result_batch_filename_unique"
            ),
            models.UniqueConstraint(
                fields=["batch", "position"], name="result_batch_position_unique"
            ),
        ]
