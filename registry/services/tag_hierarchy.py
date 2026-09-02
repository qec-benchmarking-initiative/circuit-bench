"""Small read-side projections for native and combined tag hierarchies."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from registry.models import (
    EczParent,
    EczTerm,
    Tag,
    TagEczMapping,
    TagEczParent,
    TagParent,
)


def descendant_slug_groups(
    namespace: str,
    selected_slugs: Iterable[str],
) -> tuple[tuple[str, ...], ...]:
    """Expand each selected native tag to itself and its active descendants."""

    selected = tuple(dict.fromkeys(slug for slug in selected_slugs if slug))
    if not selected:
        return ()
    rows = list(
        Tag.objects.filter(
            namespace=namespace,
            status__in=(Tag.Status.CUSTOM, Tag.Status.OFFICIAL),
        ).values_list("id", "slug")
    )
    slug_by_id = dict(rows)
    id_by_slug = {slug: tag_id for tag_id, slug in rows}
    children_by_parent = defaultdict(set)
    for child_id, parent_id in TagParent.objects.filter(
        child_id__in=slug_by_id,
        parent_id__in=slug_by_id,
    ).values_list("child_id", "parent_id"):
        children_by_parent[parent_id].add(child_id)

    groups = []
    for slug in selected:
        root_id = id_by_slug.get(slug)
        if root_id is None:
            groups.append((slug,))
            continue
        descendants = set()
        queue = deque((root_id,))
        while queue:
            tag_id = queue.popleft()
            if tag_id in descendants:
                continue
            descendants.add(tag_id)
            queue.extend(children_by_parent[tag_id])
        groups.append(tuple(sorted(slug_by_id[tag_id] for tag_id in descendants)))
    return tuple(groups)


def inclusive_code_descendant_identities(
    selected_identities: Iterable[str],
) -> tuple[str, ...]:
    """Return selected code identities and every active descendant identity.

    The code taxonomy is one effective directed acyclic graph: native Circuit
    Bench tags, Error Correction Zoo terms, cross-source parent edges, and
    active native-to-ECZ equivalence mappings all participate.  Returned
    identities use the same ``cb:<uuid>`` and ``ecz:<code-id>`` forms accepted
    by the public filter services.
    """

    selected = tuple(dict.fromkeys(value for value in selected_identities if value))
    if not selected:
        return ()

    active_tags = dict(
        Tag.objects.filter(
            namespace=Tag.Namespace.CODE,
            status__in=(Tag.Status.CUSTOM, Tag.Status.OFFICIAL),
        ).values_list("id", "slug")
    )
    tag_id_by_slug = {slug: tag_id for tag_id, slug in active_tags.items()}
    tag_id_by_string = {str(tag_id): tag_id for tag_id in active_tags}
    active_terms = dict(
        EczTerm.objects.filter(status=EczTerm.Status.CURRENT).values_list(
            "id", "ecz_code_id"
        )
    )
    term_id_by_code = {code_id: term_id for term_id, code_id in active_terms.items()}
    term_code_by_string = {
        str(term_id): code_id for term_id, code_id in active_terms.items()
    }
    mapped_term_by_tag = {
        str(tag_id): str(term_id)
        for tag_id, term_id in TagEczMapping.objects.filter(
            status=TagEczMapping.Status.ACTIVE,
            tag_id__in=active_tags,
            ecz_term_id__in=active_terms,
        ).values_list("tag_id", "ecz_term_id")
    }

    def effective(node: str) -> str:
        source, raw_id = node.split(":", 1)
        if source == "cb":
            term_id = mapped_term_by_tag.get(raw_id)
            if term_id is not None:
                return f"ecz:{term_id}"
        return node

    children_by_parent: dict[str, set[str]] = defaultdict(set)

    def add_edge(child: str, parent: str) -> None:
        effective_child = effective(child)
        effective_parent = effective(parent)
        if effective_child != effective_parent:
            children_by_parent[effective_parent].add(effective_child)

    for child_id, parent_id in TagParent.objects.filter(
        child_id__in=active_tags,
        parent_id__in=active_tags,
    ).values_list("child_id", "parent_id"):
        add_edge(f"cb:{child_id}", f"cb:{parent_id}")
    for child_id, parent_id in EczParent.objects.filter(
        child_id__in=active_terms,
        parent_id__in=active_terms,
    ).values_list("child_id", "parent_id"):
        add_edge(f"ecz:{child_id}", f"ecz:{parent_id}")
    for tag_id, term_id in TagEczParent.objects.filter(
        tag_id__in=active_tags,
        ecz_term_id__in=active_terms,
    ).values_list("tag_id", "ecz_term_id"):
        add_edge(f"cb:{tag_id}", f"ecz:{term_id}")

    root_nodes: list[str] = []
    unknown_identities: list[str] = []
    for identity in selected:
        source, separator, value = identity.partition(":")
        node = None
        if separator and source == "cb":
            tag_id = tag_id_by_string.get(value)
            if tag_id is not None:
                node = f"cb:{tag_id}"
        elif separator and source == "ecz":
            term_id = term_id_by_code.get(value)
            if term_id is not None:
                node = f"ecz:{term_id}"
        elif not separator:
            tag_id = tag_id_by_slug.get(identity)
            if tag_id is not None:
                node = f"cb:{tag_id}"
        if node is None:
            unknown_identities.append(identity)
        else:
            root_nodes.append(effective(node))

    included_nodes = set()
    queue = deque(root_nodes)
    while queue:
        node = queue.popleft()
        if node in included_nodes:
            continue
        included_nodes.add(node)
        queue.extend(children_by_parent[node])

    identities = set(unknown_identities)
    for node in included_nodes:
        source, raw_id = node.split(":", 1)
        if source == "cb":
            tag_id = tag_id_by_string.get(raw_id)
            if tag_id is not None:
                identities.add(f"cb:{tag_id}")
        else:
            code_id = term_code_by_string.get(raw_id)
            if code_id is not None:
                identities.add(f"ecz:{code_id}")
    return tuple(sorted(identities))
