from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Account
from registry.models import (
    CircuitCollection,
    CircuitCollectionChild,
    CircuitCollectionCodeTag,
    CircuitCollectionEczTerm,
    CircuitCollectionExperimentTag,
    CircuitCollectionMember,
    CircuitRevision,
    EczTerm,
    RecordEvent,
    Tag,
)
from registry.models.common import LifecycleState, RecordVisibility
from registry.services.histories import append_history_event, history_for_new_record
from registry.services.visibility import actor_visibility_q


class CollectionError(ValidationError):
    pass


def collection_queryset_for(viewer=None):
    queryset = CircuitCollection.objects.all()
    if getattr(viewer, "is_admin", False):
        return queryset
    if getattr(viewer, "is_authenticated", False):
        return queryset.filter(
            Q(visibility=RecordVisibility.PUBLIC) | Q(submitted_by=viewer)
        )
    return queryset.filter(visibility=RecordVisibility.PUBLIC)


def can_curate_collection(actor: Account, collection: CircuitCollection) -> bool:
    return actor.is_active and (
        actor.is_admin or collection.submitted_by_id == actor.id
    )


@transaction.atomic
def create_collection(
    *,
    actor: Account,
    slug: str,
    name: str,
    description: str = "",
    visibility: str = RecordVisibility.PUBLIC,
    code_tags: Iterable[Tag] = (),
    experiment_tags: Iterable[Tag] = (),
    ecz_terms: Iterable[EczTerm] = (),
) -> CircuitCollection:
    if not actor.is_active:
        raise CollectionError("Inactive accounts cannot create collections.")
    code_tags = tuple(code_tags)
    experiment_tags = tuple(experiment_tags)
    _validate_collection_tags(code_tags, experiment_tags)
    history = history_for_new_record("collection")
    collection = CircuitCollection.objects.create(
        history=history,
        slug=slug,
        name=name,
        description=description,
        submitted_by=actor,
        state=LifecycleState.PUBLISHED,
        visibility=visibility,
        published_at=timezone.now(),
    )
    CircuitCollectionCodeTag.objects.bulk_create(
        [CircuitCollectionCodeTag(collection=collection, tag=tag) for tag in code_tags]
    )
    CircuitCollectionExperimentTag.objects.bulk_create(
        [
            CircuitCollectionExperimentTag(collection=collection, tag=tag)
            for tag in experiment_tags
        ]
    )
    CircuitCollectionEczTerm.objects.bulk_create(
        [
            CircuitCollectionEczTerm(collection=collection, ecz_term=term)
            for term in ecz_terms
        ]
    )
    submitted = append_history_event(
        kind="collection",
        record=collection,
        actor=actor,
        action=RecordEvent.Action.SUBMITTED,
        note="Created this circuit collection.",
        details={"projected_state": LifecycleState.PUBLISHED},
        payload_snapshot={
            "schema": {"record_type": "collection", "version": "0.1"},
            "data": collection_payload(collection),
        },
    )
    approved = append_history_event(
        kind="collection",
        record=collection,
        actor_system="collection_policy",
        action=RecordEvent.Action.APPROVED,
        note="Approved automatically under collection policy 0.1.",
        details={"approved_by": "system"},
        caused_by=submitted,
    )
    published = append_history_event(
        kind="collection",
        record=collection,
        actor_system="collection_policy",
        action=RecordEvent.Action.PUBLISHED,
        note="Published automatically under collection policy 0.1.",
        details={"approved_by": "system"},
        caused_by=approved,
    )
    # The history event is the authoritative publication instant.  Use its exact
    # timestamp for the denormalised lifecycle projection so validation cannot
    # drift by the few microseconds between object creation and event append.
    collection.published_at = published.occurred_at
    collection.save(update_fields=["published_at"])
    return collection


