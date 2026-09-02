"""Bounded read model for the replaceable local tag-taxonomy graph component."""

from __future__ import annotations

from django.db.models import Q

from registry.models import Tag, TagParent


def build_local_tag_graph(tag: Tag) -> dict:
    """Describe the current tag, its direct neighbours, and boundary relations.

    The payload deliberately contains generic layered nodes, directed edges, and
    boundary counts. A future expanded taxonomy view can feed the same renderer
    a larger set without changing tag workflow or detail-page code.
    """

    parent_ids = set(tag.parents.values_list("id", flat=True))
    child_ids = set(tag.children.values_list("id", flat=True))
    displayed_ids = {tag.id, *parent_ids, *child_ids}
    displayed_tags = {
        item.id: item
        for item in Tag.objects.filter(id__in=displayed_ids).order_by("label", "id")
    }
    related_edges = list(
        TagParent.objects.filter(
            Q(child_id__in=displayed_ids) | Q(parent_id__in=displayed_ids)
        )
        .order_by("child_id", "parent_id")
        .values_list("child_id", "parent_id")
    )
    visible_edges = [
        {"child": str(child_id), "parent": str(parent_id)}
        for child_id, parent_id in related_edges
        if child_id in displayed_ids and parent_id in displayed_ids
    ]
    hidden_parent_counts = {item_id: 0 for item_id in displayed_ids}
    hidden_child_counts = {item_id: 0 for item_id in displayed_ids}
    for child_id, parent_id in related_edges:
        if child_id in displayed_ids and parent_id not in displayed_ids:
            hidden_parent_counts[child_id] += 1
        if parent_id in displayed_ids and child_id not in displayed_ids:
            hidden_child_counts[parent_id] += 1

    def node_payload(item_id, layer):
        item = displayed_tags[item_id]
        return {
            "id": str(item.id),
            "label": item.label,
            "url": item.get_absolute_url(),
            "layer": layer,
            "status": item.status,
            "deleted": item.status == Tag.Status.RETIRED,
            "colour": item.display_color if item.status == Tag.Status.OFFICIAL else "",
            "hidden_parent_count": hidden_parent_counts[item_id],
            "hidden_child_count": hidden_child_counts[item_id],
        }

    ordered_parents = sorted(
        parent_ids,
        key=lambda item_id: (displayed_tags[item_id].label.casefold(), item_id),
    )
    ordered_children = sorted(
        child_ids,
        key=lambda item_id: (displayed_tags[item_id].label.casefold(), item_id),
    )
    nodes = [node_payload(item_id, "parent") for item_id in ordered_parents]
    nodes.append(node_payload(tag.id, "current"))
    nodes.extend(node_payload(item_id, "child") for item_id in ordered_children)
    relationship_count = len(visible_edges)
    return {
        "id": f"tag-taxonomy-{tag.id}",
        "data_id": f"tag-taxonomy-{tag.id}-data",
        "is_trivial": not parent_ids and not child_ids,
        "open_by_default": bool(parent_ids or child_ids),
        "relationship_count": relationship_count,
        "payload": {
            "version": 1,
            "scope": "local",
            "focus": str(tag.id),
            "nodes": nodes,
            "edges": visible_edges,
        },
    }
