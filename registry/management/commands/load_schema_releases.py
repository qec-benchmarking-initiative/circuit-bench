import json
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Account
from registry.models import SchemaRelease
from registry.services.artifacts import ArtifactError, store_file_artifact

VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


class DuplicateJsonKeyError(ValueError):
    pass


class Command(BaseCommand):
    help = "Load paired checked-in schemas and definitions as draft releases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uploader",
            required=True,
            type=uuid.UUID,
            help="Account UUID recorded as uploader of the immutable artifacts",
        )
        parser.add_argument(
            "--schema-root",
            type=Path,
            default=settings.BASE_DIR / "schemas",
        )
        parser.add_argument(
            "--definitions-root",
            type=Path,
            default=settings.BASE_DIR / "definitions",
        )
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:8000/artifacts/schema-releases",
            help="Permanent-URL prefix for releases",
        )
        parser.add_argument(
            "--record-type",
            action="append",
            choices=SchemaRelease.RecordType.values,
            dest="record_types",
            help="Load only this record type; may be repeated",
        )

    def handle(self, *args, **options):
        try:
            uploader = Account.objects.get(id=options["uploader"])
        except Account.DoesNotExist as error:
            raise CommandError(f"Uploader account does not exist: {error}") from error

        schema_root = options["schema_root"].resolve()
        definitions_root = options["definitions_root"].resolve()
        selected_types = set(options["record_types"] or [])
        contracts = self._discover_contracts(
            schema_root, definitions_root, selected_types
        )
        if not contracts:
            selection = ", ".join(sorted(selected_types)) or "any record type"
            raise CommandError(
                f"No complete schema/definition pairs found for {selection}."
            )

        created_count = 0
        unchanged_count = 0
        with transaction.atomic():
            for record_type, version, schema_path, definitions_path in contracts:
                try:
                    schema_artifact, _ = store_file_artifact(
                        schema_path,
                        uploaded_by=uploader,
                        media_type="application/schema+json",
                    )
                    definitions_artifact, _ = store_file_artifact(
                        definitions_path,
                        uploaded_by=uploader,
                        media_type="text/markdown",
                    )
                except ArtifactError as error:
                    raise CommandError(str(error)) from error

                permanent_url = (
                    f"{options['base_url'].rstrip('/')}/{record_type}/{version}/"
                )
                existing = SchemaRelease.objects.filter(
                    record_type=record_type, version=version
                ).first()
                if existing is not None:
                    if (
                        existing.json_schema_artifact_id != schema_artifact.id
                        or existing.definitions_artifact_id != definitions_artifact.id
                        or existing.permanent_url != permanent_url
                    ):
                        raise CommandError(
                            f"{record_type}/{version} already exists with a different "
                            "contract or permanent URL. Bump the version; existing "
                            "release links are not rewritten."
                        )
                    unchanged_count += 1
                    continue

                SchemaRelease.objects.create(
                    record_type=record_type,
                    version=version,
                    json_schema_artifact=schema_artifact,
                    definitions_artifact=definitions_artifact,
                    permanent_url=permanent_url,
                    state=SchemaRelease.State.DRAFT,
                )
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Schema releases ready: created={created_count}, "
                f"unchanged={unchanged_count}."
            )
        )

    def _discover_contracts(
        self,
        schema_root: Path,
        definitions_root: Path,
        selected_types: set[str],
    ) -> list[tuple[str, str, Path, Path]]:
        if not schema_root.is_dir():
            raise CommandError(f"Schema root is not a directory: {schema_root}")
        if not definitions_root.is_dir():
            raise CommandError(
                f"Definitions root is not a directory: {definitions_root}"
            )

        contracts = []
        for schema_path in sorted(schema_root.glob("*/*.schema.json")):
            relative = schema_path.relative_to(schema_root)
            record_type = relative.parent.as_posix()
            version = relative.name.removesuffix(".schema.json")
            if selected_types and record_type not in selected_types:
                continue
            if record_type not in SchemaRelease.RecordType.values:
                raise CommandError(f"Unknown schema record type: {record_type}")
            if not VERSION_PATTERN.fullmatch(version):
                raise CommandError(f"Unsafe schema version filename: {relative.name}")
            if schema_path.is_symlink() or not schema_path.is_file():
                raise CommandError(f"Schema is not a regular file: {schema_path}")

            definitions_path = definitions_root / record_type / f"{version}.md"
            if definitions_path.is_symlink() or not definitions_path.is_file():
                raise CommandError(
                    f"Missing regular definitions file for {record_type}/{version}: "
                    f"{definitions_path}"
                )
            self._validate_json_schema(schema_path)
            contracts.append(
                (record_type, version, schema_path, definitions_path.resolve())
            )
        return contracts

    def _validate_json_schema(self, schema_path: Path) -> None:
        try:
            document = json.loads(
                schema_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise CommandError(f"Invalid JSON Schema {schema_path}: {error}") from error
        if not isinstance(document, dict):
            raise CommandError(f"JSON Schema must be an object: {schema_path}")
        if document.get("$schema") != JSON_SCHEMA_DIALECT:
            raise CommandError(
                f"JSON Schema must declare {JSON_SCHEMA_DIALECT}: {schema_path}"
            )


def _reject_duplicate_keys(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise DuplicateJsonKeyError(f"duplicate key {key!r}")
        document[key] = value
    return document
