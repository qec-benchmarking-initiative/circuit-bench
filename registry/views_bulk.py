from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from registry.forms_bulk import BulkActionForm
from registry.services.bulk_actions import (
    BulkActionError,
    apply_bulk_action,
    plan_collection_visibility_cascade,
    resolve_targets,
    validate_bulk_action,
)
from registry.services.visibility import VisibilityError


@login_required
@require_POST
def bulk_preview(request):
    form = BulkActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a valid bulk action and at least one record.")
        return redirect(_return_url(request))
    try:
        cascade = None
        if form.cleaned_data.get("collection_visibility_cascade"):
            cascade = plan_collection_visibility_cascade(
                form.cleaned_data.get("collection_scope"),
                action=form.cleaned_data["action"],
                actor=request.user,
            )
            targets = cascade.targets
        else:
            targets = resolve_targets(
                form.selected_targets(),
                actor=request.user,
                collection_scope=form.cleaned_data.get("collection_scope"),
            )
        validate_bulk_action(form.cleaned_data["action"], targets, actor=request.user)
    except (BulkActionError, VisibilityError, PermissionDenied) as error:
        messages.error(request, str(error))
        return redirect(_return_url(request))
    return render(
        request,
        "bulk/preview.html",
        {
            "form": form,
            "targets": targets,
            "cascade": cascade,
            "return_url": _return_url(request),
            "action_label": dict(form.fields["action"].choices)[
                form.cleaned_data["action"]
            ],
        },
    )


@login_required
@require_POST
def bulk_commit(request):
    form = BulkActionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "The bulk action could not be reconstructed.")
        return redirect(_return_url(request))
    try:
        targets = resolve_targets(
            form.selected_targets(),
            actor=request.user,
            collection_scope=form.cleaned_data.get("collection_scope"),
        )
        count = apply_bulk_action(
            form.cleaned_data["action"],
            targets,
            actor=request.user,
            note=form.cleaned_data["note"],
        )
    except (BulkActionError, VisibilityError, PermissionDenied) as error:
        messages.error(request, f"No records were changed. {error}")
    else:
        messages.success(request, f"Bulk action completed for {count} records.")
    return redirect(_return_url(request))


def _return_url(request):
    value = request.POST.get("return_url", "")
    return (
        value if value.startswith("/") and not value.startswith("//") else "/profile/"
    )
