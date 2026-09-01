from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.demo_submissions import seed_submission_demo_data


class Command(BaseCommand):
    help = "Load deterministic records for submission and approval UI development"

    def handle(self, *args, **options):
        if not (settings.DEBUG or settings.ALLOW_DEMO_SEED):
            raise CommandError(
                "seed_submission_demo requires DEBUG=True or ALLOW_DEMO_SEED=True"
            )
        counts = seed_submission_demo_data()
        summary = ", ".join(f"{name}={count}" for name, count in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Submission demo ready: {summary}"))