@transaction.atomic
def update_collection(
    collection: CircuitCollection,
    *,
    actor: Account,
    slug: str,
    name: str,
    description: str,
    visibility: str,
    code_tags: Iterable[Tag],
    experiment_tags: Iterable[Tag],
    ecz_terms: Iterable[EczTerm],
) -> CircuitCollection:
    collection = CircuitCollection.objects.select_for_update().get(id=collection.id)
    if not can_curate_collection(actor, collection):
        raise PermissionDenied
    code_tags = tuple(code_tags)
    experiment_tags = tuple(experiment_tags)
    _validate_collection_tags(code_tags, experiment_tags)
    previous_visibility = collection.visibility
    collection.slug = slug
    collection.name = name
    collection.description = description
    collection.visibility = visibility
    collection.full_clean(exclude=("history", "submitted_by"))
    collection.save(update_fields=["slug", "name", "description", "visibility"])
    collection.code_tags.set(code_tags)
    collection.experiment_tags.set(experiment_tags)
    collection.ecz_terms.set(tuple(ecz_terms))
    append_history_event(
        kind="collection",
        record=collection,
        actor=actor,
        action=RecordEvent.Action.EDITED,
        note="Updated collection metadata.",
        details={},
        payload_snapshot={
            "schema": {"record_type": "collection", "version": "0.1"},
            "data": collection_payload(collection),
        },
    )
    if previous_visibility != visibility:
        append_history_event(
            kind="collection",
            record=collection,
            actor=actor,
            action=(
                RecordEvent.Action.MADE_PUBLIC
                if visibility == RecordVisibility.PUBLIC
                else RecordEvent.Action.MADE_PRIVATE
            ),
            note=f"Made this collection {visibility}.",
            details={
                "previous_visibility": previous_visibility,
                "visibility": visibility,
            },
        )
    return collection


@transaction.atomic
def set_collection_members(
    collection: CircuitCollection,
    *,
    actor: Account,
    circuit_ids: Iterable,
    child_ids: Iterable,
) -> CircuitCollection:
    collection = CircuitCollection.objects.select_for_update().get(id=collection.id)
    if not can_curate_collection(actor, collection):
        raise PermissionDenied
    circuit_ids = tuple(dict.fromkeys(circuit_ids))
    child_ids = tuple(dict.fromkeys(child_ids))
    eligible_state = Q(state__in=[LifecycleState.PUBLISHED, LifecycleState.WITHDRAWN])
    if actor.is_admin:
        eligible_state = Q(pk__isnull=False)
    else:
        # A contributor may arrange their own not-yet-published circuit in a
        # collection while it awaits review. Other contributors can only add an
        # exact revision once that revision is public and published/withdrawn.
        eligible_state |= Q(submitted_by=actor)
    visible_circuits = (
        CircuitRevision.objects.filter(id__in=circuit_ids)
        .filter(actor_visibility_q(actor))
        .filter(eligible_state)
    )
    circuit_by_id = {item.id: item for item in visible_circuits}
    visible_children = collection_queryset_for(actor).filter(
        id__in=child_ids,
        state=LifecycleState.PUBLISHED,
    )
    child_by_id = {item.id: item for item in visible_children}
    circuits = [
        circuit_by_id[item_id] for item_id in circuit_ids if item_id in circuit_by_id
    ]
    children = [child_by_id[item_id] for item_id in child_ids if item_id in child_by_id]
    if len(circuits) != len(circuit_ids) or len(children) != len(child_ids):
        raise CollectionError("One or more selected records are unavailable.")
    for child in children:
        _assert_acyclic_edge(collection, child)
    _replace_circuit_members(collection, circuits, actor)
    _replace_child_members(collection, children, actor)
    return collection


