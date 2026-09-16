"""File-authored contracts; frozen releases are the runtime authority.

The mutable current.json selects releases, never rewrites them. Archived JSON
contains the write contract and a content hash of its definitions YAML.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker

from registry.models import SchemaRelease
from registry.services.artifacts import open_verified_artifact, store_artifact_chunks

STALE_MESSAGE = (
    "Sorry, the submission definitions have been updated. "
    "Please refresh the page and try again."
)


class ContractError(ValueError):
    pass


def current_version(kind):
    versions = getattr(settings, "CURRENT_SUBMISSION_SCHEMAS", None)
    if versions is None:
        path = Path(settings.BASE_DIR) / "schemas/current.json"
        versions = json.loads(path.read_text())["current_submission_schemas"]
    return versions[str(kind)]


def release_for(kind, version=None):
    try:
        return SchemaRelease.objects.select_related(
            "json_schema_artifact", "definitions_artifact"
        ).get(
            record_type=str(kind),
            version=version or current_version(kind),
            state__in=["frozen", "retired"],
        )
    except SchemaRelease.DoesNotExist as error:
        raise ContractError(
            f"Schema {kind}/{version or current_version(kind)} is not installed."
        ) from error


def assert_current(kind, version):
    current = current_version(kind)
    if version != current and not (current == "0.1" and version is None):
        raise ContractError(STALE_MESSAGE)


@lru_cache(maxsize=128)
def _read_file(artifact_id, sha256, backend, object_key, byte_size):
    from registry.models import Artifact

    artifact = Artifact(
        id=artifact_id,
        sha256=sha256,
        storage_backend=backend,
        object_key=object_key,
        byte_size=byte_size,
    )
    stream, _ = open_verified_artifact(artifact)
    with stream:
        return stream.read()


def artifact_bytes(artifact):
    return _read_file(
        artifact.id,
        artifact.sha256,
        artifact.storage_backend,
        artifact.object_key,
        artifact.byte_size,
    )


def contract_for(release):
    schema = json.loads(artifact_bytes(release.json_schema_artifact))
    reference = schema.get("x-definitions")
    if reference and reference["sha256"] != release.definitions_artifact.sha256:
        raise ContractError("The schema and archived definitions do not match.")
    return schema


def write_schema(kind, release=None):
    from registry.submission_policy import SubmissionKind
    from registry.submission_specs import SUBMISSION_SCHEMAS

    release = release or release_for(kind)
    contract = contract_for(release)
    if "x-submission-schema" in contract:
        return contract["x-submission-schema"]
    # Historical 0.1 demo releases predate archived write contracts. Do not
    # invent a modern contract or claim their placeholder prose was richer.
    if release.version == "0.1":
        return SUBMISSION_SCHEMAS[SubmissionKind(kind)]
    raise ContractError("This release has no archived submission contract.")


def validate_payload(kind, payload, release=None):
    validator = Draft202012Validator(
        write_schema(kind, release), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(payload), key=lambda e: str(list(e.path)))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path)
        raise ContractError(f"{location + ': ' if location else ''}{error.message}")


def definition_document(release):
    contract = contract_for(release)
    if not contract.get("x-definitions"):
        return None
    return yaml.safe_load(artifact_bytes(release.definitions_artifact))


def field_guidance(kind, field, *, release=None):
    from pages.content import render_markdown

    release = release or release_for(kind)
    schema = contract_for(release)
    key = schema.get("x-form-definitions", {}).get(field)
    if not key:
        return None
    document = definition_document(release)
    entry = document["definitions"][key]
    return {
        **entry,
        "key": key,
        "version": document["version"],
        "kind": str(kind),
        "schema_version": release.version,
        "expanded_html": render_markdown(entry["expanded"])
        if entry.get("expanded")
        else "",
        "url": f"/definitions/{kind}/{document['version']}/#{key}",
    }


def schema_status(record):
    release = getattr(record, "schema_release", None)
    if release is None:
        return None
    current = current_version(release.record_type)
    return {
        "submitted": release.public_name,
        "current": f"{release.record_type}/{current}",
        "outdated": release.version != current,
        "url": f"/artifacts/schema-releases/{release.record_type}/{release.version}/",
    }


def install_contract(kind, version, *, uploader):
    """Archive a checked-in contract atomically without rewriting old releases."""
    from django.db import transaction

    root = Path(settings.BASE_DIR)
    schema_path = root / "schemas" / kind / f"{version}.schema.json"
    source = schema_path.read_bytes()
    schema = json.loads(source)
    Draft202012Validator.check_schema(schema)
    reference = schema["x-definitions"]
    path = (schema_path.parent / reference["path"]).resolve()
    if not path.is_relative_to((root / "definitions").resolve()):
        raise ContractError("Definition path must be inside definitions/.")
    definitions = path.read_bytes()
    if hashlib.sha256(definitions).hexdigest() != reference["sha256"]:
        raise ContractError("Definition hash mismatch; publish a matching schema.")
    document = yaml.safe_load(definitions)
    if not isinstance(document.get("version"), str):
        raise ContractError("The definition version must be a string.")
    for key, entry in document["definitions"].items():
        if not isinstance(entry.get("is_guidance"), bool) or not isinstance(
            entry.get("summary"), str
        ):
            raise ContractError(f"Invalid definition metadata for {key}.")
        if entry.get("expanded") is not None and not isinstance(entry["expanded"], str):
            raise ContractError(f"Invalid expanded definition for {key}.")
    for key in schema.get("x-form-definitions", {}).values():
        if key not in document["definitions"]:
            raise ContractError(f"Missing definition: {key}")
    for old in SchemaRelease.objects.filter(record_type=kind).select_related(
        "json_schema_artifact", "definitions_artifact"
    ):
        prior = contract_for(old).get("x-definitions")
        if (
            prior
            and prior["version"] == document["version"]
            and prior["sha256"] != reference["sha256"]
        ):
            raise ContractError(
                "This definitions version is already frozen with different contents."
            )
    Draft202012Validator.check_schema(schema["x-submission-schema"])
    with transaction.atomic():
        artifacts = []
        for data, filename, media_type in (
            (source, schema_path.name, "application/schema+json"),
            (definitions, path.name, "application/yaml"),
        ):
            artifact, _ = store_artifact_chunks(
                [data],
                uploaded_by=uploader,
                original_filename=filename,
                media_type=media_type,
            )
            artifacts.append(artifact)
        existing = SchemaRelease.objects.filter(
            record_type=kind, version=version
        ).first()
        if existing:
            if (
                existing.json_schema_artifact_id,
                existing.definitions_artifact_id,
            ) != tuple(a.id for a in artifacts):
                raise ContractError(
                    f"{kind}/{version} already exists. Create a new version."
                )
            return existing
        return SchemaRelease.objects.create(
            record_type=kind,
            version=version,
            json_schema_artifact=artifacts[0],
            definitions_artifact=artifacts[1],
            state="frozen",
            frozen_at=timezone.now(),
            permanent_url=f"https://circuitbench.org/artifacts/schema-releases/{kind}/{version}/",
        )


def definition_markdown(document):
    title = document["record_type"].replace("_", " ").title()
    pieces = [
        f"# {title} definitions {document['version']}",
        document.get("status", ""),
    ]
    for key, entry in document["definitions"].items():
        # Human headings deliberately match stable, schema-referenced anchors.
        pieces += [f"## {key.replace('-', ' ')}", entry["summary"]]
        if entry.get("expanded"):
            pieces.append(entry["expanded"])
    return "\n\n".join(pieces)


def archived_definition_source(kind, version):
    for release in SchemaRelease.objects.filter(
        record_type=kind, state__in=["frozen", "retired"]
    ).select_related("json_schema_artifact", "definitions_artifact"):
        document = definition_document(release)
        if document and document["version"] == version:
            return definition_markdown(document)
        if not document and release.version == version:
            return artifact_bytes(release.definitions_artifact).decode()
    return None
