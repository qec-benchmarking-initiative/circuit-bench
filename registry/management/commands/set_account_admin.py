from django.core.management.base import BaseCommand, CommandError

from accounts.models import Account, ExternalIdentity


class Command(BaseCommand):
    help = "Grant or revoke Circuit Bench review-admin status"

    def add_arguments(self, parser):
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--account", help="Account UUID")
        selector.add_argument("--github", help="Exact linked GitHub username")
        selector.add_argument("--orcid", help="Exact linked ORCID iD")
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Revoke review-admin status instead of granting it",
        )

    def handle(self, *args, **options):
        account = self._account(options)
        account.is_admin = not options["revoke"]
        account.save(update_fields=["is_admin"])
        action = "Revoked" if options["revoke"] else "Granted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} review-admin status for {account.display_name} "
                f"({account.id})."
            )
        )

    def _account(self, options) -> Account:
        if options["account"]:
            try:
                return Account.objects.get(id=options["account"])
            except (Account.DoesNotExist, ValueError) as error:
                raise CommandError("No account has that UUID.") from error

        provider = "github" if options["github"] else "orcid"
        identifier = options[provider]
        identities = ExternalIdentity.objects.select_related("account").filter(
            provider=provider,
            public_identifier__iexact=identifier,
        )
        if identities.count() != 1:
            raise CommandError(
                f"Expected exactly one linked {provider} identity named {identifier!r}."
            )
        return identities.get().account
