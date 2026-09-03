import json
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
REQUIRED_CONTRACTS = (
    "decoder",
    "tag",
    "noise_model",
    "circuit",
    "machine",
    "evaluator",
    "result",
    "benchmark",
)
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
JSON_TYPES = {
    "array",
    "boolean",
    "integer",
    "null",
    "number",
    "object",
    "string",
}

MODERATED_LIFECYCLE_STATES_0_1 = (
    "pending_review",
    "pending_reapproval",
    "changes_requested",
    "rejected",
    "published",
    "withdrawn",
)
MACHINE_LIFECYCLE_STATES_0_1 = (
    "pending_reapproval",
    "changes_requested",
    "rejected",
    "published",
    "withdrawn",
)
BENCHMARK_ATTEMPT_LIFECYCLE_STATES_0_1 = (
    "pending_review",
    "published",
    "withdrawn",
)
VISIBILITY_VALUES_0_1 = ("public", "private")

# These are the lifecycle states reachable through each frozen 0.1 workflow,
# not every value accepted by the shared database model. In particular, the
# application does not retain contributor-created draft records.
LIFECYCLE_ENUMS_0_1 = {
    ("decoder", "0.1"): {
        "#/properties/state": MODERATED_LIFECYCLE_STATES_0_1,
    },
    ("noise_model", "0.1"): {
        "#/properties/state": MODERATED_LIFECYCLE_STATES_0_1,
    },
    ("circuit", "0.1"): {
        "#/properties/state": MODERATED_LIFECYCLE_STATES_0_1,
    },
    ("machine", "0.1"): {
        "#/properties/state": MACHINE_LIFECYCLE_STATES_0_1,
    },
    ("result", "0.1"): {
        "#/properties/state": MODERATED_LIFECYCLE_STATES_0_1,
    },
    ("benchmark", "0.1"): {
        "#/properties/state": MODERATED_LIFECYCLE_STATES_0_1,
        "#/$defs/attempt/properties/state": (BENCHMARK_ATTEMPT_LIFECYCLE_STATES_0_1),
    },
}


class DuplicateJsonKeyError(ValueError):
    pass


class Command(BaseCommand):
    help = "Validate every checked-in public JSON Schema and definitions pair"

    def add_arguments(self, parser):
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

    def handle(self, *args, **options):
        schema_root = options["schema_root"].resolve()
        definitions_root = options["definitions_root"].resolve()
        errors = validate_contracts(schema_root, definitions_root)
        if errors:
            formatted = "\n".join(f"- {error}" for error in errors)
            raise CommandError(f"Public contract validation failed:\n{formatted}")

        schema_count = len(list(schema_root.glob("*/*.schema.json")))
        self.stdout.write(
            self.style.SUCCESS(
                f"Public contracts valid: {schema_count} JSON Schemas and "
                f"{schema_count} definitions files."
            )
        )


