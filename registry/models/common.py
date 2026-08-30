import uuid

from django.db import models


class LifecycleState(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_REVIEW = "pending_review", "Pending review"
    PUBLISHED = "published", "Published"
    WITHDRAWN = "withdrawn", "Withdrawn"


class PublishedLifecycleModel(models.Model):
    state = models.CharField(
        max_length=20,
        choices=LifecycleState,
        default=LifecycleState.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state__in=[
                            LifecycleState.DRAFT,
                            LifecycleState.PENDING_REVIEW,
                        ],
                        published_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | models.Q(
                        state=LifecycleState.PUBLISHED,
                        published_at__isnull=False,
                        withdrawn_at__isnull=True,
                    )
                    | models.Q(
                        state=LifecycleState.WITHDRAWN,
                        published_at__isnull=False,
                        withdrawn_at__isnull=False,
                    )
                ),
                name="%(app_label)s_%(class)s_lifecycle_timestamps",
            )
        ]


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


def exactly_one_not_null(*field_names: str) -> models.Q:
    condition = models.Q(pk__isnull=True) & ~models.Q(pk__isnull=True)
    for selected in field_names:
        branch = models.Q(**{f"{selected}__isnull": False})
        for other in field_names:
            if other != selected:
                branch &= models.Q(**{f"{other}__isnull": True})
        condition |= branch
    return condition

