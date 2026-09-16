"""Install real provisional releases and examples of an outdated submission."""

from copy import deepcopy
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings
from django.utils.text import slugify

from accounts.models import Account
from registry.models import CircuitRevision, CircuitSlugAlias, DecoderVersion
from registry.schema_contracts import current_version, install_contract
from registry.services.submissions import (
    create_submission,
    submission_payload_for_record,
)


class Command(BaseCommand):
    help = "Create local schema-review examples and noise-parameter circuit names."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This demonstration command is development-only.")
        actor = Account.objects.filter(is_admin=True, is_active=True).first()
        if actor is None:
            raise CommandError("Create a development admin account first.")
        with transaction.atomic():
            for kind, version in [
                ("decoder", "0.2"),
                ("decoder", "0.3"),
                ("decoder", "0.4"),
                ("decoder", "0.5"),
                ("decoder", "0.6"),
                ("decoder", "0.7"),
                ("circuit", "0.2"),
                ("circuit", "0.3"),
                ("circuit", "0.4"),
                ("result", "0.2"),
                ("result", "0.3"),
                ("result", "0.4"),
                ("result", "0.5"),
                ("machine", "0.2"),
                ("machine", "0.3"),
            ]:
                install_contract(kind, version, uploader=actor)
            source = DecoderVersion.objects.filter(state="published").first()
            if source is None:
                raise CommandError("A published decoder is needed for the demo.")
            versions = {
                key: current_version(key)
                for key in (
                    "decoder",
                    "circuit",
                    "result",
                    "machine",
                    "noise_model",
                    "tag",
                    "benchmark",
                    "evaluator",
                )
            }
            for slug, label, version in (
                ("schema-demo-older", "Schema demo — older definitions", "0.2"),
                (
                    "schema-demo-older-private",
                    "Schema demo — older private submission",
                    "0.2",
                ),
                ("schema-demo-current-0-7", "Schema demo — current definitions", "0.7"),
            ):
                if DecoderVersion.objects.filter(slug=slug).exists():
                    continue
                payload = deepcopy(submission_payload_for_record("decoder", source))
                payload.update(
                    slug=slug,
                    name=label,
                    version="0.1",
                    previous_version=None,
                    description=(
                        "Synthetic decoder for testing schema review warnings; "
                        "not a scientific result."
                    ),
                    revision_description="First demonstration submission.",
                    schema_version=version,
                    visibility="private" if "private" in slug else "public",
                )
                # Submit under the earlier policy, without repointing old records.
                with override_settings(
                    CURRENT_SUBMISSION_SCHEMAS={**versions, "decoder": version}
                ):
                    create_submission("decoder", payload, submitter=actor)
                self.stdout.write(f"Created {label} under decoder/{version}")
            count = 0
            for circuit in CircuitRevision.objects.exclude(noise_parameter=None):
                text = format(Decimal(str(circuit.noise_parameter)), "f")
                if ", p=" in circuit.name:
                    continue
                old_slug = circuit.slug
                new_slug = f"{old_slug}-p-{slugify(text.replace('.', '-'))}"
                if (
                    len(new_slug) > 200
                    or CircuitRevision.objects.filter(slug=new_slug).exists()
                ):
                    raise CommandError(f"Cannot safely rename {old_slug}.")
                CircuitSlugAlias.objects.get_or_create(
                    slug=old_slug, defaults={"circuit": circuit}
                )
                circuit.slug = new_slug
                circuit.name = f"{circuit.name}, p={text}"
                circuit.save(update_fields=["slug", "name"])
                count += 1
            self.stdout.write(f"Renamed {count} circuits; old page URLs redirect.")
