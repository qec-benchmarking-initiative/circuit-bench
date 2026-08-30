import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Account
from registry.models import Artifact, SchemaRelease
from registry.services.artifacts import verify_artifact


@pytest.fixture
def uploader(db):
    return Account.objects.create_user(display_name="Contract curator")


def write_contract(tmp_path, *, title="Decoder record"):
    schema_root = tmp_path / "schemas"
    definitions_root = tmp_path / "definitions"
    schema_path = schema_root / "decoder" / "0.1.schema.json"
    definitions_path = definitions_root / "decoder" / "0.1.md"
    schema_path.parent.mkdir(parents=True)
    definitions_path.parent.mkdir(parents=True)
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": title,
                "type": "object",
            }
        ),
        encoding="utf-8",
    )
    definitions_path.write_text("# Decoder definitions 0.1\n", encoding="utf-8")
    return schema_root, definitions_root, schema_path


@pytest.mark.django_db
def test_command_loads_paired_contract_as_idempotent_draft(
    settings, tmp_path, uploader
):
    settings.MEDIA_ROOT = tmp_path / "media"
    schema_root, definitions_root, _ = write_contract(tmp_path)
    output = io.StringIO()
    options = {
        "uploader": str(uploader.id),
        "schema_root": schema_root,
        "definitions_root": definitions_root,
        "base_url": "https://local.test/schemas",
        "stdout": output,
    }

    call_command("load_schema_releases", **options)
    call_command("load_schema_releases", **options)

    release = SchemaRelease.objects.get(record_type="decoder", version="0.1")
    assert release.state == "draft"
    assert release.frozen_at is None
    assert release.permanent_url == "https://local.test/schemas/decoder/0.1/"
    assert Artifact.objects.count() == 2
    verify_artifact(release.json_schema_artifact)
    verify_artifact(release.definitions_artifact)
    assert "created=1, unchanged=0" in output.getvalue()
    assert "created=0, unchanged=1" in output.getvalue()


@pytest.mark.django_db
def test_command_refuses_to_repoint_an_existing_release(
    settings, tmp_path, uploader
):
    settings.MEDIA_ROOT = tmp_path / "media"
    schema_root, definitions_root, schema_path = write_contract(tmp_path)
    options = {
        "uploader": str(uploader.id),
        "schema_root": schema_root,
        "definitions_root": definitions_root,
        "base_url": "https://local.test/schemas",
    }
    call_command("load_schema_releases", **options)
    original_schema_id = SchemaRelease.objects.get().json_schema_artifact_id
    original_artifact_count = Artifact.objects.count()
    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "Changed meaning under the same version",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="Bump the version"):
        call_command("load_schema_releases", **options)

    release = SchemaRelease.objects.get()
    assert release.json_schema_artifact_id == original_schema_id
    assert Artifact.objects.count() == original_artifact_count


@pytest.mark.django_db
def test_command_rejects_duplicate_json_keys(settings, tmp_path, uploader):
    settings.MEDIA_ROOT = tmp_path / "media"
    schema_root, definitions_root, schema_path = write_contract(tmp_path)
    schema_path.write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"type":"object","type":"array"}',
        encoding="utf-8",
    )

    with pytest.raises(CommandError, match="duplicate key 'type'"):
        call_command(
            "load_schema_releases",
            uploader=str(uploader.id),
            schema_root=schema_root,
            definitions_root=definitions_root,
        )

    assert SchemaRelease.objects.count() == 0
    assert Artifact.objects.count() == 0
