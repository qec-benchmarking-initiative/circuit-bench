from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account
from registry.schema_contracts import ContractError, install_contract


class Command(BaseCommand):
    help = "Freeze file-authored schema/YAML pairs; existing releases cannot change."

    def add_arguments(self, parser):
        parser.add_argument(
            "contracts", nargs="+", help="For example decoder/0.2 decoder/0.3"
        )
        parser.add_argument("--uploader", required=True)

    def handle(self, *args, **options):
        uploader = Account.objects.get(pk=options["uploader"])
        for contract in options["contracts"]:
            kind, version = contract.split("/", 1)
            if not version.replace(".", "").isdigit() or kind not in {
                "decoder",
                "circuit",
                "machine",
                "result",
            }:
                raise CommandError("Invalid contract identifier")
            try:
                release = install_contract(kind, version, uploader=uploader)
            except (ContractError, ValueError) as error:
                raise CommandError(str(error)) from error
            self.stdout.write(f"Frozen {release.public_name}")