@transaction.atomic
def set_circuit_collections(
    circuit: CircuitRevision,
    *,
    actor: Account,
    collection_ids: Iterable,
) -> None:
    """Set only memberships controlled by ``actor``; preserve other curators' work."""

    collection_ids = tuple(dict.fromkeys(collection_ids))
    manageable = CircuitCollection.objects.all()
    if not actor.is_admin:
        manageable = manageable.filter(submitted_by=actor)
    desired = list(manageable.filter(id__in=collection_ids).order_by("id"))
    if len(desired) != len(collection_ids):
        raise CollectionError("You may only add circuits to collections you curate.")
    existing = list(
        manageable.filter(
            circuit_memberships__circuit_revision=circuit,
            circuit_memberships__removed_at__isnull=True,
        ).distinct()
    )
    affected = {item.id: item for item in [*desired, *existing]}
    desired_ids = {item.id for item in desired}
    for collection in affected.values():
        circuit_ids = list(
            collection.circuit_memberships.filter(removed_at__isnull=True)
            .order_by("position", "id")
            .values_list("circuit_revision_id", flat=True)
        )
        if collection.id in desired_ids and circuit.id not in circuit_ids:
            circuit_ids.append(circuit.id)
        elif collection.id not in desired_ids:
            circuit_ids = [item for item in circuit_ids if item != circuit.id]
        child_ids = list(
            collection.child_memberships.filter(removed_at__isnull=True)
            .order_by("position", "id")
            .values_list("child_id", flat=True)
        )
        set_collection_members(
            collection,
            actor=actor,
            circuit_ids=circuit_ids,
            child_ids=child_ids,
        )


def descendant_collection_ids(
    collection: CircuitCollection,
    *,
    viewer=None,
    include_self: bool = True,
    include_private: bool = False,
) -> set:
    allowed = (
        CircuitCollection.objects.all()
        if include_private
        else collection_queryset_for(viewer)
    ).values_list("id", flat=True)
    allowed_ids = set(allowed)
    visited = {collection.id} if include_self else set()
    frontier = deque([collection.id])
    while frontier:
        parent_ids = list(frontier)
        frontier.clear()
        child_ids = CircuitCollectionChild.objects.filter(
            collection_id__in=parent_ids,
            removed_at__isnull=True,
            child_id__in=allowed_ids,
        ).values_list("child_id", flat=True)
        for child_id in child_ids:
            if child_id not in visited:
                visited.add(child_id)
                frontier.append(child_id)
    if not include_self:
        visited.discard(collection.id)
    return visited


def collection_circuit_ids(
    collection: CircuitCollection,
    *,
    include_descendants: bool,
    viewer=None,
) -> set:
    collection_ids = (
        descendant_collection_ids(collection, viewer=viewer)
        if include_descendants
        else {collection.id}
    )
    return set(
        CircuitCollectionMember.objects.filter(
            collection_id__in=collection_ids,
            removed_at__isnull=True,
        ).values_list("circuit_revision_id", flat=True)
    )


def collection_payload(collection: CircuitCollection) -> dict:
    return {
        "slug": collection.slug,
        "name": collection.name,
        "description": collection.description,
        "visibility": collection.visibility,
        "code_tags": [
            str(value)
            for value in collection.code_tags.order_by("id").values_list(
                "id", flat=True
            )
        ],
        "ecz_terms": [
            str(value)
            for value in collection.ecz_terms.order_by("id").values_list(
                "id", flat=True
            )
        ],
        "experiment_tags": [
            str(value)
            for value in collection.experiment_tags.order_by("id").values_list(
                "id", flat=True
            )
        ],
    }


def _validate_collection_tags(code_tags, experiment_tags):
    if any(tag.namespace != Tag.Namespace.CODE for tag in code_tags):
        raise CollectionError("Collection code tags must use the code namespace.")
    if any(tag.namespace != Tag.Namespace.EXPERIMENT for tag in experiment_tags):
        raise CollectionError(
            "Collection experiment tags must use the experiment namespace."
        )


