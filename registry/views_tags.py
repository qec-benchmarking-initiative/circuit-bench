"""Public tag records, alias-aware creation, and owner/admin editing."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from registry.filter_grids import choice_cell, filter_grid, range_cell
from registry.forms_taxonomy import TagEditForm
from registry.models import Tag, TagEczMapping
from registry.services.decoders import public_decoder_catalogue
from registry.services.tags import active_tag_queryset, tag_detail_queryset
from registry.services.taxonomy import (
    TaxonomyConflictError,
    TaxonomyError,
    TaxonomyPermissionError,
    can_edit_tag,
    can_retire_tag,
    create_custom_tag,
    normalise_tag_aliases,
    retire_tag,
    update_tag,
)
from registry.table_controls import (
    ColumnSpec,
    apply_sort,
    cells_for_visible_columns,
    parse_nonnegative_int,
    parse_sort,
    table_context,
    url_without,
)
from registry.tag_taxonomy_graph import build_local_tag_graph
from registry.tag_usage import (
    circuit_usage_context,
    include_descendants_from_request,
)

ALGORITHM_COLUMNS = (
    ColumnSpec("name", "Decoder"),
    ColumnSpec("version", "Version"),
    ColumnSpec("skeleton", "Skeleton preparation"),
    ColumnSpec("priors", "Prior preparation"),
    ColumnSpec("probability", "Failure probability"),
    ColumnSpec("results", "Results", numeric=True, default_direction="desc"),
    ColumnSpec("published", "Published", default_direction="desc"),
)


@login_required
@require_POST
def create_tag_json(request):
    try:
        outcome = create_custom_tag(
            submitter=request.user,
            namespace=request.POST.get("namespace", ""),
            label=request.POST.get("label", ""),
            description=request.POST.get("description", ""),
            aliases=request.POST.get("aliases", ""),
            parents=request.POST.getlist("parents"),
            ecz_parents=request.POST.getlist("ecz_parents"),
        )
    except TaxonomyPermissionError as error:
        return JsonResponse({"error": str(error)}, status=403)
    except TaxonomyConflictError as error:
        return JsonResponse({"error": str(error)}, status=409)
    except TaxonomyError as error:
        return JsonResponse({"error": str(error)}, status=400)
    tag = outcome.tag
    return JsonResponse(
        {
            "tag": {
                "id": str(tag.id),
                "namespace": tag.namespace,
                "label": tag.label,
                "slug": tag.slug,
                "status": tag.status,
                "display_color": tag.display_color,
                "aliases": list(normalise_tag_aliases(request.POST.get("aliases", ""))),
                "parents": [
                    {
                        "id": str(parent.id),
                        "label": parent.label,
                        "status": parent.status,
                        "display_color": parent.display_color,
                        "namespace": parent.namespace,
                        "url": parent.get_absolute_url(),
                    }
                    for parent in tag.parents.all()
                ],
                "url": tag.get_absolute_url(),
            }
        },
        status=201,
    )


@require_GET
def tag_detail(request, namespace, slug):
    tag = get_object_or_404(
        tag_detail_queryset(),
        namespace=namespace,
        slug=slug,
    )
    usage = (
        _algorithm_usage(request, tag)
        if tag.namespace == Tag.Namespace.ALGORITHM
        else _circuit_usage(request, tag)
    )
    ecz_mappings = list(
        TagEczMapping.objects.filter(tag=tag)
        .select_related("ecz_term", "mapped_by", "revoked_by")
        .order_by("-mapped_at", "-id")
    )
    return render(
        request,
        "taxonomy/tag_detail.html",
        {
            "tag": tag,
            "can_edit": can_edit_tag(tag, request.user),
            "can_retire": can_retire_tag(tag, request.user),
            "record": {
                "kind": f"{tag.get_namespace_display()} tag",
                "name": tag.label,
                "status": tag.status,
                "status_label": (
                    "Deleted"
                    if tag.status == Tag.Status.RETIRED
                    else tag.get_status_display()
                ),
                "version": None,
                "tags": (),
            },
            "tag_graph": build_local_tag_graph(tag),
            "ecz_mappings": ecz_mappings,
            **usage,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def tag_edit(request, namespace, slug):
    tag = get_object_or_404(
        tag_detail_queryset(),
        namespace=namespace,
        slug=slug,
    )
    if not can_edit_tag(tag, request.user):
        raise PermissionDenied("You cannot edit this tag.")
    initial = {
        "label": tag.label,
        "description": tag.description,
        "aliases": "\n".join(alias.alias for alias in tag.display_aliases),
        "parents": list(tag.parents.values_list("id", flat=True)),
        "ecz_parents": list(tag.ecz_parents.values_list("id", flat=True)),
    }
    form = TagEditForm(request.POST or None, tag=tag, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            update_tag(tag.id, actor=request.user, **form.cleaned_data)
        except TaxonomyPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except TaxonomyError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "The tag was updated.")
            return redirect(tag.get_absolute_url())
    current_parent_ids = list(tag.parents.values_list("id", flat=True))
    parent_tags = list(active_tag_queryset(include_ids=current_parent_ids))
    for parent in parent_tags:
        parent.picker_key = str(parent.id)
    selected_parent_ids = {
        str(parent_id)
        for parent_id in form["parents"].value()
        or tag.parents.values_list("id", flat=True)
    }
    return render(
        request,
        "taxonomy/tag_edit.html",
        {
            "tag": tag,
            "form": form,
            "parent_tags": [item for item in parent_tags if item.id != tag.id],
            "selected_parent_ids": selected_parent_ids,
            "selected_ecz_parents": list(
                form.fields["ecz_parents"].queryset.filter(
                    id__in=form["ecz_parents"].value() or ()
                )
            ),
            "excluded_taxonomy_key": f"cb:{tag.id}",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def tag_delete(request, namespace, slug):
    tag = get_object_or_404(
        tag_detail_queryset(),
        namespace=namespace,
        slug=slug,
    )
    if not can_retire_tag(tag, request.user):
        raise PermissionDenied("You cannot delete this tag.")
    if request.method == "POST":
        try:
            retire_tag(tag.id, actor=request.user)
        except TaxonomyPermissionError as error:
            raise PermissionDenied(str(error)) from error
        except TaxonomyError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, "The tag was deleted from active use.")
            return redirect(tag.get_absolute_url())
    return render(request, "taxonomy/tag_delete.html", {"tag": tag})


def _algorithm_usage(request, tag):
    query = request.GET.get("q", "").strip()
    skeleton = request.GET.get("skeleton", "").strip()
    priors = request.GET.get("priors", "").strip()
    probability = request.GET.get("probability", "").strip()
    result_min_raw = request.GET.get("result_min", "")
    result_max_raw = request.GET.get("result_max", "")
    result_min = parse_nonnegative_int(result_min_raw)
    result_max = parse_nonnegative_int(result_max_raw)
    include_descendants = include_descendants_from_request(request)
    tag_match = "children" if include_descendants else "any"
    base = public_decoder_catalogue(tag_slugs=(tag.slug,), tag_match=tag_match)
    result_values = list(base.values_list("published_result_count", flat=True))
    queryset = public_decoder_catalogue(
        query=query,
        tag_slugs=(tag.slug,),
        tag_match=tag_match,
        skeleton_preparation=skeleton,
        priors_preparation=priors,
        probability_output=probability,
        result_min=result_min,
        result_max=result_max,
    )
    sort_keys = parse_sort(
        request.GET.get("sort", ""), ALGORITHM_COLUMNS, (("name", "asc"),)
    )
    queryset = apply_sort(
        queryset,
        sort_keys,
        {
            "name": "name",
            "version": "version",
            "skeleton": "circuit_skeleton_preparation",
            "priors": "circuit_priors_preparation",
            "probability": "provides_failure_probability",
            "results": "published_result_count",
            "published": "published_at",
        },
    )
    records = list(queryset)
    table = table_context(request, ALGORITHM_COLUMNS, sort_keys)
    rows = []
    for decoder in records:
        cells = {
            "name": {
                "key": "name",
                "value": decoder.name,
                "url": reverse("decoders:detail", args=[decoder.slug]),
            },
            "version": {"key": "version", "value": decoder.version},
            "skeleton": {
                "key": "skeleton",
                "value": decoder.get_circuit_skeleton_preparation_display(),
            },
            "priors": {
                "key": "priors",
                "value": decoder.get_circuit_priors_preparation_display(),
            },
            "probability": {
                "key": "probability",
                "value": "Yes" if decoder.provides_failure_probability else "No",
            },
            "results": {
                "key": "results",
                "value": decoder.published_result_count,
                "numeric": True,
            },
            "published": {"key": "published", "value": decoder.published_at},
        }
        rows.append(
            {"cells": cells_for_visible_columns(table["visible_column_keys"], cells)}
        )
    grid = filter_grid(
        grid_id=f"tag-{tag.slug}-decoder-filters",
        title="Decoder filters",
        cells=[
            choice_cell(
                key="skeleton",
                label="Skeleton preparation",
                name="skeleton",
                value=skeleton,
                choices=(
                    ("", "Any"),
                    ("not_required", "Not required"),
                    ("required", "Required"),
                ),
            ),
            choice_cell(
                key="priors",
                label="Prior preparation",
                name="priors",
                value=priors,
                choices=(
                    ("", "Any"),
                    ("not_required", "Not required"),
                    ("required", "Required"),
                ),
            ),
            choice_cell(
                key="probability",
                label="Failure probability",
                name="probability",
                value=probability,
                choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
            ),
            range_cell(
                key="result_count",
                label="Published results",
                minimum_name="result_min",
                maximum_name="result_max",
                minimum_value=result_min_raw,
                maximum_value=result_max_raw,
                values=result_values,
                histogram_label="Published results per decoder version",
            ),
        ],
    )
    return _usage_context(
        request,
        tag,
        query=query,
        records=records,
        rows=rows,
        table=table,
        grid=grid,
        label="Decoder versions using this tag",
        empty="No published decoder versions using this tag match these controls.",
        include_descendants=include_descendants,
        descendant_control_label=(
            "Show decoder versions tagged with this tag or any child of it"
        ),
        search_label="Search within these decoder versions",
    )


def _circuit_usage(request, tag):
    include_descendants = include_descendants_from_request(request)
    match = "children" if include_descendants else "any"
    if tag.namespace == Tag.Namespace.CODE:
        scope_arguments = {
            "code_tag_slugs": (f"cb:{tag.id}",),
            "code_tag_match": match,
        }
    else:
        scope_arguments = {
            "experiment_tag_slugs": (tag.slug,),
            "experiment_tag_match": match,
        }
    return circuit_usage_context(
        request,
        scope_arguments=scope_arguments,
        reset_url=tag.get_absolute_url(),
        grid_id=f"tag-{tag.slug}-circuit-filters",
        label="Circuit revisions using this tag",
        empty="No published circuit revisions using this tag match these controls.",
    )


def _usage_context(
    request,
    tag,
    *,
    query,
    records,
    rows,
    table,
    grid,
    label,
    empty,
    include_descendants,
    descendant_control_label,
    search_label,
):
    return {
        "usage_query": query,
        "usage_records": records,
        "usage_rows": rows,
        "usage_grid": grid,
        "usage_label": label,
        "usage_empty": empty,
        "usage_search_label": search_label,
        "usage_search_id": f"tag-{tag.slug}-usage-search",
        "include_descendants": include_descendants,
        "descendant_control_label": descendant_control_label,
        "usage_filters_active": bool(
            query or grid["filtered"] or not include_descendants
        ),
        "usage_reset_url": tag.get_absolute_url(),
        "result_count": len(records),
        "reset_sort_url": url_without(request, "sort"),
        "raw_sort": request.GET.get("sort", ""),
        "raw_columns": request.GET.get("columns", ""),
        **table,
    }
