from django.conf import settings
from django.db import models


class DailyQuoteSchedule(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    day_offset = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="daily_quote_schedule_updates",
    )

    class Meta:
        db_table = "daily_quote_schedule"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="daily_quote_schedule_singleton",
            )
        ]

    @classmethod
    def current_day_offset(cls) -> int:
        value = cls.objects.filter(pk=1).values_list("day_offset", flat=True).first()
        return value if value is not None else 0

    def __str__(self) -> str:
        return f"Daily quote schedule (offset {self.day_offset:+d})"
