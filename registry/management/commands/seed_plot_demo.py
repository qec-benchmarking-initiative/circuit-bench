from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from registry.demo_plotting import seed_plot_demo_data


class Command(BaseCommand):
    help = "Add a larger synthetic result population for local plot development."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_plot_demo is available only with DEBUG=True")

        counts = seed_plot_demo_data()
        rendered = ", ".join(f"{key}={value}" for key, value in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Plot demo data ready: {rendered}"))
