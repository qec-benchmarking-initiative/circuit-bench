import uuid

from django.db import models


class LifecycleState(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING_REVIEW = "pending_review", "Pending review"
    PENDING_REAPPROVAL = "pending_reapproval", "Pending reapproval"
    CHANGES_REQUESTED = "changes_requested", "Changes requested"
    REJECTED = "rejected", "Rejected"
    PUBLISHED = "published", "Published"
    WITHDRAWN = "withdrawn", "Withdrawn"


class RecordVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"


REVIEW_QUEUE_STATES = (
    LifecycleState.PENDING_REVIEW,
    LifecycleState.PENDING_REAPPROVAL,
)
EDITABLE_CANDIDATE_STATES = (*REVIEW_QUEUE_STATES, LifecycleState.CHANGES_REQUESTED)
PROFILE_PENDING_STATES = EDITABLE_CANDIDATE_STATES


class PublishedLifecycleModel(models.Model):
    state = models.CharField(
        max_length=20,
        choices=LifecycleState,
        default=LifecycleState.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    visibility = models.CharField(
        max_length=10,
        choices=RecordVisibility,
        default=RecordVisibility.PUBLIC,
    )

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        state__in=[
                            LifecycleState.DRAFT,
                            LifecycleState.PENDING_REVIEW,
                            LifecycleState.PENDING_REAPPROVAL,
                            LifecycleState.CHANGES_REQUESTED,
                            LifecycleState.REJECTED,
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
            ),
            models.CheckConstraint(
                condition=models.Q(visibility__in=RecordVisibility.values),
                name="%(app_label)s_%(class)s_visibility_valid",
            ),
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
