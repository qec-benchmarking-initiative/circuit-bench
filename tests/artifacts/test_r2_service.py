import hashlib
import io

import pytest
from botocore.exceptions import ClientError
from django.core.management import call_command

from accounts.models import Account
from registry.models import Artifact
from registry.services import artifacts
from registry.services.artifacts import (
    ArtifactError,
    ArtifactIntegrityError,
    open_verified_artifact,
    store_artifact_chunks,
    verify_artifact,
)


class FakeR2Client:
    def __init__(self):
        self.objects = {}

    def upload_fileobj(self, source, bucket, key, ExtraArgs):
        self.objects[(bucket, key)] = {
            "body": source.read(),
            "extra": ExtraArgs,
        }

    def get_object(self, *, Bucket, Key):
        try:
            value = self.objects[(Bucket, Key)]
        except KeyError as error:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey", "Message": "missing"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            ) from error
        return {"Body": io.BytesIO(value["body"])}


@pytest.fixture
def uploader(db):
    return Account.objects.create_user(display_name="R2 uploader")


@pytest.mark.django_db
def test_r2_artifacts_are_content_addressed_verified_and_readable(
    monkeypatch, settings, uploader
):
    fake = FakeR2Client()
    settings.ARTIFACT_STORAGE_BACKEND = "r2"
    settings.R2_BUCKET_NAME = "circuit-bench-test"
    monkeypatch.setattr(artifacts, "_r2_client", lambda: fake)
    content = b"detector error model\n"

    artifact, created = store_artifact_chunks(
        [content],
        uploaded_by=uploader,
        media_type="text/plain",
        original_filename="circuit.dem",
    )

    assert created is True
    assert artifact.storage_backend == Artifact.StorageBackend.R2
    assert artifact.object_key.endswith(artifact.sha256)
    assert verify_artifact(artifact).path is None
    stored_file, verification = open_verified_artifact(artifact)
    try:
        assert stored_file.read() == content
    finally:
        stored_file.close()
    assert verification.byte_size == len(content)
    assert fake.objects[(settings.R2_BUCKET_NAME, artifact.object_key)]["extra"] == {
        "ContentType": "text/plain",
        "Metadata": {
            "sha256": artifact.sha256,
            "byte-size": str(len(content)),
        },
    }


@pytest.mark.django_db
def test_r2_download_streams_only_verified_bytes(
    client, monkeypatch, settings, uploader
):
    fake = FakeR2Client()
    settings.ARTIFACT_STORAGE_BACKEND = "r2"
    settings.R2_BUCKET_NAME = "circuit-bench-test"
    monkeypatch.setattr(artifacts, "_r2_client", lambda: fake)
    content = b'{"hyperparameters":{"window":8}}\n'
    artifact, _created = store_artifact_chunks(
        [content],
        uploaded_by=uploader,
        media_type="application/json",
        original_filename="hyperparameters.json",
    )
    client.force_login(uploader)

    response = client.get(f"/artifacts/{artifact.id}/download/")

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == content
    assert response["ETag"] == f'"{artifact.sha256}"'


@pytest.mark.django_db
def test_r2_artifact_corruption_is_refused(monkeypatch, settings, uploader):
    fake = FakeR2Client()
    settings.ARTIFACT_STORAGE_BACKEND = "r2"
    settings.R2_BUCKET_NAME = "circuit-bench-test"
    monkeypatch.setattr(artifacts, "_r2_client", lambda: fake)
    artifact, _created = store_artifact_chunks(
        [b"immutable"],
        uploaded_by=uploader,
        media_type="application/octet-stream",
        original_filename="immutable.bin",
    )
    fake.objects[(settings.R2_BUCKET_NAME, artifact.object_key)]["body"] = b"tampered"

    with pytest.raises(ArtifactIntegrityError, match="SHA-256 mismatch"):
        verify_artifact(artifact)


@pytest.mark.django_db
def test_r2_existing_corrupt_content_address_is_never_overwritten(
    monkeypatch, settings, uploader
):
    fake = FakeR2Client()
    settings.ARTIFACT_STORAGE_BACKEND = "r2"
    settings.R2_BUCKET_NAME = "circuit-bench-test"
    monkeypatch.setattr(artifacts, "_r2_client", lambda: fake)
    content = b"claimed immutable bytes"
    digest = hashlib.sha256(content).hexdigest()
    object_key = f"artifacts/sha256/{digest[:2]}/{digest}"
    fake.objects[(settings.R2_BUCKET_NAME, object_key)] = {
        "body": b"corrupt pre-existing object",
        "extra": {},
    }

    with pytest.raises(ArtifactIntegrityError, match="SHA-256 mismatch"):
        store_artifact_chunks(
            [content],
            uploaded_by=uploader,
            media_type="application/octet-stream",
            original_filename="immutable.bin",
        )

    assert fake.objects[(settings.R2_BUCKET_NAME, object_key)]["body"] == (
        b"corrupt pre-existing object"
    )


@pytest.mark.django_db
def test_r2_upload_fails_closed_when_configuration_is_missing(settings, uploader):
    settings.ARTIFACT_STORAGE_BACKEND = "r2"
    settings.R2_BUCKET_NAME = ""
    settings.R2_ENDPOINT_URL = ""
    settings.R2_ACCESS_KEY_ID = ""
    settings.R2_SECRET_ACCESS_KEY = ""

    with pytest.raises(ArtifactError, match="configuration is missing"):
        store_artifact_chunks(
            [b"bytes"],
            uploaded_by=uploader,
            media_type="application/octet-stream",
            original_filename="object.bin",
        )

    assert Artifact.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_complete_staging_seed_uses_r2(monkeypatch, settings):
    fake = FakeR2Client()
    settings.ALLOW_DEMO_SEED = True
    settings.ARTIFACT_STORAGE_BACKEND = "r2"
    settings.R2_BUCKET_NAME = "circuit-bench-staging-test"
    settings.PUBLIC_SITE_HOST = "circuit-bench-staging.example"
    monkeypatch.setattr(artifacts, "_r2_client", lambda: fake)

    call_command("seed_staging", verbosity=0)

    stored_artifacts = list(Artifact.objects.all())
    assert len(stored_artifacts) > 20
    assert all(
        artifact.storage_backend == Artifact.StorageBackend.R2
        for artifact in stored_artifacts
    )
    assert len(fake.objects) == len(stored_artifacts)
