import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from registry.management.commands.validate_contracts import (
    LIFECYCLE_ENUMS_0_1,
    REQUIRED_CONTRACTS,
    _resolve_pointer,
    _validate_schema_document,
)


def test_checked_in_public_contracts_validate(capsys):
    call_command("validate_contracts")

    output = capsys.readouterr().out
    assert "8 JSON Schemas and 8 definitions files" in output


def test_validator_requires_every_record_type(tmp_path: Path):
    schema_root = tmp_path / "schemas"
    definitions_root = tmp_path / "definitions"
    schema_root.mkdir()
    definitions_root.mkdir()

    with pytest.raises(CommandError, match="missing regular schema file"):
        call_command(
            "validate_contracts",
            schema_root=schema_root,
            definitions_root=definitions_root,
        )


def test_validator_rejects_an_unresolved_local_reference(tmp_path: Path):
    schema_root = tmp_path / "schemas"
    definitions_root = tmp_path / "definitions"
    for record_type in REQUIRED_CONTRACTS:
        (schema_root / record_type).mkdir(parents=True)
        (definitions_root / record_type).mkdir(parents=True)
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"urn:decoderbench:schema:{record_type}:0.1",
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "schema": {"const": f"{record_type}/0.1"},
            },
            "required": ["schema"],
        }
        if record_type == "result":
            schema["properties"]["broken"] = {"$ref": "#/$defs/missing"}
        (schema_root / record_type / "0.1.schema.json").write_text(
            json.dumps(schema), encoding="utf-8"
        )
        (definitions_root / record_type / "0.1.md").write_text(
            f"# {record_type} definitions 0.1\n", encoding="utf-8"
        )

    with pytest.raises(CommandError, match="unresolved \\$ref"):
        call_command(
            "validate_contracts",
            schema_root=schema_root,
            definitions_root=definitions_root,
        )


def test_checked_in_lifecycle_enums_match_the_declared_workflows():
    project_root = Path(__file__).resolve().parents[2]

    for (record_type, version), expected_by_pointer in LIFECYCLE_ENUMS_0_1.items():
        schema_path = project_root / "schemas" / record_type / f"{version}.schema.json"
        document = json.loads(schema_path.read_text(encoding="utf-8"))
        for pointer, expected in expected_by_pointer.items():
            assert _resolve_pointer(document, pointer)["enum"] == list(expected)


@pytest.mark.parametrize(
    ("record_type", "pointer", "unsupported_state"),
    (
        ("decoder", "#/properties/state", "draft"),
        ("benchmark", "#/$defs/attempt/properties/state", "changes_requested"),
    ),
)
def test_validator_rejects_lifecycle_enum_drift(
    record_type, pointer, unsupported_state
):
    version = "0.1"
    relative = Path(record_type) / f"{version}.schema.json"
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / relative
    document = json.loads(schema_path.read_text(encoding="utf-8"))
    _resolve_pointer(document, pointer)["enum"].append(unsupported_state)

    errors = _validate_schema_document(document, record_type, version, relative)

    assert any(
        pointer in error and "lifecycle enum must be" in error for error in errors
    )
