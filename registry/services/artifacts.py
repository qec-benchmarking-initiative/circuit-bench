from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from django.conf import settings
from django.db import IntegrityError, transaction

from accounts.models import Account
from registry.models import Artifact

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_MAX_UPLOAD_BYTES = 1024 * 1024
READ_CHUNK_SIZE = 64 * 1024


class ArtifactError(Exception):
    """Base class for failures which must not produce an artifact row."""


class ArtifactTooLargeError(ArtifactError):
    pass


class ArtifactExpectationError(ArtifactError):
    pass


class ArtifactIntegrityError(ArtifactError):
    pass


class UnsafeObjectKeyError(ArtifactIntegrityError):
    pass


@dataclass(frozen=True)
class ArtifactVerification:
    path: Path
    sha256: str
    byte_size: int


def local_artifact_path(artifact: Artifact) -> Path:
    """Resolve an artifact object key without allowing it to escape MEDIA_ROOT."""
    if artifact.storage_backend != Artifact.StorageBackend.LOCAL:
        raise ArtifactIntegrityError(
            f"Artifact {artifact.id} is not stored by the local backend."
        )

    root = Path(settings.MEDIA_ROOT).resolve()
    object_key = Path(artifact.object_key)
    if object_key.is_absolute():
        raise UnsafeObjectKeyError("Absolute artifact object keys are forbidden.")

    candidate = root / object_key
    resolved = candidate.resolve(strict=False)
    if resolved == root or root not in resolved.parents:
        raise UnsafeObjectKeyError("Artifact object key escapes MEDIA_ROOT.")
    if candidate.is_symlink():
        raise UnsafeObjectKeyError("Artifact object keys may not be symbolic links.")
    return resolved


def verify_artifact(artifact: Artifact) -> ArtifactVerification:
    """Recompute local bytes and require exact agreement with stored metadata."""
    if not SHA256_PATTERN.fullmatch(artifact.sha256):
        raise ArtifactIntegrityError("Stored SHA-256 metadata is malformed.")
    if artifact.byte_size < 0:
        raise ArtifactIntegrityError("Stored byte-size metadata is negative.")

    path = local_artifact_path(artifact)
    if not path.is_file():
        raise ArtifactIntegrityError(
            f"Artifact object is missing: {artifact.object_key}"
        )

    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as stored_file:
        for chunk in iter(lambda: stored_file.read(READ_CHUNK_SIZE), b""):
            digest.update(chunk)
            byte_size += len(chunk)

    actual_sha256 = digest.hexdigest()
    if actual_sha256 != artifact.sha256:
        raise ArtifactIntegrityError(
            f"SHA-256 mismatch: expected {artifact.sha256}, got {actual_sha256}."
        )
    if byte_size != artifact.byte_size:
        raise ArtifactIntegrityError(
            f"Size mismatch: expected {artifact.byte_size}, got {byte_size}."
        )
    return ArtifactVerification(path, actual_sha256, byte_size)


