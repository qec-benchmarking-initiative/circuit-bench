from django.core.management.base import BaseCommand, CommandError

from registry.models import TagParent
from registry.services.taxonomy import (
    TaxonomyValidationError,
    validate_tag_taxonomy_acyclic,
)


class Command(BaseCommand):
    help = "Validate that the persisted tag-parent graph is acyclic."

    def handle(self, *args, **options):
        try:
            validate_tag_taxonomy_acyclic()
        except TaxonomyValidationError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Validated {TagParent.objects.count()} tag-parent relationships."
            )
        )
