import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.api_auth import bearer_token_required
from accounts.api_tokens import require_token_scopes
from registry.forms_batches import CircuitBatchUploadForm, example_batch_manifest
from registry.models import CircuitBatch
from registry.services.circuit_batches import (
    CircuitBatchError,
    batch_schema,
    commit_batch,
    extract_uploaded_files,
    parse_manifest,
    validate_batch,
)


@login_required
def batch_create(request):
    form = CircuitBatchUploadForm(request.POST or None, request.FILES or None)
    if request.method == "GET":
        form.fields["manifest_json"].initial = example_batch_manifest()
    if request.method == "POST" and form.is_valid():
        try:
            file_bytes = extract_uploaded_files(form.cleaned_data["circuit_files"])
            validation = validate_batch(
                actor=request.user,
                manifest=form.cleaned_data["manifest"],
                file_bytes=file_bytes,
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except CircuitBatchError as error:
            form.add_error(None, str(error))
        else:
            return redirect("collections:batch-preview", batch_id=validation.batch.id)
    return render(request, "batches/create.html", {"form": form})


@login_required
@require_GET
def batch_preview(request, batch_id):
    batch = get_object_or_404(
        CircuitBatch.objects.prefetch_related("items"), id=batch_id
    )
    if batch.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return render(
        request,
        "batches/preview.html",
        {
            "batch": batch,
            "manifest": batch.normalized_manifest,
            "manifest_json": json.dumps(
                batch.normalized_manifest, indent=2, sort_keys=True
            ),
        },
    )


@login_required
@require_POST
def batch_commit(request, batch_id):
    try:
        circuits = commit_batch(batch_id, actor=request.user)
    except CircuitBatchError as error:
        messages.error(request, f"No records were created. {error}")
        return redirect("collections:batch-preview", batch_id=batch_id)
    messages.success(
        request,
        (
            f"Submitted {len(circuits)} circuit "
            f"revision{'' if len(circuits) == 1 else 's'}."
        ),
    )
    return redirect("submissions:profile")


@require_GET
def batch_schema_json(request):
    return JsonResponse(batch_schema(), json_dumps_params={"indent": 2})


@require_GET
def openapi_json(request):
    return JsonResponse(
        {
            "openapi": "3.1.0",
            "info": {
                "title": "Circuit Bench submission API",
                "version": "0.1",
            },
            "servers": [{"url": request.build_absolute_uri("/api/0.1/")}],
            "components": {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}},
                "schemas": {"CircuitBatchManifest": batch_schema()},
            },
            "security": [{"bearerAuth": []}],
            "paths": {
                "/circuit-batches/validate/": {
                    "post": {
                        "summary": "Validate circuit files and a batch manifest",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "multipart/form-data": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["manifest", "files"],
                                        "properties": {
                                            "manifest": {
                                                "type": "string",
                                                "format": "binary",
                                            },
                                            "files": {
                                                "type": "array",
                                                "items": {
                                                    "type": "string",
                                                    "format": "binary",
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {"description": "Validated preview"},
                            "400": {"description": "Validation failed"},
                            "401": {"description": "Missing or invalid token"},
                            "403": {"description": "Token permission is insufficient"},
                        },
                    }
                },
                "/circuit-batches/{batch_id}/commit/": {
                    "post": {
                        "summary": "Commit a validated circuit batch",
                        "parameters": [
                            {
                                "name": "batch_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string", "format": "uuid"},
                            }
                        ],
                        "responses": {
                            "200": {"description": "Submitted circuit records"},
                            "400": {"description": "Commit failed"},
                            "401": {"description": "Missing or invalid token"},
                            "403": {"description": "Token permission is insufficient"},
                        },
                    }
                },
            },
        },
        json_dumps_params={"indent": 2},
    )


@csrf_exempt
@require_POST
@bearer_token_required("circuits:submit")
def api_batch_validate(request):
    try:
        uploaded_manifest = request.FILES.get("manifest")
        if uploaded_manifest:
            manifest = parse_manifest(uploaded_manifest.read())
        else:
            manifest = parse_manifest(request.POST.get("manifest", ""))
        _require_manifest_scopes(request, manifest)
        validation = validate_batch(
            actor=request.user,
            manifest=manifest,
            file_bytes=extract_uploaded_files(request.FILES.getlist("files")),
            idempotency_key=(
                request.headers.get("Idempotency-Key")
                or request.POST.get("idempotency_key")
            ),
        )
    except PermissionError as error:
        return JsonResponse(
            {"error": {"code": "insufficient_scope", "message": str(error)}},
            status=403,
        )
    except (CircuitBatchError, ValueError) as error:
        return JsonResponse(
            {"ok": False, "errors": [{"path": "", "message": str(error)}]},
            status=400,
        )
    return JsonResponse(
        {
            "ok": True,
            "batch_id": str(validation.batch.id),
            "state": validation.batch.state,
            "report": validation.batch.validation_report,
            "commit_url": f"/api/0.1/circuit-batches/{validation.batch.id}/commit/",
        }
    )


@csrf_exempt
@require_POST
@bearer_token_required("circuits:submit")
def api_batch_commit(request, batch_id):
    try:
        batch = CircuitBatch.objects.filter(id=batch_id).first()
        if batch is None:
            raise CircuitBatchError("Batch preview not found.")
        _require_manifest_scopes(request, batch.normalized_manifest)
        circuits = commit_batch(batch_id, actor=request.user)
    except PermissionError as error:
        return JsonResponse(
            {"error": {"code": "insufficient_scope", "message": str(error)}},
            status=403,
        )
    except (CircuitBatchError, PermissionDenied) as error:
        return JsonResponse(
            {"ok": False, "errors": [{"path": "", "message": str(error)}]},
            status=400,
        )
    return JsonResponse(
        {
            "ok": True,
            "batch_id": str(batch_id),
            "circuits": [
                {
                    "id": str(circuit.id),
                    "slug": circuit.slug,
                    "state": circuit.state,
                    "visibility": circuit.visibility,
                    "url": reverse("circuits:detail", args=[circuit.slug]),
                }
                for circuit in circuits
            ],
        }
    )


def _require_manifest_scopes(request, manifest):
    required = {"circuits:submit"}
    collection_changes = bool(manifest.get("new_collections")) or any(
        circuit.get("collections")
        for circuit in (manifest.get("circuits") or {}).values()
        if isinstance(circuit, dict)
    )
    if collection_changes:
        required.add("collections:write")
    if manifest.get("new_tags"):
        required.add("tags:write")
    require_token_scopes(request.api_token, required)
