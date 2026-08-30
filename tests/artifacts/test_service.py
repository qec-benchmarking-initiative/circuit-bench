import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Account
from registry.models import Artifact
from registry.services.artifacts import (
    ArtifactExpectationError,
    ArtifactIntegrityError,
    ArtifactTooLargeError,
    UnsafeObjectKeyError,
    local_artifact_path,
    store_artifact_chunks,
    store_uploaded_artifact,
    verify_artifact,
)


@pytest.fixture
def uploader(db):
    return Account.objects.create_user(display_name="Artifact uploader")


@pytest.mark.django_db
def test_content_addressed_storage_deduplicates_identical_bytes(
    settings, tmp_path, uploader
):
    settings.MEDIA_ROOT = tmp_path / "media"
    content = b"same scientific bytes\n"

    first, first_created = store_uploaded_artifact(
        SimpleUploadedFile("first.dem", content, content_type="text/plain"),
        uploaded_by=uploader,
    )
    second, second_created = store_uploaded_artifact(
        SimpleUploadedFile("renamed.dem", content, content_type="text/plain"),
        uploaded_by=uploader,
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert Artifact.objects.count() == 1
    assert first.sha256 == hashlib.sha256(content).hexdigest()
    assert first.byte_size == len(content)
    assert first.object_key.endswith(first.sha256)
    assert local_artifact_path(first).read_bytes() == content
    assert verify_artifact(first).byte_size == len(content)


@pytest.mark.django_db
def test_expected_digest_and_size_are_strict(settings, tmp_path, uploader):
    settings.MEDIA_ROOT = tmp_path / "media"
    content = b"{}"

    with pytest.raises(ArtifactExpectationError, match="SHA-256 mismatch"):
        store_uploaded_artifact(
            SimpleUploadedFile("claim.json", content),
            uploaded_by=uploader,
            expected_sha256="0" * 64,
            expected_byte_size=2,
        )
    with pytest.raises(ArtifactExpectationError, match="Size mismatch"):
        store_uploaded_artifact(
            SimpleUploadedFile("claim.json", content),
            uploaded_by=uploader,
            expected_sha256=hashlib.sha256(content).hexdigest(),
            expected_byte_size=3,
        )

    assert Artifact.objects.count() == 0


@pytest.mark.django_db
def test_size_limit_is_enforced_while_streaming(settings, tmp_path, uploader):
    settings.MEDIA_ROOT = tmp_path / "media"

    with pytest.raises(ArtifactTooLargeError, match="4-byte upload limit"):
        store_artifact_chunks(
            [b"123", b"45"],
            uploaded_by=uploader,
            media_type="application/octet-stream",
            original_filename="too-large.bin",
            max_bytes=4,
        )

    assert Artifact.objects.count() == 0


@pytest.mark.django_db
def test_corrupted_object_fails_and_is_never_overwritten(settings, tmp_path, uploader):
    settings.MEDIA_ROOT = tmp_path / "media"
    content = b"original immutable bytes"
    artifact, _ = store_uploaded_artifact(
        SimpleUploadedFile("result.json", content), uploaded_by=uploader
    )
    object_path = local_artifact_path(artifact)
    object_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="SHA-256 mismatch"):
        verify_artifact(artifact)
    with pytest.raises(ArtifactIntegrityError, match="SHA-256 mismatch"):
        store_uploaded_artifact(
            SimpleUploadedFile("result.json", content), uploaded_by=uploader
        )

    assert object_path.read_bytes() == b"tampered"


@pytest.mark.django_db
def test_object_key_cannot_escape_media_root(settings, tmp_path, uploader):
    settings.MEDIA_ROOT = tmp_path / "media"
    artifact = Artifact.objects.create(
        sha256=hashlib.sha256(b"").hexdigest(),
        byte_size=0,
        media_type="application/octet-stream",
        original_filename="escape.bin",
        storage_backend="local",
        object_key="../outside",
        uploaded_by=uploader,
    )

    with pytest.raises(UnsafeObjectKeyError, match="escapes MEDIA_ROOT"):
        verify_artifact(artifact)
