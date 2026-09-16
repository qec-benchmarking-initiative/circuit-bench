"""Bounded, atomic result batches using the single-result validation service."""

import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone
from jsonschema import Draft202012Validator

from accounts.models import Account
from registry.models import ResultBatch, ResultBatchItem
from registry.schema_contracts import ContractError, assert_current, current_version
from registry.services.circuit_batches import (
    CircuitBatchError,
    _object_without_duplicate_keys,
)
from registry.services.submissions import (
    SubmissionError,
    create_submission,
    validate_submission_payload,
)
from registry.submission_specs import SUBMISSION_SCHEMAS, get_submission_schema

ResultBatchError = CircuitBatchError
MAX_JSON_BYTES = 1024 * 1024
MAX_RESULTS = 200


def batch_schema():
    partial = (
        SUBMISSION_SCHEMAS["result"]
        if current_version("result") == "0.1"
        else get_submission_schema("result")
    ).copy()
    partial.pop("required", None)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:circuit-bench:result-batch:0.1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "schema_version", "results"],
        "properties": {
            "schema": {"const": "result-batch/0.1"},
            "schema_version": {"const": current_version("result")},
            "defaults": partial,
            "results": {
                "type": "object",
                "minProperties": 1,
                "maxProperties": MAX_RESULTS,
                "propertyNames": {"pattern": r"^[^/\\]+\.json$", "maxLength": 255},
                "additionalProperties": partial,
            },
        },
    }


def parse_json(raw):
    try:
        if isinstance(raw, bytes):
            if len(raw) > MAX_JSON_BYTES:
                raise ResultBatchError("JSON files must be at most 1 MiB.")
            raw = raw.decode("utf-8")
        if len(raw.encode()) > MAX_JSON_BYTES:
            raise ResultBatchError("JSON must be at most 1 MiB.")
        value = json.loads(
            raw,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"Invalid number: {value}")
            ),
        )
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ResultBatchError(f"Invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ResultBatchError("Each JSON document must be an object.")
    return value


def _canonical_payload(payload, actor, name):
    if payload.get("supersedes_result"):
        raise ResultBatchError(
            f"{name}: use the single-result revision form to replace a result."
        )
    try:
        return validate_submission_payload("result", payload, actor=actor)
    except SubmissionError as error:
        detail = str(error)
        if getattr(error, "form", None) is not None:
            detail += " " + "; ".join(
                f"{key}: {', '.join(values)}"
                for key, values in error.form.errors.items()
            )
        raise ResultBatchError(f"{name}: {detail}") from error


def validate_batch(*, actor, manifest, file_bytes, idempotency_key=None):
    if not actor.is_active:
        raise PermissionDenied
    try:
        assert_current("result", manifest.get("schema_version"))
    except ContractError as error:
        raise ResultBatchError(str(error)) from error
    errors = list(Draft202012Validator(batch_schema()).iter_errors(manifest))
    if errors:
        error = errors[0]
        raise ResultBatchError(
            f"{'.'.join(map(str, error.path)) or 'manifest'}: {error.message}"
        )
    names = set(manifest["results"])
    if names != set(file_bytes):
        missing, extra = (
            sorted(names - set(file_bytes)),
            sorted(set(file_bytes) - names),
        )
        raise ResultBatchError(
            f"Files do not match manifest. Missing: {', '.join(missing) or 'none'}; "
            f"unexpected: {', '.join(extra) or 'none'}."
        )
    normalized = {
        "schema": "result-batch/0.1",
        "schema_version": manifest["schema_version"],
        "results": {},
    }
    for name in sorted(names):
        payload = {
            **manifest.get("defaults", {}),
            **parse_json(file_bytes[name]),
            **manifest["results"][name],
        }
        if (
            "schema_version" in payload
            and payload["schema_version"] != manifest["schema_version"]
        ):
            raise ResultBatchError(f"{name}: schema_version differs from the manifest.")
        payload["schema_version"] = manifest["schema_version"]
        normalized["results"][name] = _canonical_payload(payload, actor, name)
    digest = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    key = (idempotency_key or "").strip() or None
    if key and len(key) > 200:
        raise ResultBatchError("Idempotency key must be at most 200 characters.")
    with transaction.atomic():
        # Serialize this contributor's idempotency checks, including retries.
        Account.objects.select_for_update().get(pk=actor.pk)
        if key:
            existing = ResultBatch.objects.filter(
                submitted_by=actor, idempotency_key=key
            ).first()
            if existing:
                if existing.manifest_sha256 != digest:
                    raise ResultBatchError(
                        "That idempotency key was already used for different results."
                    )
                return existing
        batch = ResultBatch.objects.create(
            submitted_by=actor,
            normalized_manifest=normalized,
            manifest_sha256=digest,
            idempotency_key=key,
        )
        ResultBatchItem.objects.bulk_create(
            [
                ResultBatchItem(
                    batch=batch, position=index, file_name=name, payload=payload
                )
                for index, (name, payload) in enumerate(
                    normalized["results"].items(), 1
                )
            ]
        )
        return batch


@transaction.atomic
def commit_batch(batch_id, *, actor):
    batch = ResultBatch.objects.select_for_update().filter(pk=batch_id).first()
    if not batch or batch.submitted_by_id != actor.id or not actor.is_active:
        raise PermissionDenied(
            "This batch belongs to another contributor or does not exist."
        )
    items = list(batch.items.select_related("result"))
    if batch.committed_at:
        return tuple(item.result for item in items)
    try:
        assert_current("result", batch.normalized_manifest["schema_version"])
    except ContractError as error:
        raise ResultBatchError(str(error)) from error
    results = []
    try:
        for item in items:
            payload = _canonical_payload(item.payload, actor, item.file_name)
            item.result = create_submission("result", payload, submitter=actor).record
            item.save(update_fields=["result"])
            results.append(item.result)
    except (SubmissionError, IntegrityError) as error:
        raise ResultBatchError(str(error)) from error
    batch.committed_at = timezone.now()
    batch.save(update_fields=["committed_at"])
    return tuple(results)
