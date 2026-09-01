"""Views for isolated tag and noise-model curation workflows."""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from registry.forms_taxonomy import (
    CurationNoteForm,
    CustomTagForm,
    NoiseModelSubmissionForm,
    TagDeprecationForm,
    TagPromotionForm,
)
from registry.models import NoiseModel, Tag
from registry.services.taxonomy import (
    TaxonomyError,
    TaxonomyPermissionError,
    approve_and_publish_noise_model,
    create_custom_tag,
    deprecate_noise_model,
    deprecate_tag,
    promote_noise_model_official,
    promote_tag_official,
    submit_noise_model,
)

PREVIEW_SESSION_KEY = "registry_taxonomy_previews"
PREVIEW_LIMIT = 8
TAG_POLICY = {
    "version": "0.1",
    "text": (
        "Custom tags are published immediately under the provisional custom-"
        "vocabulary route. Administrators may later promote or deprecate them."
    ),
}
NOISE_MODEL_POLICY = {
    "version": "0.1",
    "text": (
        "Noise-model submissions enter admin review as community models. Approval "
        "publishes the community record; official status is a separate curation "
        "decision."
    ),
}


@login_required
@require_http_methods(["GET", "POST"])
def custom_tag_create(request):
    initial = _restored_initial(request, "tag")
    form = CustomTagForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        token = _store_preview(request, "tag", form.payload())
        return redirect("taxonomy:tag-preview", preview_id=token)
    return render(
        request,
        "taxonomy/form.html",
        {
            "form": form,
            "kind": "tag",
            "title": "Create custom tag",
            "policy": TAG_POLICY,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def noise_model_submit(request):
    initial = _restored_initial(request, "noise_model")
    form = NoiseModelSubmissionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        token = _store_preview(request, "noise_model", form.payload())
        return redirect("taxonomy:noise-model-preview", preview_id=token)
    return render(
        request,
        "taxonomy/form.html",
        {
            "form": form,
            "kind": "noise_model",
            "title": "Submit noise model",
            "policy": NOISE_MODEL_POLICY,
        },
    )


@login_required
@require_GET
def noise_model_candidate(request, noise_model_id):
    noise_model = get_object_or_404(
        NoiseModel.objects.select_related(
            "submitted_by", "schema_release", "predecessor"
        ),
        id=noise_model_id,
    )
    if noise_model.submitted_by_id != request.user.id and not request.user.is_admin:
        raise PermissionDenied
    return render(
        request,
        "taxonomy/noise_model_candidate.html",
        {
            "noise_model": noise_model,
            "can_approve": request.user.is_admin
            and noise_model.state in {"pending_review", "pending_reapproval"},
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def custom_tag_preview(request, preview_id):
    preview = _preview_or_404(request, preview_id, "tag")
    payload = preview["payload"]
    error = None
    if request.method == "POST":
        try:
            outcome = create_custom_tag(submitter=request.user, **payload)
        except TaxonomyPermissionError as exception:
            raise PermissionDenied(str(exception)) from exception
        except TaxonomyError as exception:
            error = str(exception)
        else:
            _discard_preview(request, preview_id)
            return render(
                request,
                "taxonomy/confirmation.html",
                {
                    "title": "Custom tag created",
                    "record": outcome.tag,
                    "record_kind": "tag",
                },
            )
    return render(
        request,
        "taxonomy/preview.html",
        {
            "title": "Preview custom tag",
            "kind": "tag",
            "preview_id": preview_id,
            "rows": (
                ("Namespace", payload["namespace"]),
                ("Slug", payload["slug"]),
                ("Label", payload["label"]),
                ("Description", payload["description"]),
                ("Initial status", "Custom"),
            ),
            "back_url": f"/taxonomy/tags/new/?preview={preview_id}",
            "error": error,
            "policy": TAG_POLICY,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def noise_model_preview(request, preview_id):
    preview = _preview_or_404(request, preview_id, "noise_model")
    payload = preview["payload"]
    predecessor = None
    if payload.get("predecessor"):
        predecessor = NoiseModel.objects.filter(id=payload["predecessor"]).first()
    error = None
    if request.method == "POST":
        try:
            outcome = submit_noise_model(
                submitter=request.user,
                slug=payload["slug"],
                name=payload["name"],
                short_description=payload["short_description"],
                paper_url=payload["paper_url"],
                randomises_priors=payload["randomises_priors"],
                predecessor=predecessor,
            )
        except TaxonomyPermissionError as exception:
            raise PermissionDenied(str(exception)) from exception
        except TaxonomyError as exception:
            error = str(exception)
        else:
            _discard_preview(request, preview_id)
            return render(
                request,
                "taxonomy/confirmation.html",
                {
                    "title": "Noise model submitted",
                    "record": outcome.noise_model,
                    "record_kind": "noise_model",
                },
            )
    return render(
        request,
        "taxonomy/preview.html",
        {
            "title": "Preview noise model",
            "kind": "noise_model",
            "preview_id": preview_id,
            "rows": (
                ("Slug", payload["slug"]),
                ("Name", payload["name"]),
                ("Short description", payload["short_description"]),
                ("Paper URL", payload["paper_url"]),
                (
                    "Randomises priors",
                    "Yes" if payload["randomises_priors"] else "No",
                ),
                ("Previous revision", predecessor.name if predecessor else "None"),
                ("Initial curation", "Community"),
                ("Initial state", "Pending review"),
            ),
            "back_url": f"/taxonomy/noise-models/new/?preview={preview_id}",
            "error": error,
            "policy": NOISE_MODEL_POLICY,
        },
    )


@login_required
@require_GET
def curation_queue(request):
    _require_admin_view(request)
    active_tags = list(
        Tag.objects.exclude(status=Tag.Status.DEPRECATED)
        .select_related("submitted_by", "curated_by")
        .order_by("namespace", "status", "label", "id")
    )
    canonical_by_namespace = {
        namespace: list(
            Tag.objects.filter(namespace=namespace)
            .exclude(status=Tag.Status.DEPRECATED)
            .filter(canonical_tag__isnull=True)
            .order_by("status", "label", "id")
        )
        for namespace in Tag.Namespace.values
    }
    tag_rows = [
        {
            "tag": tag,
            "canonical_options": [
                candidate
                for candidate in canonical_by_namespace[tag.namespace]
                if candidate.id != tag.id
            ],
        }
        for tag in active_tags
    ]
    pending_noise_models = NoiseModel.objects.filter(
        state__in=("pending_review", "pending_reapproval")
    ).select_related("submitted_by", "predecessor")
    published_noise_models = NoiseModel.objects.filter(state="published").exclude(
        curation_status=NoiseModel.CurationStatus.DEPRECATED
    )
    return render(
        request,
        "taxonomy/curation_queue.html",
        {
            "tag_rows": tag_rows,
            "pending_noise_models": pending_noise_models.order_by("created_at", "id"),
            "published_noise_models": published_noise_models.order_by("name", "id"),
        },
    )


@login_required
@require_POST
def tag_promote(request, tag_id):
    _require_admin_view(request)
    form = TagPromotionForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_errors(form))
    else:
        try:
            promote_tag_official(
                tag_id,
                curator=request.user,
                display_color=form.cleaned_data["display_color"],
            )
        except TaxonomyError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The tag is now official.")
    return redirect("taxonomy:curation")


@login_required
@require_POST
def tag_deprecate(request, tag_id):
    _require_admin_view(request)
    tag = get_object_or_404(Tag, id=tag_id)
    form = TagDeprecationForm(request.POST, tag=tag)
    if not form.is_valid():
        messages.error(request, _form_errors(form))
    else:
        try:
            deprecate_tag(
                tag.id,
                curator=request.user,
                canonical_tag_id=form.cleaned_data["canonical_tag"].id,
            )
        except TaxonomyError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The tag was deprecated and mapped.")
    return redirect("taxonomy:curation")


@login_required
@require_POST
def noise_model_approve(request, noise_model_id):
    _require_admin_view(request)
    try:
        approve_and_publish_noise_model(noise_model_id, reviewer=request.user)
    except TaxonomyError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The community noise model was published.")
    return redirect("taxonomy:curation")


@login_required
@require_POST
def noise_model_promote(request, noise_model_id):
    _require_admin_view(request)
    try:
        promote_noise_model_official(noise_model_id, curator=request.user)
    except TaxonomyError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "The noise model is now official.")
    return redirect("taxonomy:curation")


@login_required
@require_POST
def noise_model_deprecate(request, noise_model_id):
    _require_admin_view(request)
    form = CurationNoteForm(request.POST)
    if not form.is_valid():
        messages.error(request, _form_errors(form))
    else:
        try:
            deprecate_noise_model(
                noise_model_id,
                curator=request.user,
                note=form.cleaned_data["note"],
            )
        except TaxonomyError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The noise model was deprecated.")
    return redirect("taxonomy:curation")


def _store_preview(request, kind: str, payload: dict) -> uuid.UUID:
    token = uuid.uuid4()
    previews = request.session.get(PREVIEW_SESSION_KEY, {})
    previews[str(token)] = {"kind": kind, "payload": payload}
    while len(previews) > PREVIEW_LIMIT:
        previews.pop(next(iter(previews)))
    request.session[PREVIEW_SESSION_KEY] = previews
    return token


def _preview_or_404(request, preview_id, kind: str) -> dict:
    preview = request.session.get(PREVIEW_SESSION_KEY, {}).get(str(preview_id))
    if not preview or preview.get("kind") != kind:
        raise Http404("Taxonomy preview not found")
    return preview


def _restored_initial(request, kind: str) -> dict | None:
    raw_token = request.GET.get("preview", "")
    if not raw_token:
        return None
    try:
        token = uuid.UUID(raw_token)
    except ValueError:
        return None
    preview = request.session.get(PREVIEW_SESSION_KEY, {}).get(str(token))
    if not preview or preview.get("kind") != kind:
        return None
    return preview["payload"]


def _discard_preview(request, preview_id) -> None:
    previews = request.session.get(PREVIEW_SESSION_KEY, {})
    previews.pop(str(preview_id), None)
    request.session[PREVIEW_SESSION_KEY] = previews


def _require_admin_view(request) -> None:
    if not request.user.is_active or not request.user.is_admin:
        raise PermissionDenied("Only active administrators may curate records.")


def _form_errors(form) -> str:
    return " ".join(
        str(message)
        for messages_for_field in form.errors.values()
        for message in messages_for_field
    )
