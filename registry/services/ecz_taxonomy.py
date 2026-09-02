from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import connection, transaction
from django.utils import timezone

from accounts.models import Account
from registry.models import (
    EczParent,
    EczTerm,
    Tag,
    TagEczMapping,
    TagEczParent,
    TagParent,
)
from registry.services.taxonomy import can_edit_tag

ECZ_TAXONOMY_ADVISORY_LOCK_ID = 0x43425245435A4752


class EczTaxonomyError(ValueError):
    """A combined-taxonomy operation would violate policy or graph integrity."""


class EczTaxonomyPermissionError(EczTaxonomyError, PermissionError):
    """The actor cannot curate the requested relationship."""


@dataclass(frozen=True)
class TaxonomyTermDisplay:
    key: str
    source: str
    label: str
    url: str
    selectable: bool
    selected: bool
    status: str
    colour: str
    border_style: str
    namespace: str
    source_suffix: str = ""
    aliases: tuple[str, ...] = ()
    database_id: str = ""
    slug: str = ""
    matched_alias: str = ""

    @property
    def picker_key(self) -> str:
        return self.key


def display_native_tag(tag: Tag, *, selected: bool = False) -> TaxonomyTermDisplay:
    aliases = tuple(
        item.alias
        for item in getattr(tag, "display_aliases", ())
        if getattr(item, "is_active", True)
    )
    return TaxonomyTermDisplay(
        key=f"cb:{tag.id}",
        source="circuit_bench",
        label=tag.label,
        url=tag.get_absolute_url(),
        selectable=tag.status not in (Tag.Status.DEPRECATED, Tag.Status.RETIRED),
        selected=selected,
        status=tag.status,
        colour=tag.display_color or "",
        border_style="solid",
        namespace=tag.namespace,
        aliases=aliases,
        database_id=str(tag.id),
        slug=tag.slug,
    )


def display_ecz_term(term: EczTerm, *, selected: bool = False) -> TaxonomyTermDisplay:
    return TaxonomyTermDisplay(
        key=f"ecz:{term.ecz_code_id}",
        source="ecz",
        label=term.display_name,
        url=term.get_absolute_url(),
        selectable=term.status == EczTerm.Status.CURRENT,
        selected=selected,
        status=term.status,
        colour="ecz",
        border_style="dashed",
        namespace=Tag.Namespace.CODE,
        source_suffix="(ECZ)",
        database_id=str(term.id),
    )


def circuit_code_taxonomy(circuit) -> tuple[TaxonomyTermDisplay, ...]:
    """Return canonical code identities for one prefetched circuit revision."""

    native_tags = getattr(circuit, "display_code_tags", None)
    if native_tags is None:
        native_tags = list(circuit.code_tags.all())
    direct_terms = getattr(circuit, "display_ecz_terms", None)
    if direct_terms is None:
        direct_terms = list(circuit.ecz_terms.all())

    displays: dict[str, TaxonomyTermDisplay] = {}
    for tag in native_tags:
        mappings = getattr(tag, "active_ecz_mappings", None)
        if mappings is None:
            mappings = list(
                tag.ecz_mappings.filter(status=TagEczMapping.Status.ACTIVE)
                .select_related("ecz_term")
                .order_by("mapped_at", "id")
            )
        if mappings:
            term = mappings[-1].ecz_term
            displays[f"ecz:{term.ecz_code_id}"] = display_ecz_term(term)
        else:
            native = display_native_tag(tag)
            displays[native.key] = native
    for term in direct_terms:
        displays[f"ecz:{term.ecz_code_id}"] = display_ecz_term(term)
    return tuple(
        sorted(displays.values(), key=lambda item: (item.label.casefold(), item.key))
    )


def taxonomy_display_dict(item: TaxonomyTermDisplay) -> dict[str, str]:
    return {
        "label": item.label,
        "url": item.url,
        "source": item.source,
        "status": item.status,
        "display_color": item.colour if item.source == "circuit_bench" else "",
    }


