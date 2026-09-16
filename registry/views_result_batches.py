import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.api_auth import bearer_token_required
from registry.forms_batches import ResultBatchUploadForm
from registry.models import CircuitRevision, DecoderVersion, ResultBatch
from registry.schema_contracts import current_version
from registry.services.circuit_batches import extract_uploaded_files
from registry.services.result_batches import (
    ResultBatchError,
    batch_schema,
    commit_batch,
    parse_json,
    validate_batch,
)


def _example():
    return json.dumps(
        {
            "schema": "result-batch/0.1",
            "schema_version": current_version("result"),
            "defaults": {"visibility": "private"},
            "results": {"result-1.json": {}},
        },
        indent=2,
    )


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    form = ResultBatchUploadForm(request.POST or None, request.FILES or None)
    if request.method == "GET":
        form.fields["manifest_json"].initial = _example()
    if request.method == "POST" and form.is_valid():
        try:
            batch = validate_batch(
                actor=request.user,
                manifest=form.cleaned_data["manifest"],
                file_bytes=extract_uploaded_files(
                    form.cleaned_data["result_files"], suffix=".json"
                ),
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except ResultBatchError as error:
            form.add_error(None, str(error))
        else:
            return redirect("submissions:result-batch-preview", batch_id=batch.id)
    return render(request, "batches/result_create.html", {"form": form})


@login_required
@require_GET
def preview(request, batch_id):
    batch = get_object_or_404(ResultBatch, id=batch_id, submitted_by=request.user)
    items = list(batch.items.all())
    decoders = DecoderVersion.objects.in_bulk(
        item.payload["decoder_version"] for item in items
    )
    circuits = CircuitRevision.objects.in_bulk(
        item.payload["circuit_revision"] for item in items
    )
    decoder_names = {str(k): f"{v.name} {v.version}" for k, v in decoders.items()}
    circuit_names = {str(k): v.name for k, v in circuits.items()}
    for item in items:
        item.decoder_label = decoder_names.get(
            item.payload["decoder_version"], "Unavailable"
        )
        item.circuit_label = circuit_names.get(
            item.payload["circuit_revision"], "Unavailable"
        )
    return render(
        request,
        "batches/result_preview.html",
        {
            "batch": batch,
            "items": items,
            "manifest_json": json.dumps(batch.normalized_manifest, indent=2),
        },
    )


@login_required
@require_POST
def commit(request, batch_id):
    try:
        results = commit_batch(batch_id, actor=request.user)
    except ResultBatchError as error:
        messages.error(request, f"No results were submitted. {error}")
        return redirect("submissions:result-batch-preview", batch_id=batch_id)
    messages.success(request, f"Submitted {len(results)} results for review.")
    return redirect("submissions:profile")


@require_GET
def schema(request):
    return JsonResponse(batch_schema(), json_dumps_params={"indent": 2})


@csrf_exempt
@require_POST
@bearer_token_required("results:submit")
def api_validate(request):
    try:
        uploaded = request.FILES.get("manifest")
        manifest = parse_json(
            uploaded.read(1024 * 1024 + 1)
            if uploaded
            else request.POST.get("manifest", "")
        )
        batch = validate_batch(
            actor=request.user,
            manifest=manifest,
            file_bytes=extract_uploaded_files(
                request.FILES.getlist("files"), suffix=".json"
            ),
            idempotency_key=request.headers.get("Idempotency-Key")
            or request.POST.get("idempotency_key"),
        )
    except ResultBatchError as error:
        return JsonResponse(
            {"ok": False, "errors": [{"message": str(error)}]}, status=400
        )
    return JsonResponse(
        {
            "ok": True,
            "batch_id": str(batch.id),
            "state": batch.state,
            "report": {"valid": True, "result_count": batch.items.count()},
            "preview_url": reverse("submissions:result-batch-preview", args=[batch.id]),
            "commit_url": reverse("api-0.1:result-batch-commit", args=[batch.id]),
        }
    )


@csrf_exempt
@require_POST
@bearer_token_required("results:submit")
def api_commit(request, batch_id):
    try:
        results = commit_batch(batch_id, actor=request.user)
    except PermissionDenied as error:
        return JsonResponse({"ok": False, "error": str(error)}, status=403)
    except ResultBatchError as error:
        return JsonResponse(
            {"ok": False, "errors": [{"message": str(error)}]}, status=400
        )
    return JsonResponse(
        {
            "ok": True,
            "batch_id": str(batch_id),
            "results": [
                {
                    "id": str(result.id),
                    "state": result.state,
                    "visibility": result.visibility,
                }
                for result in results
            ],
        }
    )
