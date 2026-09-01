from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from registry.demo import seed_demo_data


class Command(BaseCommand):
    help = "Load deterministic, synthetic development records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Flush local data before loading the demonstration records",
        )

    def handle(self, *args, **options):
        if not (settings.DEBUG or settings.ALLOW_DEMO_SEED):
            raise CommandError("seed_demo requires DEBUG=True or ALLOW_DEMO_SEED=True")
        if options["reset"]:
            call_command("flush", interactive=False, verbosity=0)

        counts = seed_demo_data()
        summary = ", ".join(f"{name}={count}" for name, count in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Demo data ready: {summary}"))