def _assert_acyclic_edge(collection, child):
    if collection.id == child.id:
        raise CollectionError("A collection cannot contain itself.")
    if collection.id in descendant_collection_ids(
        child, viewer=None, include_private=True
    ):
        raise CollectionError("That subcollection would create a cycle.")


def _replace_circuit_members(collection, circuits, actor):
    desired = {item.id: position for position, item in enumerate(circuits, 1)}
    existing = {
        item.circuit_revision_id: item
        for item in collection.circuit_memberships.select_for_update()
    }
    active = [item for item in existing.values() if item.removed_at is None]
    for offset, membership in enumerate(active, 1):
        membership.position = len(existing) + len(circuits) + offset
        membership.save(update_fields=["position"])
    for circuit_id, membership in existing.items():
        if circuit_id in desired:
            was_removed = membership.removed_at is not None
            membership.position = desired[circuit_id]
            membership.removed_by = None
            membership.removed_at = None
            membership.save(update_fields=["position", "removed_by", "removed_at"])
            if was_removed:
                append_history_event(
                    kind="collection",
                    record=collection,
                    actor=actor,
                    action=RecordEvent.Action.MEMBER_ADDED,
                    note=f"Added circuit {membership.circuit_revision}.",
                    details={"circuit_revision_id": str(circuit_id)},
                )
        elif membership.removed_at is None:
            membership.removed_by = actor
            membership.removed_at = timezone.now()
            membership.save(update_fields=["removed_by", "removed_at"])
            append_history_event(
                kind="collection",
                record=collection,
                actor=actor,
                action=RecordEvent.Action.MEMBER_REMOVED,
                note=f"Removed circuit {membership.circuit_revision}.",
                details={"circuit_revision_id": str(circuit_id)},
            )
    for circuit in circuits:
        if circuit.id not in existing:
            CircuitCollectionMember.objects.create(
                collection=collection,
                circuit_revision=circuit,
                position=desired[circuit.id],
                added_by=actor,
            )
            append_history_event(
                kind="collection",
                record=collection,
                actor=actor,
                action=RecordEvent.Action.MEMBER_ADDED,
                note=f"Added circuit {circuit}.",
                details={"circuit_revision_id": str(circuit.id)},
            )


def _replace_child_members(collection, children, actor):
    desired = {item.id: position for position, item in enumerate(children, 1)}
    existing = {
        item.child_id: item for item in collection.child_memberships.select_for_update()
    }
    active = [item for item in existing.values() if item.removed_at is None]
    for offset, membership in enumerate(active, 1):
        membership.position = len(existing) + len(children) + offset
        membership.save(update_fields=["position"])
    for child_id, membership in existing.items():
        if child_id in desired:
            was_removed = membership.removed_at is not None
            membership.position = desired[child_id]
            membership.removed_by = None
            membership.removed_at = None
            membership.save(update_fields=["position", "removed_by", "removed_at"])
            if was_removed:
                append_history_event(
                    kind="collection",
                    record=collection,
                    actor=actor,
                    action=RecordEvent.Action.CHILD_ADDED,
                    note=f"Added subcollection {membership.child}.",
                    details={"child_collection_id": str(child_id)},
                )
        elif membership.removed_at is None:
            membership.removed_by = actor
            membership.removed_at = timezone.now()
            membership.save(update_fields=["removed_by", "removed_at"])
            append_history_event(
                kind="collection",
                record=collection,
                actor=actor,
                action=RecordEvent.Action.CHILD_REMOVED,
                note=f"Removed subcollection {membership.child}.",
                details={"child_collection_id": str(child_id)},
            )
    for child in children:
        if child.id not in existing:
            CircuitCollectionChild.objects.create(
                collection=collection,
                child=child,
                position=desired[child.id],
                added_by=actor,
            )
            append_history_event(
                kind="collection",
                record=collection,
                actor=actor,
                action=RecordEvent.Action.CHILD_ADDED,
                note=f"Added subcollection {child}.",
                details={"child_collection_id": str(child.id)},
            )
