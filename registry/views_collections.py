from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from registry.filter_grids import algorithm_grid as build_algorithm_grid
from registry.filter_grids import circuit_grid as build_circuit_grid
from registry.filter_grids import machine_grid as build_machine_grid
from registry.filter_grids import related_records_cell
from registry.forms_collections import (
    CircuitCollectionForm,
    CircuitCollectionMembershipForm,
)
from registry.models import CircuitCollection, CircuitRevision, Machine, Tag
from registry.models.common import LifecycleState
from registry.record_pickers import record_picker_context
from registry.result_comparison import (
    api_parameters_from_request,
    result_comparison_context,
)
from registry.result_request import result_filter_state
from registry.result_tables import result_cell_map
from registry.services.collections import (
    CollectionError,
    can_curate_collection,
    collection_circuit_ids,
    collection_queryset_for,
    create_collection,
    descendant_collection_ids,
    set_collection_members,
    update_collection,
)
from registry.services.decoders import catalogue_algorithm_tags
from registry.services.filter_options import public_circuit_filter_options
from registry.services.histories import history_view
from registry.services.results import public_result_catalogue
from registry.services.visibility import actor_visibility_q
from registry.table_controls import cells_for_visible_columns
from registry.views_results import RESULT_COLUMNS


@require_GET
def collection_list(request):
    query = request.GET.get("q", "").strip()
    collections = collection_queryset_for(request.user).filter(
        state__in=[LifecycleState.PUBLISHED, LifecycleState.WITHDRAWN]
    )
    if query:
        matching_tag_ids = (
            Tag.objects.filter(actor_visibility_q(request.user))
            .filter(Q(label__icontains=query) | Q(aliases__alias__icontains=query))
            .values("id")
        )
        collections = collections.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(description__icontains=query)
            | Q(submitted_by__display_name__icontains=query)
            | Q(code_tags__id__in=matching_tag_ids)
            | Q(ecz_terms__display_name__icontains=query)
            | Q(experiment_tags__id__in=matching_tag_ids)
        )
        collections = collections.distinct()
    collections = (
        collections.select_related("submitted_by")
        .prefetch_related(
            Prefetch(
                "code_tags",
                queryset=Tag.objects.filter(actor_visibility_q(request.user)),
                to_attr="display_code_tags",
            ),
            "ecz_terms",
            Prefetch(
                "experiment_tags",
                queryset=Tag.objects.filter(actor_visibility_q(request.user)),
                to_attr="display_experiment_tags",
            ),
        )
        .annotate(
            direct_circuit_count=Count(
                "circuit_memberships",
                filter=Q(circuit_memberships__removed_at__isnull=True),
                distinct=True,
            ),
            direct_child_count=Count(
                "child_memberships",
                filter=Q(child_memberships__removed_at__isnull=True),
                distinct=True,
            ),
        )
        .order_by("name", "id")
    )
    return render(
        request,
        "collections/list.html",
        {"collections": collections, "query": query},
    )