def store_uploaded_artifact(
    uploaded_file,
    *,
    uploaded_by: Account,
    media_type: str | None = None,
    original_filename: str | None = None,
    expected_sha256: str | None = None,
    expected_byte_size: int | None = None,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> tuple[Artifact, bool]:
    chunks = uploaded_file.chunks()
    return store_artifact_chunks(
        chunks,
        uploaded_by=uploaded_by,
        media_type=media_type or getattr(uploaded_file, "content_type", None),
        original_filename=original_filename or getattr(uploaded_file, "name", None),
        expected_sha256=expected_sha256,
        expected_byte_size=expected_byte_size,
        max_bytes=max_bytes,
    )


def store_file_artifact(
    source_path: str | Path,
    *,
    uploaded_by: Account,
    media_type: str,
    original_filename: str | None = None,
    expected_sha256: str | None = None,
    expected_byte_size: int | None = None,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> tuple[Artifact, bool]:
    source = Path(source_path)
    if source.is_symlink() or not source.is_file():
        raise ArtifactError(f"Artifact source is not a regular file: {source}")

    with source.open("rb") as source_file:
        return store_artifact_chunks(
            _file_chunks(source_file),
            uploaded_by=uploaded_by,
            media_type=media_type,
            original_filename=original_filename or source.name,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
            max_bytes=max_bytes,
        )


def store_artifact_chunks(
    chunks: Iterable[bytes],
    *,
    uploaded_by: Account,
    media_type: str | None,
    original_filename: str | None,
    expected_sha256: str | None = None,
    expected_byte_size: int | None = None,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> tuple[Artifact, bool]:
    """Write one immutable local object, returning an existing row on duplicate."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if expected_sha256 is not None and not SHA256_PATTERN.fullmatch(expected_sha256):
        raise ArtifactExpectationError(
            "Expected SHA-256 must be 64 lowercase hexadecimal characters."
        )
    if expected_byte_size is not None and expected_byte_size < 0:
        raise ArtifactExpectationError("Expected byte size must be non-negative.")

    filename = _safe_filename(original_filename)
    content_type = _safe_media_type(media_type)
    incoming_dir = Path(settings.MEDIA_ROOT).resolve() / ".incoming"
    incoming_dir.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        digest = hashlib.sha256()
        byte_size = 0
        with tempfile.NamedTemporaryFile(dir=incoming_dir, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            for chunk in chunks:
                if not isinstance(chunk, bytes):
                    chunk = bytes(chunk)
                byte_size += len(chunk)
                if byte_size > max_bytes:
                    raise ArtifactTooLargeError(
                        f"Artifact exceeds the {max_bytes}-byte upload limit."
                    )
                digest.update(chunk)
                temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())

        sha256 = digest.hexdigest()
        _check_expectations(
            sha256,
            byte_size,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
        )

        existing = Artifact.objects.filter(sha256=sha256).first()
        if existing is not None:
            verify_artifact(existing)
            return existing, False

        object_key = f"artifacts/sha256/{sha256[:2]}/{sha256}"
        destination = Path(settings.MEDIA_ROOT).resolve() / object_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            _verify_path(destination, sha256, byte_size)

        try:
            with transaction.atomic():
                artifact = Artifact.objects.create(
                    sha256=sha256,
                    byte_size=byte_size,
                    media_type=content_type,
                    original_filename=filename,
                    storage_backend=Artifact.StorageBackend.LOCAL,
                    object_key=object_key,
                    uploaded_by=uploaded_by,
                )
        except IntegrityError:
            artifact = Artifact.objects.get(sha256=sha256)
            verify_artifact(artifact)
            return artifact, False

        verify_artifact(artifact)
        return artifact, True
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _file_chunks(source_file: BinaryIO) -> Iterable[bytes]:
    while chunk := source_file.read(READ_CHUNK_SIZE):
        yield chunk


def _check_expectations(
    sha256: str,
    byte_size: int,
    *,
    expected_sha256: str | None,
    expected_byte_size: int | None,
) -> None:
    if expected_sha256 is not None and sha256 != expected_sha256:
        raise ArtifactExpectationError(
            f"SHA-256 mismatch: expected {expected_sha256}, got {sha256}."
        )
    if expected_byte_size is not None and byte_size != expected_byte_size:
        raise ArtifactExpectationError(
            f"Size mismatch: expected {expected_byte_size}, got {byte_size}."
        )


def _verify_path(path: Path, expected_sha256: str, expected_size: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise ArtifactIntegrityError("Content-addressed destination is not a file.")
    digest = hashlib.sha256()
    byte_size = 0
    with path.open("rb") as existing_file:
        for chunk in iter(lambda: existing_file.read(READ_CHUNK_SIZE), b""):
            digest.update(chunk)
            byte_size += len(chunk)
    if digest.hexdigest() != expected_sha256 or byte_size != expected_size:
        raise ArtifactIntegrityError(
            "Existing content-addressed object does not match its object key."
        )


def _safe_filename(filename: str | None) -> str:
    candidate = (filename or "artifact.bin").replace("\\", "/").split("/")[-1]
    candidate = "".join(character for character in candidate if ord(character) >= 32)
    candidate = candidate.strip()
    if not candidate or candidate in {".", ".."}:
        return "artifact.bin"
    return candidate[:255]


def _safe_media_type(media_type: str | None) -> str:
    candidate = (media_type or "application/octet-stream").strip().lower()
    if not candidate or len(candidate) > 255 or "\n" in candidate or "\r" in candidate:
        return "application/octet-stream"
    return candidate
