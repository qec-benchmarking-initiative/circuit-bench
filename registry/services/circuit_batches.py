"""Manifest-first Stim batch validation and commit services."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath

import stim
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator

from accounts.models import Account
from registry.models import (
    CircuitBatch,
    CircuitBatchItem,
    CircuitCollection,
    CircuitRevision,
    EczTerm,
    NoiseModel,
    Tag,
)
from registry.models.common import LifecycleState
from registry.services.artifacts import store_artifact_chunks
from registry.services.collections import (
    collection_queryset_for,
    create_collection,
    set_collection_members,
)
from registry.services.submissions import create_submission, validate_submission_payload
from registry.services.taxonomy import create_custom_tag
from registry.submission_policy import SubmissionKind

BATCH_SCHEMA_ID = "urn:circuit-bench:circuit-batch:0.1"
MAX_BATCH_FILES = 200
MAX_STIM_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 32 * 1024 * 1024
CLIENT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,99}$")


class CircuitBatchError(Exception):
    pass


@dataclass(frozen=True)
class BatchValidation:
    batch: CircuitBatch
    items: tuple[CircuitBatchItem, ...]


def batch_schema() -> dict:
    """Public contract; semantic checks are shared with browser validation."""

    reference = {"type": "string", "minLength": 1}
    reference_list = {"type": "array", "items": reference, "uniqueItems": True}
    circuit_properties = {
        "client_id": {"type": "string", "pattern": CLIENT_ID.pattern},
        "slug": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$"},
        "name": {"type": "string", "minLength": 1},
        "visibility": {"enum": ["public", "private"]},
        "description": {"type": ["string", "null"]},
        "revision_description": {"type": "string", "minLength": 1},
        "noise_model": reference,
        "is_css": {"type": "boolean"},
        "code_distance_upper_bound": {"type": ["integer", "null"], "minimum": 1},
        "circuit_distance_upper_bound": {
            "type": ["integer", "null"],
            "minimum": 1,
        },
        "rounds": {"type": ["integer", "null"], "minimum": 1},
        "dem_x_detectors_only": {"type": "boolean"},
        "dem_z_detectors_only": {"type": "boolean"},
        "dem_arguments": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                key: {"type": "boolean"}
                for key in (
                    "decompose_errors",
                    "flatten_loops",
                    "allow_gauge_detectors",
                    "approximate_disjoint_errors",
                    "ignore_decomposition_failures",
                    "block_decomposition_from_introducing_remnant_edges",
                )
            },
        },
        "code_tags": reference_list,
        "ecz_terms": reference_list,
        "experiment_tags": reference_list,
        "collections": reference_list,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": BATCH_SCHEMA_ID,
        "title": "Circuit Bench circuit batch manifest 0.1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", "circuits"],
        "properties": {
            "schema": {"const": "circuit-batch/0.1"},
            "defaults": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    key: value
                    for key, value in circuit_properties.items()
                    if key != "client_id"
                },
            },
            "circuits": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": circuit_properties,
                },
            },
            "new_tags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["client_id", "namespace", "label", "description"],
                    "properties": {
                        "client_id": {"type": "string", "pattern": CLIENT_ID.pattern},
                        "namespace": {"enum": list(Tag.Namespace.values)},
                        "label": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                        "visibility": {"enum": ["public", "private"]},
                        "aliases": {"type": "array", "items": {"type": "string"}},
                        "parents": reference_list,
                        "ecz_parents": reference_list,
                    },
                },
            },
            "new_collections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["client_id", "slug", "name"],
                    "properties": {
                        "client_id": {"type": "string", "pattern": CLIENT_ID.pattern},
                        "slug": {
                            "type": "string",
                            "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                        },
                        "name": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                        "visibility": {"enum": ["public", "private"]},
                        "code_tags": reference_list,
                        "ecz_terms": reference_list,
                        "experiment_tags": reference_list,
                        "children": reference_list,
                    },
                },
            },
        },
    }


def extract_uploaded_files(files) -> dict[str, bytes]:
    """Return safe, flat Stim names from uploads and optional zip archives."""

    extracted = {}
    expanded = 0
    for uploaded in files:
        name = PurePosixPath(uploaded.name).name
        raw = uploaded.read(MAX_ARCHIVE_BYTES + 1)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise CircuitBatchError(f"{name} exceeds the 16 MiB batch-file limit.")
        if name.lower().endswith(".zip"):
            try:
                archive = zipfile.ZipFile(BytesIO(raw))
            except zipfile.BadZipFile as error:
                raise CircuitBatchError(
                    f"{name} is not a readable zip file."
                ) from error
            for member in archive.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".stim"):
                    continue
                path = PurePosixPath(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise CircuitBatchError("Zip entries may not escape the archive.")
                file_name = path.name
                if member.file_size > MAX_STIM_BYTES:
                    raise CircuitBatchError(
                        f"{file_name} exceeds the 1 MiB circuit limit."
                    )
                if expanded + member.file_size > MAX_EXPANDED_BYTES:
                    raise CircuitBatchError("Expanded batch files exceed 32 MiB.")
                data = archive.read(member)
                expanded += len(data)
                _add_stim_file(extracted, file_name, data)
        else:
            expanded += len(raw)
            _add_stim_file(extracted, name, raw)
        if expanded > MAX_EXPANDED_BYTES:
            raise CircuitBatchError("Expanded batch files exceed 32 MiB.")
    if not extracted:
        raise CircuitBatchError(
            "Upload at least one .stim file or a zip containing one."
        )
    if len(extracted) > MAX_BATCH_FILES:
        raise CircuitBatchError(
            f"A batch may contain at most {MAX_BATCH_FILES} circuits."
        )
    return extracted


def parse_manifest(raw) -> dict:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        manifest = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CircuitBatchError(f"Manifest JSON is invalid: {error}.") from error
    if not isinstance(manifest, dict):
        raise CircuitBatchError("The manifest must be one JSON object.")
    if manifest.get("schema") != "circuit-batch/0.1":
        raise CircuitBatchError("Manifest schema must be circuit-batch/0.1.")
    allowed = {"schema", "defaults", "circuits", "new_tags", "new_collections"}
    unexpected = sorted(set(manifest) - allowed)
    if unexpected:
        raise CircuitBatchError(f"Unknown manifest field: {unexpected[0]}.")
    if not isinstance(manifest.get("circuits"), dict) or not manifest["circuits"]:
        raise CircuitBatchError("Manifest circuits must be a non-empty filename map.")
    _validate_manifest_schema(manifest)
    return manifest


def _object_without_duplicate_keys(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise CircuitBatchError(f"Manifest JSON repeats the key {key!r}.")
        output[key] = value
    return output


def validate_batch(
    *,
    actor: Account,
    manifest: dict,
    file_bytes: dict[str, bytes],
    idempotency_key: str | None = None,
) -> BatchValidation:
    if not actor.is_active:
        raise PermissionDenied("Inactive accounts cannot submit batches.")
    _validate_manifest_schema(manifest)
    idempotency_key = (idempotency_key or "").strip() or None
    normalized = _normalize_manifest(manifest, file_bytes=file_bytes, actor=actor)
    canonical = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    if idempotency_key:
        existing = CircuitBatch.objects.filter(
            submitted_by=actor, idempotency_key=idempotency_key
        ).first()
        if existing:
            if existing.manifest_sha256 != digest:
                raise CircuitBatchError(
                    "That idempotency key was already used for a different batch."
                )
            return BatchValidation(existing, tuple(existing.items.order_by("position")))
    with transaction.atomic():
        batch = CircuitBatch.objects.create(
            submitted_by=actor,
            state=CircuitBatch.State.VALIDATED,
            raw_manifest=manifest,
            normalized_manifest=normalized,
            validation_report={
                "valid": True,
                "file_count": len(normalized["circuits"]),
                "new_tag_count": len(normalized["new_tags"]),
                "new_collection_count": len(normalized["new_collections"]),
            },
            manifest_sha256=digest,
            idempotency_key=idempotency_key,
        )
        items = []
        for position, item in enumerate(normalized["circuits"], 1):
            artifact, _created = store_artifact_chunks(
                [file_bytes[item["file_name"]]],
                uploaded_by=actor,
                media_type="application/vnd.stim+circuit",
                original_filename=item["file_name"],
                max_bytes=MAX_STIM_BYTES,
            )
            items.append(
                CircuitBatchItem.objects.create(
                    batch=batch,
                    position=position,
                    client_id=item["client_id"],
                    file_name=item["file_name"],
                    sampling_artifact=artifact,
                )
            )
    return BatchValidation(batch, tuple(items))


def _validate_manifest_schema(manifest):
    errors = sorted(
        Draft202012Validator(batch_schema()).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    path = "/".join(str(part) for part in error.absolute_path)
    location = f" at {path}" if path else ""
    raise CircuitBatchError(
        f"Manifest does not match schema{location}: {error.message}"
    )


@transaction.atomic
def commit_batch(batch_id, *, actor: Account) -> tuple[CircuitRevision, ...]:
    try:
        batch = CircuitBatch.objects.select_for_update().get(id=batch_id)
    except CircuitBatch.DoesNotExist as error:
        raise CircuitBatchError("Batch preview not found.") from error
    if batch.submitted_by_id != actor.id:
        raise PermissionDenied("Only the contributor can commit this batch.")
    if batch.state == CircuitBatch.State.COMMITTED:
        return tuple(
            item.circuit_revision
            for item in batch.items.select_related("circuit_revision").order_by(
                "position"
            )
        )
    if batch.state != CircuitBatch.State.VALIDATED:
        raise CircuitBatchError("This batch is not ready to commit.")

    normalized = batch.normalized_manifest
    tag_ids = _create_declared_tags(normalized["new_tags"], actor=actor)
    collections = _create_declared_collections(
        normalized["new_collections"], tag_ids=tag_ids, actor=actor
    )
    items_by_name = {
        item.file_name: item
        for item in batch.items.select_for_update()
        .select_related("sampling_artifact")
        .order_by("position")
    }
    created = []
    membership_requests = []
    for spec in normalized["circuits"]:
        item = items_by_name[spec["file_name"]]
        payload = _materialize_circuit_payload(
            spec,
            sampling_artifact=item.sampling_artifact,
            tag_ids=tag_ids,
            actor=actor,
        )
        outcome = create_submission(SubmissionKind.CIRCUIT, payload, submitter=actor)
        item.circuit_revision = outcome.record
        item.save(update_fields=["circuit_revision"])
        created.append(outcome.record)
        for collection_ref in spec["collections"]:
            membership_requests.append((collection_ref, outcome.record))

    membership_references = {
        reference
        for spec in normalized["circuits"]
        for reference in spec["collections"]
    }
    child_references = {
        reference
        for declaration in normalized["new_collections"]
        for reference in declaration["children"]
    }
    destination_collections = _resolve_collection_map(
        membership_references, collections, actor=actor, require_owned=True
    )
    child_collections = _resolve_collection_map(
        child_references, collections, actor=actor, require_owned=False
    )
    for declaration in normalized["new_collections"]:
        collection = collections[declaration["client_id"]]
        children = [child_collections[value] for value in declaration["children"]]
        _append_collection_contents(collection, actor=actor, children=children)
    for reference, circuit in membership_requests:
        _append_collection_contents(
            destination_collections[reference], actor=actor, circuits=[circuit]
        )

    batch.state = CircuitBatch.State.COMMITTED
    batch.committed_at = timezone.now()
    batch.save(update_fields=["state", "committed_at"])
    return tuple(created)


def _normalize_manifest(manifest, *, file_bytes, actor):
    file_specs = manifest["circuits"]
    missing = sorted(set(file_specs) - set(file_bytes))
    extra = sorted(set(file_bytes) - set(file_specs))
    if missing:
        raise CircuitBatchError(f"Missing uploaded file: {missing[0]}.")
    if extra:
        raise CircuitBatchError(f"Uploaded file is absent from manifest: {extra[0]}.")
    defaults = manifest.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise CircuitBatchError("Manifest defaults must be an object.")

    new_tags = _normalize_new_tags(manifest.get("new_tags") or [])
    new_collections = _normalize_new_collections(manifest.get("new_collections") or [])
    new_tag_refs = {f"new:{item['client_id']}": item["namespace"] for item in new_tags}
    new_collection_refs = {f"new:{item['client_id']}" for item in new_collections}
    _validate_new_tag_declarations(
        new_tags,
        actor=actor,
        new_tag_refs=new_tag_refs,
    )
    _validate_collection_declarations(
        new_collections,
        actor=actor,
        new_tag_refs=new_tag_refs,
        new_collection_refs=new_collection_refs,
    )
    normalized_circuits = []
    seen_slugs = set()
    seen_client_ids = set()
    for position, (file_name, supplied) in enumerate(file_specs.items(), 1):
        if not isinstance(supplied, dict):
            raise CircuitBatchError(f"Manifest entry {file_name} must be an object.")
        data = {**defaults, **supplied}
        allowed_fields = set(
            batch_schema()["properties"]["circuits"]["additionalProperties"][
                "properties"
            ]
        )
        unexpected = sorted(set(data) - allowed_fields)
        if unexpected:
            raise CircuitBatchError(f"Unknown field in {file_name}: {unexpected[0]}.")
        client_id = data.pop("client_id", f"circuit-{position}")
        if not CLIENT_ID.fullmatch(str(client_id)) or str(client_id) in seen_client_ids:
            raise CircuitBatchError(f"Invalid client_id for {file_name}.")
        seen_client_ids.add(str(client_id))
        slug = str(data.get("slug", "")).strip()
        if not slug or slug in seen_slugs:
            raise CircuitBatchError(f"Every circuit needs a unique slug ({file_name}).")
        seen_slugs.add(slug)
        if CircuitRevision.objects.filter(slug=slug).exists():
            raise CircuitBatchError(f"Circuit slug is already in use: {slug}.")
        derived = _derive_stim(file_name, file_bytes[file_name], data)
        if derived["num_observables"] < 1:
            raise CircuitBatchError(
                f"{file_name} has no observables; circuit records need at least one."
            )
        spec = {
            "file_name": file_name,
            "client_id": str(client_id),
            **data,
            "name": str(data.get("name") or PurePosixPath(file_name).stem),
            "visibility": data.get("visibility", "public"),
            "derived": derived,
            "collections": list(dict.fromkeys(data.get("collections") or [])),
        }
        _validate_references(
            spec,
            actor=actor,
            new_tag_refs=new_tag_refs,
            new_collection_refs=new_collection_refs,
        )
        normalized_circuits.append(spec)
    return {
        "schema": "circuit-batch/0.1",
        "new_tags": new_tags,
        "new_collections": new_collections,
        "circuits": normalized_circuits,
    }


def _derive_stim(file_name, data, spec):
    if len(data) > MAX_STIM_BYTES:
        raise CircuitBatchError(f"{file_name} exceeds the 1 MiB circuit limit.")
    try:
        circuit = stim.Circuit(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise CircuitBatchError(
            f"Stim could not parse {file_name}: {error}."
        ) from error
    arguments = spec.get("dem_arguments") or {}
    allowed = {
        "decompose_errors",
        "flatten_loops",
        "allow_gauge_detectors",
        "approximate_disjoint_errors",
        "ignore_decomposition_failures",
        "block_decomposition_from_introducing_remnant_edges",
    }
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        raise CircuitBatchError(f"Invalid dem_arguments for {file_name}.")
    args = {key: False for key in allowed}
    args.update(arguments)
    if any(not isinstance(value, bool) for value in args.values()):
        raise CircuitBatchError(f"DEM arguments for {file_name} must be boolean.")
    try:
        dem = circuit.detector_error_model(**args)
    except ValueError as error:
        raise CircuitBatchError(
            f"Stim could not compile {file_name}: {error}."
        ) from error
    return {
        "num_detectors": circuit.num_detectors,
        "num_observables": circuit.num_observables,
        "num_errors": dem.num_errors,
        "stim_version": stim.__version__,
        "dem_arguments": args,
        "dem_text": str(dem),
    }


def _materialize_circuit_payload(spec, *, sampling_artifact, tag_ids, actor):
    derived = spec["derived"]
    dem_bytes = derived["dem_text"].encode()
    dem_artifact, _ = store_artifact_chunks(
        [dem_bytes],
        uploaded_by=actor,
        media_type="application/vnd.stim+dem",
        original_filename=f"{PurePosixPath(spec['file_name']).stem}.dem",
    )
    manifest_data = {
        "schema": "circuit-ingest/0.1",
        "sampling_sha256": sampling_artifact.sha256,
        "dem_sha256": dem_artifact.sha256,
        "stim_version": derived["stim_version"],
        "dem_arguments": derived["dem_arguments"],
        "derived": {
            key: derived[key]
            for key in ("num_detectors", "num_errors", "num_observables")
        },
    }
    manifest_bytes = json.dumps(
        manifest_data, sort_keys=True, separators=(",", ":")
    ).encode()
    manifest_artifact, _ = store_artifact_chunks(
        [manifest_bytes],
        uploaded_by=actor,
        media_type="application/json",
        original_filename=f"{PurePosixPath(spec['file_name']).stem}.manifest.json",
    )
    args = derived["dem_arguments"]
    payload = {
        "visibility": spec.get("visibility", "public"),
        "slug": spec["slug"],
        "name": spec.get("name") or PurePosixPath(spec["file_name"]).stem,
        "previous_revision": None,
        "description": spec.get("description"),
        "revision_description": spec.get(
            "revision_description", "First submitted revision."
        ),
        "noise_model": str(spec["noise_model"]),
        "is_css": bool(spec.get("is_css", False)),
        "code_distance_upper_bound": spec.get("code_distance_upper_bound"),
        "circuit_distance_upper_bound": spec.get("circuit_distance_upper_bound"),
        "rounds": spec.get("rounds"),
        "num_detectors": derived["num_detectors"],
        "num_errors": derived["num_errors"],
        "num_observables": derived["num_observables"],
        "dem_x_detectors_only": bool(spec.get("dem_x_detectors_only", False)),
        "dem_z_detectors_only": bool(spec.get("dem_z_detectors_only", False)),
        "stim_version": derived["stim_version"],
        "dem_decompose_errors": args["decompose_errors"],
        "dem_flatten_loops": args["flatten_loops"],
        "dem_allow_gauge_detectors": args["allow_gauge_detectors"],
        "dem_approximate_disjoint_errors": args["approximate_disjoint_errors"],
        "dem_ignore_decomposition_failures": args["ignore_decomposition_failures"],
        "dem_block_decomposition_from_introducing_remnant_edges": args[
            "block_decomposition_from_introducing_remnant_edges"
        ],
        "sampling_circuit_artifact": str(sampling_artifact.id),
        "detector_error_model_artifact": str(dem_artifact.id),
        "manifest_artifact": str(manifest_artifact.id),
        "code_tags": [
            _resolve_tag_ref(value, tag_ids) for value in spec.get("code_tags", [])
        ],
        "ecz_terms": [str(value) for value in spec.get("ecz_terms", [])],
        "experiment_tags": [
            _resolve_tag_ref(value, tag_ids)
            for value in spec.get("experiment_tags", [])
        ],
        "collections": [],
    }
    return validate_submission_payload(SubmissionKind.CIRCUIT, payload, actor=actor)


def _normalize_new_tags(items):
    if not isinstance(items, list):
        raise CircuitBatchError("new_tags must be an array.")
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise CircuitBatchError("Each new tag declaration must be an object.")
        client_id = str(item.get("client_id", ""))
        namespace = item.get("namespace")
        if not CLIENT_ID.fullmatch(client_id) or client_id in seen:
            raise CircuitBatchError(
                "New tag client_id values must be unique identifiers."
            )
        if namespace not in Tag.Namespace.values:
            raise CircuitBatchError(f"New tag {client_id} has an invalid namespace.")
        visibility = item.get("visibility", "public")
        if visibility not in {"public", "private"}:
            raise CircuitBatchError(f"New tag {client_id} has invalid visibility.")
        if (
            not str(item.get("label", "")).strip()
            or not str(item.get("description", "")).strip()
        ):
            raise CircuitBatchError(
                f"New tag {client_id} needs a label and description."
            )
        seen.add(client_id)
        normalized.append(
            {
                "client_id": client_id,
                "namespace": namespace,
                "label": str(item["label"]).strip(),
                "description": str(item["description"]).strip(),
                "visibility": visibility,
                "aliases": item.get("aliases") or [],
                "parents": item.get("parents") or [],
                "ecz_parents": item.get("ecz_parents") or [],
            }
        )
    return normalized


def _normalize_new_collections(items):
    if not isinstance(items, list):
        raise CircuitBatchError("new_collections must be an array.")
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise CircuitBatchError(
                "Each new collection declaration must be an object."
            )
        client_id = str(item.get("client_id", ""))
        if not CLIENT_ID.fullmatch(client_id) or client_id in seen:
            raise CircuitBatchError(
                "New collection client_id values must be unique identifiers."
            )
        if (
            not str(item.get("slug", "")).strip()
            or not str(item.get("name", "")).strip()
        ):
            raise CircuitBatchError(
                f"New collection {client_id} needs a slug and name."
            )
        seen.add(client_id)
        normalized.append(
            {
                "client_id": client_id,
                "slug": str(item["slug"]).strip(),
                "name": str(item["name"]).strip(),
                "description": str(item.get("description", "")).strip(),
                "visibility": item.get("visibility", "public"),
                "code_tags": item.get("code_tags") or [],
                "ecz_terms": item.get("ecz_terms") or [],
                "experiment_tags": item.get("experiment_tags") or [],
                "children": item.get("children") or [],
            }
        )
    return normalized


def _validate_references(spec, *, actor, new_tag_refs, new_collection_refs):
    try:
        noise = NoiseModel.objects.get(id=spec.get("noise_model"), state="published")
    except (ValueError, NoiseModel.DoesNotExist) as error:
        raise CircuitBatchError(
            f"{spec['file_name']} needs a published noise_model UUID."
        ) from error
    if (
        noise.visibility == "private"
        and noise.submitted_by_id != actor.id
        and not actor.is_admin
    ):
        raise CircuitBatchError(f"Noise model is not visible for {spec['file_name']}.")
    for field, namespace in (
        ("code_tags", Tag.Namespace.CODE),
        ("experiment_tags", Tag.Namespace.EXPERIMENT),
    ):
        values = spec.get(field) or []
        for value in values:
            if value in new_tag_refs:
                if new_tag_refs[value] != namespace:
                    raise CircuitBatchError(
                        f"{value} has the wrong tag kind for {field}."
                    )
                continue
            try:
                tag = Tag.objects.get(id=value, namespace=namespace)
            except (ValueError, Tag.DoesNotExist) as error:
                raise CircuitBatchError(
                    f"Invalid {field} reference in {spec['file_name']}: {value}."
                ) from error
            if (
                tag.visibility == "private"
                and tag.submitted_by_id != actor.id
                and not actor.is_admin
            ):
                raise CircuitBatchError(
                    f"A tag is not visible for {spec['file_name']}."
                )
    for value in spec.get("ecz_terms") or []:
        if not EczTerm.objects.filter(id=value).exists():
            raise CircuitBatchError(f"Invalid ECZ reference in {spec['file_name']}.")
    if not (spec.get("code_tags") or spec.get("ecz_terms")):
        raise CircuitBatchError(f"{spec['file_name']} needs a code classification.")
    if not spec.get("experiment_tags"):
        raise CircuitBatchError(f"{spec['file_name']} needs an experiment tag.")
    for value in spec["collections"]:
        if value in new_collection_refs:
            continue
        collection = _owned_collection(value, actor=actor)
        if collection is None:
            raise CircuitBatchError(
                f"You do not curate collection {value} ({spec['file_name']})."
            )


def _create_declared_tags(declarations, *, actor):
    output = {}
    pending = {f"new:{item['client_id']}": item for item in declarations}
    while pending:
        created_this_pass = []
        for reference, item in pending.items():
            new_parents = [
                parent for parent in item["parents"] if parent.startswith("new:")
            ]
            if any(parent not in output for parent in new_parents):
                continue
            outcome = create_custom_tag(
                submitter=actor,
                namespace=item["namespace"],
                label=item["label"],
                description=item["description"],
                aliases=item["aliases"],
                parents=[output.get(parent, parent) for parent in item["parents"]],
                ecz_parents=item["ecz_parents"],
                visibility=item["visibility"],
            )
            output[reference] = str(outcome.tag.id)
            created_this_pass.append(reference)
        if not created_this_pass:
            raise CircuitBatchError("New tag parent references contain a cycle.")
        for reference in created_this_pass:
            pending.pop(reference)
    return output


def _validate_new_tag_declarations(declarations, *, actor, new_tag_refs):
    graph = {}
    for item in declarations:
        reference = f"new:{item['client_id']}"
        graph[reference] = set()
        for parent in item["parents"]:
            if parent in new_tag_refs:
                if new_tag_refs[parent] != item["namespace"]:
                    raise CircuitBatchError(
                        f"{parent} has the wrong tag kind for parent of {reference}."
                    )
                graph[reference].add(parent)
                continue
            try:
                tag = Tag.objects.get(id=parent, namespace=item["namespace"])
            except (ValueError, Tag.DoesNotExist) as error:
                raise CircuitBatchError(
                    f"Invalid parent reference for new tag {reference}: {parent}."
                ) from error
            if (
                tag.visibility == "private"
                and tag.submitted_by_id != actor.id
                and not actor.is_admin
            ):
                raise CircuitBatchError(
                    f"A parent tag is not visible for new tag {reference}."
                )
        if item["ecz_parents"] and item["namespace"] != Tag.Namespace.CODE:
            raise CircuitBatchError(
                f"Only code tags may have ECZ parents ({reference})."
            )
        for parent in item["ecz_parents"]:
            if not EczTerm.objects.filter(
                id=parent, status=EczTerm.Status.CURRENT
            ).exists():
                raise CircuitBatchError(
                    f"Invalid ECZ parent for new tag {reference}: {parent}."
                )
    _assert_reference_graph_acyclic(graph, "New tag parent references")


def _validate_collection_declarations(
    declarations,
    *,
    actor,
    new_tag_refs,
    new_collection_refs,
):
    seen_slugs = set()
    graph = {}
    for item in declarations:
        reference = f"new:{item['client_id']}"
        graph[reference] = set()
        if item["visibility"] not in {"public", "private"}:
            raise CircuitBatchError(
                f"Collection {item['client_id']} has invalid visibility."
            )
        if (
            item["slug"] in seen_slugs
            or CircuitCollection.objects.filter(slug=item["slug"]).exists()
        ):
            raise CircuitBatchError(
                f"Collection slug is already in use: {item['slug']}."
            )
        seen_slugs.add(item["slug"])
        for field, namespace in (
            ("code_tags", Tag.Namespace.CODE),
            ("experiment_tags", Tag.Namespace.EXPERIMENT),
        ):
            for value in item[field]:
                if value in new_tag_refs:
                    if new_tag_refs[value] != namespace:
                        raise CircuitBatchError(
                            f"{value} has the wrong tag kind for {field}."
                        )
                    continue
                try:
                    tag = Tag.objects.get(id=value, namespace=namespace)
                except (ValueError, Tag.DoesNotExist) as error:
                    raise CircuitBatchError(
                        f"Invalid {field} reference in collection {item['name']}."
                    ) from error
                if (
                    tag.visibility == "private"
                    and tag.submitted_by_id != actor.id
                    and not actor.is_admin
                ):
                    raise CircuitBatchError(
                        f"A tag is not visible for collection {item['name']}."
                    )
        for value in item["ecz_terms"]:
            if not EczTerm.objects.filter(id=value).exists():
                raise CircuitBatchError(
                    f"Invalid ECZ reference in collection {item['name']}."
                )
        for child in item["children"]:
            if child in new_collection_refs:
                graph[reference].add(child)
                continue
            if _visible_collection(child, actor=actor) is None:
                raise CircuitBatchError(
                    f"Unavailable child collection reference: {child}."
                )
    _assert_reference_graph_acyclic(graph, "New collection nesting")


def _assert_reference_graph_acyclic(graph, label):
    active = set()
    complete = set()

    def visit(node):
        if node in active:
            raise CircuitBatchError(f"{label} contain a cycle.")
        if node in complete:
            return
        active.add(node)
        for adjacent in graph.get(node, ()):
            visit(adjacent)
        active.remove(node)
        complete.add(node)

    for node in graph:
        visit(node)


def _create_declared_collections(declarations, *, tag_ids, actor):
    output = {}
    for item in declarations:
        code_tags = Tag.objects.filter(
            id__in=[_resolve_tag_ref(value, tag_ids) for value in item["code_tags"]],
            namespace=Tag.Namespace.CODE,
        )
        experiments = Tag.objects.filter(
            id__in=[
                _resolve_tag_ref(value, tag_ids) for value in item["experiment_tags"]
            ],
            namespace=Tag.Namespace.EXPERIMENT,
        )
        ecz_terms = EczTerm.objects.filter(id__in=item["ecz_terms"])
        output[item["client_id"]] = create_collection(
            actor=actor,
            slug=item["slug"],
            name=item["name"],
            description=item["description"],
            visibility=item["visibility"],
            code_tags=code_tags,
            experiment_tags=experiments,
            ecz_terms=ecz_terms,
        )
    return output


def _resolve_collection_map(references, created, *, actor, require_owned):
    output = {f"new:{key}": value for key, value in created.items()}
    for reference in references:
        if reference.startswith("new:"):
            if reference not in output:
                raise CircuitBatchError(
                    f"New collection reference is undeclared: {reference}."
                )
            continue
        resolver = _owned_collection if require_owned else _visible_collection
        collection = resolver(reference, actor=actor)
        if collection is None:
            raise CircuitBatchError(
                f"Collection reference is unavailable: {reference}."
            )
        output[reference] = collection
    return output


def _owned_collection(reference, *, actor):
    queryset = CircuitCollection.objects.all()
    if not actor.is_admin:
        queryset = queryset.filter(submitted_by=actor)
    try:
        return queryset.filter(id=reference).first()
    except (ValueError, TypeError):
        return queryset.filter(slug=reference).first()


def _visible_collection(reference, *, actor):
    queryset = collection_queryset_for(actor).filter(state=LifecycleState.PUBLISHED)
    try:
        return queryset.filter(id=reference).first()
    except (ValueError, TypeError):
        return queryset.filter(slug=reference).first()


def _append_collection_contents(collection, *, actor, circuits=(), children=()):
    current_circuits = list(
        collection.circuit_memberships.filter(removed_at__isnull=True)
        .order_by("position")
        .values_list("circuit_revision_id", flat=True)
    )
    current_children = list(
        collection.child_memberships.filter(removed_at__isnull=True)
        .order_by("position")
        .values_list("child_id", flat=True)
    )
    set_collection_members(
        collection,
        actor=actor,
        circuit_ids=[*current_circuits, *(item.id for item in circuits)],
        child_ids=[*current_children, *(item.id for item in children)],
    )


def _resolve_tag_ref(value, tag_ids):
    return str(tag_ids.get(value, value))


def _add_stim_file(output, name, data):
    if not name.lower().endswith(".stim"):
        raise CircuitBatchError(f"Only .stim files are accepted ({name}).")
    if name in output:
        raise CircuitBatchError(f"Duplicate filename in batch: {name}.")
    if len(data) > MAX_STIM_BYTES:
        raise CircuitBatchError(f"{name} exceeds the 1 MiB circuit limit.")
    output[name] = data