@login_required
@require_http_methods(["GET", "POST"])
def collection_create(request):
    form = CircuitCollectionForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        collection = create_collection(
            actor=request.user,
            slug=form.cleaned_data["slug"],
            name=form.cleaned_data["name"],
            description=form.cleaned_data["description"],
            visibility=form.cleaned_data["visibility"],
            code_tags=form.cleaned_data["code_tags"],
            ecz_terms=form.cleaned_data["ecz_terms"],
            experiment_tags=form.cleaned_data["experiment_tags"],
        )
        messages.success(request, "Circuit collection created.")
        return redirect("collections:members", slug=collection.slug)
    return render(
        request,
        "collections/form.html",
        {
            "form": form,
            "operation": "create",
            "collection": None,
            **_collection_tag_pickers(form, "create"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def collection_edit(request, slug):
    collection = get_object_or_404(CircuitCollection, slug=slug)
    if not can_curate_collection(request.user, collection):
        raise PermissionDenied
    form = CircuitCollectionForm(
        request.POST or None,
        actor=request.user,
        instance=collection,
    )
    if request.method == "POST" and form.is_valid():
        old_slug = collection.slug
        collection = update_collection(
            collection,
            actor=request.user,
            slug=form.cleaned_data["slug"],
            name=form.cleaned_data["name"],
            description=form.cleaned_data["description"],
            visibility=form.cleaned_data["visibility"],
            code_tags=form.cleaned_data["code_tags"],
            ecz_terms=form.cleaned_data["ecz_terms"],
            experiment_tags=form.cleaned_data["experiment_tags"],
        )
        messages.success(request, "Circuit collection updated.")
        if old_slug != collection.slug:
            return redirect("collections:edit", slug=collection.slug)
        return redirect("collections:detail", slug=collection.slug)
    return render(
        request,
        "collections/form.html",
        {
            "form": form,
            "operation": "edit",
            "collection": collection,
            **_collection_tag_pickers(form, "edit"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def collection_members(request, slug):
    collection = get_object_or_404(CircuitCollection, slug=slug)
    if not can_curate_collection(request.user, collection):
        raise PermissionDenied
    form = CircuitCollectionMembershipForm(
        request.POST or None,
        actor=request.user,
        instance=collection,
    )
    if request.method == "POST" and form.is_valid():
        try:
            set_collection_members(
                collection,
                actor=request.user,
                circuit_ids=[item.id for item in form.cleaned_data["circuits"]],
                child_ids=[item.id for item in form.cleaned_data["child_collections"]],
            )
        except CollectionError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Collection contents updated.")
            return redirect("collections:detail", slug=collection.slug)
    return render(
        request,
        "collections/members.html",
        {
            "form": form,
            "collection": collection,
            "circuit_picker": _membership_picker_cell(
                form,
                field_name="circuits",
                picker_key="collection-circuits",
                label="Circuits",
            ),
            "collection_picker": _membership_picker_cell(
                form,
                field_name="child_collections",
                picker_key="circuit-collections",
                label="Subcollections",
            ),
        },
    )


@require_GET
def collection_detail(request, slug):
    collection = get_object_or_404(
        collection_queryset_for(request.user)
        .select_related("submitted_by", "history")
        .prefetch_related(
            Prefetch(
                "code_tags",
                queryset=Tag.objects.filter(actor_visibility_q(request.user)),
                to_attr="display_code_tags",
            ),
            "ecz_terms",
            Prefetch(
                "experiment_tags",
                queryset=Tag.objects.filter(actor_visibility_q(request.user)),
                to_attr="display_experiment_tags",
            ),
        ),
        slug=slug,
        state__in=[LifecycleState.PUBLISHED, LifecycleState.WITHDRAWN],
    )
    include_descendants = request.GET.get("include_descendants", "1") not in {
        "0",
        "false",
        "no",
    }
    collection_ids = descendant_collection_ids(collection, viewer=request.user)
    circuit_ids = collection_circuit_ids(
        collection,
        include_descendants=include_descendants,
        viewer=request.user,
    )
    all_tree_circuit_ids = collection_circuit_ids(
        collection,
        include_descendants=True,
        viewer=request.user,
    )
    visible_tree_circuits = CircuitRevision.objects.filter(
        id__in=all_tree_circuit_ids
    ).filter(actor_visibility_q(request.user))
    circuit_visibility_summary = visible_tree_circuits.aggregate(
        total=Count("id"),
        public=Count("id", filter=Q(visibility="public")),
        private=Count("id", filter=Q(visibility="private")),
        withdrawn=Count("id", filter=Q(state=LifecycleState.WITHDRAWN)),
    )
    direct_children = (
        CircuitCollection.objects.filter(
            parent_memberships__collection=collection,
            parent_memberships__removed_at__isnull=True,
        )
        .filter(actor_visibility_q(request.user))
        .select_related("submitted_by")
        .order_by("parent_memberships__position", "id")
    )
    direct_memberships = list(
        collection.circuit_memberships.filter(
            actor_visibility_q(request.user, "circuit_revision__"),
            circuit_revision__state__in=[
                LifecycleState.PUBLISHED,
                LifecycleState.WITHDRAWN,
            ],
            removed_at__isnull=True,
        )
        .select_related("circuit_revision", "circuit_revision__noise_model")
        .select_related("circuit_revision__submitted_by")
        .order_by("position", "id")
    )
    can_bulk_administer = bool(
        request.user.is_authenticated
        and any(
            request.user.is_admin
            or membership.circuit_revision.submitted_by_id == request.user.id
            for membership in direct_memberships
        )
    )
    filter_state = result_filter_state(request.GET)
    filters = filter_state.service_arguments
    noise_model_picker = record_picker_context(
        "noise-models", filters["noise_model_slugs"]
    )
    filters["noise_model_slugs"] = tuple(
        record["identifier"] for record in noise_model_picker["selected_records"]
    )
    results_queryset = public_result_catalogue(**filters, viewer=request.user).filter(
        circuit_revision_id__in=circuit_ids
    )
    comparison = result_comparison_context(
        request,
        queryset=results_queryset,
        columns=RESULT_COLUMNS,
        default_sort=(("published", "desc"),),
        plot_id=f"collection-{collection.id}-results",
        point_context="results",
        api_parameters=api_parameters_from_request(
            request.GET,
            overrides=(
                ("scope_collection", collection.slug),
                (
                    "include_descendants",
                    "true" if include_descendants else "false",
                ),
            ),
        ),
    )
    rows = [
        {
            "cells": cells_for_visible_columns(
                comparison["visible_column_keys"],
                result_cell_map(result, filter_url=request.path),
            )
        }
        for result in comparison["results"]
    ]
    algorithm_tags = filters["algorithm_tag_slugs"]
    code_tags = filters["code_tag_slugs"]
    experiment_tags = filters["experiment_tag_slugs"]
    circuit_options = public_circuit_filter_options()
    filters_active = bool(
        filters["query"]
        or algorithm_tags
        or filters["skeleton_preparation"]
        or filters["decoder_priors_preparation"]
        or filters["probability_output"]
        or code_tags
        or experiment_tags
        or filters["noise_model_slugs"]
        or filters["randomises_priors"]
        or filters["is_css"]
        or filters["machine_class"]
        or any(value is not None for value in filter_state.parsed_ranges.values())
        or comparison["scripted_query_active"]
        or not include_descendants
    )
    return render(
        request,
        "collections/detail.html",
        {
            "collection": collection,
            "direct_children": direct_children,
            "direct_memberships": direct_memberships,
            "descendant_count": max(0, len(collection_ids) - 1),
            "circuit_visibility_summary": circuit_visibility_summary,
            "include_descendants": include_descendants,
            "can_curate": can_curate_collection(request.user, collection)
            if request.user.is_authenticated
            else False,
            "can_bulk_administer": can_bulk_administer,
            "result_rows": rows,
            "query": filters["query"],
            "filters_active": filters_active,
            "algorithm_filter_grid": build_algorithm_grid(
                grid_id="collection-algorithm-filters",
                picker_id="collection-algorithm-tags",
                tags=list(catalogue_algorithm_tags()),
                selected_tags=algorithm_tags,
                tag_match=filters["algorithm_tag_match"],
                skeleton=filters["skeleton_preparation"],
                priors=filters["decoder_priors_preparation"],
                probability=filters["probability_output"],
                tag_name="algorithm_tag",
                tag_match_name="algorithm_tag_match",
                priors_name="decoder_priors",
            ),
            "circuit_filter_grid": build_circuit_grid(
                grid_id="collection-circuit-filters",
                code_tags=circuit_options["code_tags"],
                selected_code_tags=code_tags,
                code_tag_match=filters["code_tag_match"],
                experiment_tags=circuit_options["experiment_tags"],
                selected_experiment_tags=experiment_tags,
                experiment_tag_match=filters["experiment_tag_match"],
                noise_model_picker=noise_model_picker,
                randomises_priors=filters["randomises_priors"],
                is_css=filters["is_css"],
                raw_values=filter_state.raw_ranges,
                distributions=circuit_options["distributions"],
                priors_name="circuit_priors",
            ),
            "machine_filter_grid": build_machine_grid(
                grid_id="collection-machine-filters",
                machine_classes=Machine.MachineClass.choices,
                selected_machine_class=filters["machine_class"],
            ),
            "history": history_view("collection", collection, request.user),
            **comparison,
        },
    )


def collection_or_404_for_scope(raw, viewer=None):
    collection = (
        collection_queryset_for(viewer)
        .filter(Q(slug=raw) | Q(id=raw) if _looks_like_uuid(raw) else Q(slug=raw))
        .first()
    )
    if collection is None:
        raise Http404("Circuit collection not found")
    return collection


def _looks_like_uuid(value):
    try:
        import uuid

        uuid.UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True


def _collection_tag_pickers(form, operation):
    def picker(field_name, namespace, *, ecz_field_name=None):
        bound = form[field_name]
        selected = _bound_values(bound.value())
        tags = list(
            bound.field.queryset.filter(id__in=selected).order_by("label", "id")
        )
        for tag in tags:
            tag.picker_key = str(tag.id)
        output = {
            "picker_id": f"collection-{operation}-{field_name}",
            "label": bound.label,
            "input_name": bound.html_name,
            "tags": tags,
            "selected_keys": selected,
            "tag_namespace": namespace,
            "errors": bound.errors,
        }
        if ecz_field_name:
            ecz_bound = form[ecz_field_name]
            ecz_values = _bound_values(ecz_bound.value())
            output.update(
                selected_ecz_terms=list(
                    ecz_bound.field.queryset.filter(id__in=ecz_values)
                ),
                ecz_input_name=ecz_bound.html_name,
                errors=(*bound.errors, *ecz_bound.errors),
            )
        return output

    return {
        "code_tag_picker": picker("code_tags", "code", ecz_field_name="ecz_terms"),
        "experiment_tag_picker": picker("experiment_tags", "experiment"),
    }


def _membership_picker_cell(form, *, field_name, picker_key, label):
    bound = form[field_name]
    picker = record_picker_context(
        picker_key,
        _bound_values(bound.value()),
        input_name=bound.html_name,
        records=bound.field.queryset,
    )
    if field_name == "child_collections":
        picker["search_url"] = f"{picker['search_url']}?exclude={form.instance.id}"
    cell = related_records_cell(
        key=f"collection-members-{field_name}",
        label=label,
        picker_id=f"collection-members-{field_name}-picker",
        picker=picker,
    )
    cell.update(
        empty_label=(
            "No circuits selected"
            if field_name == "circuits"
            else "No subcollections selected"
        ),
        maximum_selections=0,
        required=False,
        disabled=False,
        hide_label=True,
    )
    if not cell["selected_records"]:
        cell["display_value"] = cell["empty_label"]
        cell["selection_label"] = cell["empty_label"]
    return cell


def _bound_values(value):
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),)
