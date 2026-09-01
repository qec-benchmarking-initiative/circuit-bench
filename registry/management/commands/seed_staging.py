from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.demo import seed_demo_data
from registry.demo_plotting import seed_plot_demo_data
from registry.demo_submissions import seed_submission_demo_data


class Command(BaseCommand):
    help = "Load the complete idempotent synthetic staging data set"

    def handle(self, *args, **options):
        if not settings.ALLOW_DEMO_SEED:
            raise CommandError("seed_staging requires ALLOW_DEMO_SEED=True")

        seed_demo_data()
        seed_plot_demo_data()
        counts = seed_submission_demo_data()
        rendered = ", ".join(f"{key}={value}" for key, value in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Staging data ready: {rendered}"))