def validate_contracts(schema_root: Path, definitions_root: Path) -> list[str]:
    errors: list[str] = []
    if not schema_root.is_dir():
        return [f"schema root is not a directory: {schema_root}"]
    if not definitions_root.is_dir():
        return [f"definitions root is not a directory: {definitions_root}"]

    for record_type in REQUIRED_CONTRACTS:
        schema_path = schema_root / record_type / "0.1.schema.json"
        definitions_path = definitions_root / record_type / "0.1.md"
        if not schema_path.is_file() or schema_path.is_symlink():
            errors.append(f"missing regular schema file: {schema_path}")
        if not definitions_path.is_file() or definitions_path.is_symlink():
            errors.append(f"missing regular definitions file: {definitions_path}")

    schema_paths = sorted(schema_root.glob("*/*.schema.json"))
    for schema_path in schema_paths:
        relative = schema_path.relative_to(schema_root)
        record_type = relative.parent.as_posix()
        version = relative.name.removesuffix(".schema.json")
        if record_type not in REQUIRED_CONTRACTS:
            errors.append(f"unknown public record type: {record_type}")
            continue
        if not VERSION_PATTERN.fullmatch(version):
            errors.append(f"unsafe schema version filename: {relative}")
            continue
        if schema_path.is_symlink() or not schema_path.is_file():
            errors.append(f"schema is not a regular file: {schema_path}")
            continue

        try:
            document = json.loads(
                schema_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            errors.append(f"invalid JSON in {relative}: {error}")
            continue

        errors.extend(
            _validate_schema_document(document, record_type, version, relative)
        )

        definitions_path = definitions_root / record_type / f"{version}.md"
        if definitions_path.is_symlink() or not definitions_path.is_file():
            errors.append(f"missing regular definitions file: {definitions_path}")
            continue
        try:
            definitions = definitions_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            errors.append(f"unreadable definitions file {definitions_path}: {error}")
            continue
        if not definitions.startswith("# "):
            errors.append(
                "definitions file must start with a level-one title: "
                f"{definitions_path}"
            )
        if version not in definitions:
            errors.append(
                f"definitions file does not name contract version {version}: "
                f"{definitions_path}"
            )

    return errors


def _validate_schema_document(
    document: Any,
    record_type: str,
    version: str,
    relative: Path,
) -> list[str]:
    if not isinstance(document, dict):
        return [f"JSON Schema must be an object: {relative}"]

    errors: list[str] = []
    expected_contract = f"{record_type}/{version}"
    expected_id = f"urn:decoderbench:schema:{record_type}:{version}"
    if document.get("$schema") != JSON_SCHEMA_DIALECT:
        errors.append(f"{relative}: $schema must be {JSON_SCHEMA_DIALECT}")
    if document.get("$id") != expected_id:
        errors.append(f"{relative}: $id must be {expected_id}")
    if document.get("type") != "object":
        errors.append(f"{relative}: top-level type must be object")
    if document.get("additionalProperties") is not False:
        errors.append(f"{relative}: top-level additionalProperties must be false")

    properties = document.get("properties")
    if not isinstance(properties, dict):
        errors.append(f"{relative}: top-level properties must be an object")
    else:
        schema_property = properties.get("schema")
        if (
            not isinstance(schema_property, dict)
            or schema_property.get("const") != expected_contract
        ):
            errors.append(
                f"{relative}: properties.schema.const must be {expected_contract!r}"
            )

    errors.extend(_validate_schema_node(document, document, relative, "#"))
    errors.extend(_validate_lifecycle_enums(document, record_type, version, relative))
    errors.extend(_validate_visibility(document, relative))
    return errors


def _validate_visibility(document: dict[str, Any], relative: Path) -> list[str]:
    properties = document.get("properties")
    visibility = properties.get("visibility") if isinstance(properties, dict) else None
    actual = visibility.get("enum") if isinstance(visibility, dict) else None
    errors = []
    if actual != list(VISIBILITY_VALUES_0_1):
        errors.append(
            f"{relative} #/properties/visibility: visibility enum must be "
            f"{list(VISIBILITY_VALUES_0_1)!r}; found {actual!r}"
        )
    required = document.get("required")
    if not isinstance(required, list) or "visibility" not in required:
        errors.append(f"{relative}: visibility must be a required property")
    return errors


def _validate_lifecycle_enums(
    document: dict[str, Any],
    record_type: str,
    version: str,
    relative: Path,
) -> list[str]:
    expected_by_pointer = LIFECYCLE_ENUMS_0_1.get((record_type, version), {})
    errors = []
    for pointer, expected in expected_by_pointer.items():
        node = _resolve_pointer(document, pointer)
        actual = node.get("enum") if isinstance(node, dict) else None
        expected_values = list(expected)
        if actual != expected_values:
            errors.append(
                f"{relative} {pointer}: lifecycle enum must be "
                f"{expected_values!r}; found {actual!r}"
            )
    return errors


def _validate_schema_node(
    node: Any,
    root: dict[str, Any],
    relative: Path,
    location: str,
) -> list[str]:
    if isinstance(node, bool):
        return []
    if not isinstance(node, dict):
        return [f"{relative} {location}: schema node must be an object or boolean"]

    errors: list[str] = []
    declared_type = node.get("type")
    if declared_type is not None:
        declared_types = (
            [declared_type] if isinstance(declared_type, str) else declared_type
        )
        if (
            not isinstance(declared_types, list)
            or not declared_types
            or any(value not in JSON_TYPES for value in declared_types)
            or len(set(declared_types)) != len(declared_types)
        ):
            errors.append(f"{relative} {location}: invalid type declaration")

    ref = node.get("$ref")
    if ref is not None:
        if not isinstance(ref, str) or not ref.startswith("#/"):
            errors.append(
                f"{relative} {location}: only local JSON Pointer "
                "$ref values are allowed"
            )
        elif _resolve_pointer(root, ref) is None:
            errors.append(f"{relative} {location}: unresolved $ref {ref!r}")

    properties = node.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            errors.append(f"{relative} {location}: properties must be an object")
        else:
            for name, child in properties.items():
                errors.extend(
                    _validate_schema_node(
                        child,
                        root,
                        relative,
                        f"{location}/properties/{name}",
                    )
                )

    definitions = node.get("$defs")
    if definitions is not None:
        if not isinstance(definitions, dict):
            errors.append(f"{relative} {location}: $defs must be an object")
        else:
            for name, child in definitions.items():
                errors.extend(
                    _validate_schema_node(
                        child,
                        root,
                        relative,
                        f"{location}/$defs/{name}",
                    )
                )

    required = node.get("required")
    if required is not None:
        if (
            not isinstance(required, list)
            or any(not isinstance(value, str) for value in required)
            or len(set(required)) != len(required)
        ):
            errors.append(
                f"{relative} {location}: required must contain unique strings"
            )
        elif isinstance(properties, dict):
            missing = sorted(set(required) - set(properties))
            if missing:
                errors.append(
                    f"{relative} {location}: required names missing from properties: "
                    f"{', '.join(missing)}"
                )

    items = node.get("items")
    if items is not None:
        errors.extend(_validate_schema_node(items, root, relative, f"{location}/items"))

    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        alternatives = node.get(keyword)
        if alternatives is None:
            continue
        if not isinstance(alternatives, list) or not alternatives:
            errors.append(f"{relative} {location}: {keyword} must be a non-empty array")
            continue
        for index, child in enumerate(alternatives):
            errors.extend(
                _validate_schema_node(
                    child,
                    root,
                    relative,
                    f"{location}/{keyword}/{index}",
                )
            )

    enum = node.get("enum")
    if enum is not None:
        if not isinstance(enum, list) or not enum:
            errors.append(f"{relative} {location}: enum must be a non-empty array")
        elif len({_canonical_json(value) for value in enum}) != len(enum):
            errors.append(f"{relative} {location}: enum values must be unique")

    return errors


def _resolve_pointer(document: dict[str, Any], ref: str) -> Any | None:
    current: Any = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _reject_duplicate_keys(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise DuplicateJsonKeyError(f"duplicate key {key!r}")
        document[key] = value
    return document
