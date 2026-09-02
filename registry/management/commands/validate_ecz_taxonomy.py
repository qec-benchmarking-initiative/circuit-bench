from django.core.management.base import BaseCommand, CommandError

from registry.models import EczParent, EczTerm
from registry.services.ecz_taxonomy import (
    EczTaxonomyError,
    validate_combined_taxonomy,
)


class Command(BaseCommand):
    help = "Validate imported and combined ECZ taxonomy invariants."

    def handle(self, *args, **options):
        try:
            validate_combined_taxonomy()
        except EczTaxonomyError as error:
            raise CommandError(str(error)) from error
        current = EczTerm.objects.filter(status=EczTerm.Status.CURRENT).count()
        retired = EczTerm.objects.filter(status=EczTerm.Status.RETIRED).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"ECZ taxonomy valid: {current} current terms, {retired} retired, "
                f"{EczParent.objects.count()} imported parent edges."
            )
        )
