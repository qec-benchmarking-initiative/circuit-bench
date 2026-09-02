from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from registry.forms_taxonomy import EczMappingForm, EczMappingRevocationForm
from registry.models import (
    EczSyncRun,
    EczTerm,
    TagEczMapping,
)
from registry.services.ecz_taxonomy import (
    EczTaxonomyError,
    create_tag_ecz_mapping,
    revoke_tag_ecz_mapping,
)
from registry.tag_taxonomy_graph import build_ecz_term_graph
from registry.tag_usage import (
    circuit_usage_context,
    include_descendants_from_request,
)


@require_GET
def term_detail(request, code_id):
    term = get_object_or_404(
        EczTerm.objects.select_related("first_seen_run", "last_seen_run"),
        ecz_code_id=code_id,
    )
    include_descendants = include_descendants_from_request(request)
    usage = circuit_usage_context(
        request,
        scope_arguments={
            "code_tag_slugs": (f"ecz:{term.ecz_code_id}",),
            "code_tag_match": "children" if include_descendants else "any",
        },
        reset_url=term.get_absolute_url(),
        grid_id=f"ecz-{term.ecz_code_id}-circuit-filters",
        label=f"Circuits tagged with {term.display_name}",
        empty=(
            f"No published circuits tagged with {term.display_name} match these "
            "controls."
        ),
    )
    mappings = list(
        TagEczMapping.objects.filter(ecz_term=term)
        .select_related("tag", "mapped_by", "revoked_by")
        .order_by("-mapped_at", "-id")
    )
    return render(
        request,
        "taxonomy/ecz_detail.html",
        {
            "term": term,
            "record": {
                "kind": "Error Correction Zoo tag",
                "name": term.display_name,
                "version": None,
                "status": term.status,
                "status_label": term.get_status_display(),
                "tags": (),
            },
            "tag_graph": build_ecz_term_graph(term),
            "mappings": mappings,
            "can_curate": request.user.is_authenticated and request.user.is_admin,
            **usage,
        },
    )


@login_required
@require_GET
def sync_status(request):
    _require_admin(request)
    runs = list(EczSyncRun.objects.order_by("-started_at", "-id")[:30])
    successful = next(
        (
            run
            for run in runs
            if run.status in (EczSyncRun.Status.APPLIED, EczSyncRun.Status.NO_CHANGE)
        ),
        None,
    )
    stale = not successful or successful.finished_at < timezone.now() - timedelta(
        days=7
    )
    current_count = EczTerm.objects.filter(status=EczTerm.Status.CURRENT).count()
    retired_count = EczTerm.objects.filter(status=EczTerm.Status.RETIRED).count()
    active_mappings = list(
        TagEczMapping.objects.filter(status=TagEczMapping.Status.ACTIVE)
        .select_related("tag", "ecz_term", "mapped_by")
        .order_by("tag__label", "id")
    )
    return render(
        request,
        "taxonomy/ecz_status.html",
        {
            "runs": runs,
            "successful": successful,
            "stale": stale,
            "current_count": current_count,
            "retired_count": retired_count,
            "active_mappings": active_mappings,
            "retired_target_mappings": [
                mapping
                for mapping in active_mappings
                if mapping.ecz_term.status == EczTerm.Status.RETIRED
            ],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def mapping_create(request):
    _require_admin(request)
    form = EczMappingForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            mapping = create_tag_ecz_mapping(
                tag_id=form.cleaned_data["tag"].id,
                ecz_term_id=form.cleaned_data["ecz_term"].id,
                actor=request.user,
                note=form.cleaned_data["note"],
            )
        except EczTaxonomyError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The ECZ equivalence mapping was created.")
            return redirect(mapping.ecz_term.get_absolute_url())
    return render(
        request,
        "taxonomy/ecz_mapping_form.html",
        {"title": "Map a Circuit Bench code tag to ECZ", "form": form},
    )


@login_required
@require_http_methods(["GET", "POST"])
def mapping_revoke(request, mapping_id):
    _require_admin(request)
    mapping = get_object_or_404(
        TagEczMapping.objects.select_related("tag", "ecz_term"),
        id=mapping_id,
        status=TagEczMapping.Status.ACTIVE,
    )
    form = EczMappingRevocationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            revoke_tag_ecz_mapping(
                mapping.id,
                actor=request.user,
                note=form.cleaned_data["note"],
            )
        except EczTaxonomyError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The ECZ equivalence mapping was revoked.")
            return redirect(mapping.ecz_term.get_absolute_url())
    return render(
        request,
        "taxonomy/ecz_mapping_form.html",
        {
            "title": "Demerge Circuit Bench and ECZ terms",
            "form": form,
            "mapping": mapping,
        },
    )


def _require_admin(request):
    if not request.user.is_admin:
        raise PermissionDenied
