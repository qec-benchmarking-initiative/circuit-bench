"""Bounded read model for the replaceable local tag-taxonomy graph component."""

from __future__ import annotations

from django.db.models import Q

from registry.models import EczParent, EczTerm, Tag, TagEczParent, TagParent


def build_local_tag_graph(tag: Tag) -> dict:
    """Describe the current tag, its direct neighbours, and boundary relations.

    The payload deliberately contains generic layered nodes, directed edges, and
    boundary counts. A future expanded taxonomy view can feed the same renderer
    a larger set without changing tag workflow or detail-page code.
    """

    parent_ids = set(tag.parents.values_list("id", flat=True))
    ecz_parent_ids = set(tag.ecz_parents.values_list("id", flat=True))
    child_ids = set(tag.children.values_list("id", flat=True))
    displayed_ids = {tag.id, *parent_ids, *child_ids}
    displayed_tags = {
        item.id: item
        for item in Tag.objects.filter(id__in=displayed_ids).order_by("label", "id")
    }
    displayed_ecz_terms = {
        item.id: item
        for item in EczTerm.objects.filter(id__in=ecz_parent_ids).order_by(
            "display_name", "ecz_code_id"
        )
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
    visible_edges.extend(
        {"child": str(tag.id), "parent": f"ecz:{term.ecz_code_id}"}
        for term in displayed_ecz_terms.values()
    )
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
    nodes.extend(
        {
            "id": f"ecz:{item.ecz_code_id}",
            "label": f"{item.display_name} (ECZ)",
            "url": item.get_absolute_url(),
            "layer": "parent",
            "status": item.status,
            "source": "ecz",
            "deleted": item.status == EczTerm.Status.RETIRED,
            "colour": "",
            "hidden_parent_count": item.parents.count(),
            "hidden_child_count": max(
                0,
                item.children.count()
                + TagEczParent.objects.filter(ecz_term=item).count()
                - 1,
            ),
        }
        for item in displayed_ecz_terms.values()
    )
    nodes.append(node_payload(tag.id, "current"))
    nodes.extend(node_payload(item_id, "child") for item_id in ordered_children)
    relationship_count = len(visible_edges)
    return {
        "id": f"tag-taxonomy-{tag.id}",
        "data_id": f"tag-taxonomy-{tag.id}-data",
        "is_trivial": not parent_ids and not ecz_parent_ids and not child_ids,
        "open_by_default": bool(parent_ids or ecz_parent_ids or child_ids),
        "relationship_count": relationship_count,
        "payload": {
            "version": 1,
            "scope": "local",
            "focus": str(tag.id),
            "nodes": nodes,
            "edges": visible_edges,
        },
    }


def build_ecz_term_graph(term: EczTerm) -> dict:
    """Build a bounded local graph around one imported ECZ identity."""

    parent_ids = set(term.parents.values_list("id", flat=True))
    child_ids = set(term.children.values_list("id", flat=True))
    native_children = list(
        Tag.objects.filter(ecz_parent_memberships__ecz_term=term)
        .order_by("label", "id")
        .distinct()
    )
    displayed_ecz_ids = {term.id, *parent_ids, *child_ids}
    displayed_terms = {
        item.id: item
        for item in EczTerm.objects.filter(id__in=displayed_ecz_ids).order_by(
            "display_name", "ecz_code_id"
        )
    }
    imported_edges = list(
        EczParent.objects.filter(
            Q(child_id__in=displayed_ecz_ids) | Q(parent_id__in=displayed_ecz_ids)
        ).values_list("child_id", "parent_id")
    )
    visible_edges = [
        {
            "child": f"ecz:{displayed_terms[child_id].ecz_code_id}",
            "parent": f"ecz:{displayed_terms[parent_id].ecz_code_id}",
            "source": "ecz",
        }
        for child_id, parent_id in imported_edges
        if child_id in displayed_ecz_ids and parent_id in displayed_ecz_ids
    ]
    visible_edges.extend(
        {"child": f"cb:{tag.id}", "parent": f"ecz:{term.id}"} for tag in native_children
    )
    hidden_parent_counts = {item_id: 0 for item_id in displayed_ecz_ids}
    hidden_child_counts = {item_id: 0 for item_id in displayed_ecz_ids}
    for child_id, parent_id in imported_edges:
        if child_id in displayed_ecz_ids and parent_id not in displayed_ecz_ids:
            hidden_parent_counts[child_id] += 1
        if parent_id in displayed_ecz_ids and child_id not in displayed_ecz_ids:
            hidden_child_counts[parent_id] += 1

    def ecz_node(item_id, layer):
        item = displayed_terms[item_id]
        return {
            "id": f"ecz:{item.ecz_code_id}",
            "label": f"{item.display_name} (ECZ)",
            "url": item.get_absolute_url(),
            "layer": layer,
            "status": item.status,
            "source": "ecz",
            "deleted": item.status == EczTerm.Status.RETIRED,
            "colour": "",
            "hidden_parent_count": hidden_parent_counts[item_id],
            "hidden_child_count": hidden_child_counts[item_id],
        }

    nodes = [
        ecz_node(item_id, "parent")
        for item_id in sorted(
            parent_ids,
            key=lambda item_id: (
                displayed_terms[item_id].display_name.casefold(),
                item_id,
            ),
        )
    ]
    nodes.append(ecz_node(term.id, "current"))
    nodes.extend(
        ecz_node(item_id, "child")
        for item_id in sorted(
            child_ids,
            key=lambda item_id: (
                displayed_terms[item_id].display_name.casefold(),
                item_id,
            ),
        )
    )
    for tag in native_children:
        nodes.append(
            {
                "id": f"cb:{tag.id}",
                "label": tag.label,
                "url": tag.get_absolute_url(),
                "layer": "child",
                "status": tag.status,
                "source": "circuit_bench",
                "deleted": tag.status == Tag.Status.RETIRED,
                "colour": (
                    tag.display_color if tag.status == Tag.Status.OFFICIAL else ""
                ),
                "hidden_parent_count": (
                    TagParent.objects.filter(child=tag).count()
                    + TagEczParent.objects.filter(tag=tag)
                    .exclude(ecz_term=term)
                    .count()
                ),
                "hidden_child_count": TagParent.objects.filter(parent=tag).count(),
            }
        )
    relationships = len(visible_edges)
    return {
        "id": f"ecz-taxonomy-{term.ecz_code_id}",
        "data_id": f"ecz-taxonomy-{term.ecz_code_id}-data",
        "title": "Combined local graph",
        "is_trivial": not relationships,
        "open_by_default": bool(relationships),
        "relationship_count": relationships,
        "payload": {
            "version": 1,
            "scope": "local",
            "focus": f"ecz:{term.ecz_code_id}",
            "nodes": nodes,
            "edges": visible_edges,
        },
    }
