from django.core.management.base import BaseCommand, CommandError

from registry.models import Result
from registry.services.result_verification import derive_result_reproduction_status


class Command(BaseCommand):
    help = "Validate the server-derived reproduction status stored on every result"

    def handle(self, *args, **options):
        errors = []
        checked = 0
        for result in Result.objects.order_by("id").iterator():
            checked += 1
            expected = derive_result_reproduction_status(result)
            if result.reproduction_status != expected:
                errors.append(
                    f"result {result.id}: stored {result.reproduction_status!r}; "
                    f"derived {expected!r}"
                )
        if errors:
            rendered = "\n".join(f"- {error}" for error in errors)
            raise CommandError(
                f"Result verification validation failed with {len(errors)} "
                f"error(s):\n{rendered}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Validated server-derived status for {checked} result records."
            )
        )
