import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from registry.management.commands.validate_contracts import REQUIRED_CONTRACTS


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
