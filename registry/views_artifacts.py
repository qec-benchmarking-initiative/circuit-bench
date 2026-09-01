from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from registry.forms_artifacts import DevelopmentArtifactUploadForm
from registry.models import Artifact, SchemaRelease
from registry.services.artifacts import (
    ArtifactError,
    ArtifactIntegrityError,
    open_verified_artifact,
    store_uploaded_artifact,
    verify_artifact,
)


def artifact_index(request):
    _require_development()
    return render(
        request,
        "artifacts/index.html",
        {
            "artifacts": Artifact.objects.select_related("uploaded_by").order_by(
                "-created_at"
            )[:100],
            "schema_releases": SchemaRelease.objects.select_related(
                "json_schema_artifact", "definitions_artifact"
            ).order_by("record_type", "version"),
        },
    )


def artifact_upload(request):
    _require_development()
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    if request.method == "POST":
        form = DevelopmentArtifactUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                artifact, created = store_uploaded_artifact(
                    form.cleaned_data["file"],
                    uploaded_by=request.user,
                    media_type=form.cleaned_data["media_type"] or None,
                    expected_sha256=form.cleaned_data["expected_sha256"],
                    expected_byte_size=form.cleaned_data["expected_byte_size"],
                )
            except ArtifactError as error:
                form.add_error("file", str(error))
            else:
                outcome = (
                    "Stored a new file." if created else "Reused the existing file."
                )
                messages.success(request, outcome)
                return redirect("artifacts:detail", artifact_id=artifact.id)
    else:
        form = DevelopmentArtifactUploadForm()
    return render(request, "artifacts/upload.html", {"form": form})


def artifact_detail(request, artifact_id):
    _require_development()
    artifact = get_object_or_404(
        Artifact.objects.select_related("uploaded_by"), id=artifact_id
    )
    try:
        verification = verify_artifact(artifact)
    except ArtifactIntegrityError as error:
        verification = None
        verification_error = str(error)
    else:
        verification_error = None
    return render(
        request,
        "artifacts/detail.html",
        {
            "artifact": artifact,
            "verification": verification,
            "verification_error": verification_error,
        },
    )


def schema_release_detail(request, record_type, version):
    release = get_object_or_404(
        SchemaRelease.objects.select_related(
            "json_schema_artifact", "definitions_artifact"
        ),
        record_type=record_type,
        version=version,
    )
    return render(request, "artifacts/schema_release_detail.html", {"release": release})


def artifact_download(request, artifact_id):
    artifact = get_object_or_404(Artifact, id=artifact_id)
    try:
        stored_file, verification = open_verified_artifact(artifact)
    except ArtifactIntegrityError as error:
        return HttpResponse(
            f"File integrity verification failed: {error}",
            status=409,
            content_type="text/plain; charset=utf-8",
        )

    response = FileResponse(
        stored_file,
        as_attachment=True,
        filename=_download_filename(artifact.original_filename),
        content_type=artifact.media_type or "application/octet-stream",
    )
    response["Content-Length"] = verification.byte_size
    response["ETag"] = f'"{verification.sha256}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _require_development() -> None:
    if not settings.DEBUG:
        raise Http404


def _download_filename(filename: str) -> str:
    candidate = filename.replace("\\", "/").split("/")[-1]
    candidate = "".join(character for character in candidate if ord(character) >= 32)
    return candidate.strip()[:255] or "file.bin"