def parse_taxonomy_key(key: str) -> tuple[str, str]:
    source, separator, identity = key.partition(":")
    if not separator or source not in {"cb", "ecz"} or not identity:
        raise EczTaxonomyError("Invalid taxonomy-term identity.")
    return source, identity


@transaction.atomic
def set_tag_ecz_parents(
    tag_id,
    *,
    actor: Account,
    ecz_terms: Iterable[EczTerm | str],
) -> Tag:
    _acquire_combined_graph_lock()
    tag = Tag.objects.select_for_update().get(id=tag_id)
    if not can_edit_tag(tag, actor):
        raise EczTaxonomyPermissionError("You cannot edit this tag.")
    if tag.namespace != Tag.Namespace.CODE:
        raise EczTaxonomyError("Only code tags can have ECZ parent terms.")
    requested_ids = _normalise_ecz_term_ids(ecz_terms)
    current_ids = set(
        TagEczParent.objects.filter(tag=tag).values_list("ecz_term_id", flat=True)
    )
    allowed_terms = {
        term.id: term
        for term in EczTerm.objects.select_for_update().filter(
            id__in=requested_ids,
            status=EczTerm.Status.CURRENT,
        )
    }
    missing_new = set(requested_ids) - set(allowed_terms) - current_ids
    if missing_new:
        raise EczTaxonomyError("New ECZ parents must be current imported terms.")
    proposed_edges = _combined_edges(
        cross_override=(tag.id, set(requested_ids)),
    )
    _assert_effective_acyclic(proposed_edges, _active_mapping_pairs())
    TagEczParent.objects.filter(tag=tag).exclude(ecz_term_id__in=requested_ids).delete()
    TagEczParent.objects.bulk_create(
        TagEczParent(tag=tag, ecz_term_id=term_id)
        for term_id in requested_ids
        if term_id not in current_ids
    )
    return tag


@transaction.atomic
def create_tag_ecz_mapping(
    *,
    tag_id,
    ecz_term_id,
    actor: Account,
    note: str,
) -> TagEczMapping:
    _require_admin(actor)
    note = note.strip()
    if not note:
        raise EczTaxonomyError("A mapping rationale is required.")
    _acquire_combined_graph_lock()
    tag = Tag.objects.select_for_update().get(id=tag_id)
    term = EczTerm.objects.select_for_update().get(id=ecz_term_id)
    if tag.namespace != Tag.Namespace.CODE:
        raise EczTaxonomyError("Only code tags can map to ECZ terms.")
    if tag.status == Tag.Status.RETIRED:
        raise EczTaxonomyError("A deleted tag cannot acquire a mapping.")
    if term.status != EczTerm.Status.CURRENT:
        raise EczTaxonomyError("A new mapping target must be current in ECZ.")
    if (
        TagEczMapping.objects.select_for_update()
        .filter(
            tag=tag,
            status=TagEczMapping.Status.ACTIVE,
        )
        .exists()
    ):
        raise EczTaxonomyError("This tag already has an active ECZ mapping.")
    mappings = _active_mapping_pairs()
    mappings[tag.id] = term.id
    _assert_effective_acyclic(_combined_edges(), mappings)
    return TagEczMapping.objects.create(
        tag=tag,
        ecz_term=term,
        status=TagEczMapping.Status.ACTIVE,
        mapped_by=actor,
        mapped_at=timezone.now(),
        mapping_note=note,
    )


@transaction.atomic
def revoke_tag_ecz_mapping(
    mapping_id,
    *,
    actor: Account,
    note: str,
) -> TagEczMapping:
    _require_admin(actor)
    note = note.strip()
    if not note:
        raise EczTaxonomyError("A demerge rationale is required.")
    mapping = TagEczMapping.objects.select_for_update().get(id=mapping_id)
    if mapping.status != TagEczMapping.Status.ACTIVE:
        raise EczTaxonomyError("This ECZ mapping is already revoked.")
    mapping.status = TagEczMapping.Status.REVOKED
    mapping.revoked_by = actor
    mapping.revoked_at = timezone.now()
    mapping.revocation_note = note
    mapping.save(
        update_fields=[
            "status",
            "revoked_by",
            "revoked_at",
            "revocation_note",
        ]
    )
    return mapping


def validate_combined_taxonomy() -> None:
    _assert_effective_acyclic(_combined_edges(), _active_mapping_pairs())
    invalid_cross_tags = TagEczParent.objects.exclude(
        tag__namespace=Tag.Namespace.CODE
    ).count()
    if invalid_cross_tags:
        raise EczTaxonomyError(
            f"{invalid_cross_tags} non-code tags have ECZ parent relationships."
        )


def _combined_edges(
    *,
    cross_override: tuple[object, set] | None = None,
) -> set[tuple[str, str]]:
    edges = {
        (f"cb:{child_id}", f"cb:{parent_id}")
        for child_id, parent_id in TagParent.objects.values_list(
            "child_id", "parent_id"
        )
    }
    edges.update(
        (f"ecz:{child_id}", f"ecz:{parent_id}")
        for child_id, parent_id in EczParent.objects.values_list(
            "child_id", "parent_id"
        )
    )
    cross_edges = set(TagEczParent.objects.values_list("tag_id", "ecz_term_id"))
    if cross_override is not None:
        tag_id, term_ids = cross_override
        cross_edges = {edge for edge in cross_edges if edge[0] != tag_id}
        cross_edges.update((tag_id, term_id) for term_id in term_ids)
    edges.update((f"cb:{tag_id}", f"ecz:{term_id}") for tag_id, term_id in cross_edges)
    return edges


def _active_mapping_pairs() -> dict:
    return dict(
        TagEczMapping.objects.filter(status=TagEczMapping.Status.ACTIVE).values_list(
            "tag_id", "ecz_term_id"
        )
    )


def _assert_effective_acyclic(edges: set[tuple[str, str]], mappings: dict) -> None:
    replacements = {
        f"cb:{tag_id}": f"ecz:{term_id}" for tag_id, term_id in mappings.items()
    }
    effective_edges = {
        (replacements.get(child, child), replacements.get(parent, parent))
        for child, parent in edges
    }
    self_edges = sorted(child for child, parent in effective_edges if child == parent)
    if self_edges:
        raise EczTaxonomyError(
            f"The mapping would make {self_edges[0]} its own effective parent."
        )
    parents = defaultdict(set)
    nodes = set()
    for child, parent in effective_edges:
        parents[child].add(parent)
        nodes.update((child, parent))
    visiting = set()
    visited = set()

    def visit(node, path):
        if node in visiting:
            raise EczTaxonomyError(
                "The combined taxonomy would contain a cycle: "
                + " -> ".join((*path, node))
            )
        if node in visited:
            return
        visiting.add(node)
        for parent in sorted(parents[node]):
            visit(parent, (*path, node))
        visiting.remove(node)
        visited.add(node)

    for node in sorted(nodes):
        visit(node, ())


def _normalise_ecz_term_ids(values: Iterable[EczTerm | str]) -> tuple:
    ids = []
    seen = set()
    for value in values:
        raw_id = value.id if isinstance(value, EczTerm) else value
        try:
            term_id = EczTerm._meta.pk.to_python(raw_id)
        except (TypeError, ValueError) as error:
            raise EczTaxonomyError("An ECZ parent identity is invalid.") from error
        if term_id not in seen:
            ids.append(term_id)
            seen.add(term_id)
    return tuple(ids)


def _require_admin(actor: Account) -> None:
    if not actor.is_active or not actor.is_admin:
        raise EczTaxonomyPermissionError("Administrator access is required.")


def _acquire_combined_graph_lock() -> None:
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            [ECZ_TAXONOMY_ADVISORY_LOCK_ID],
        )
