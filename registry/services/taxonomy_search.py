from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from django.db.models import Prefetch, Q
from django.db.models.functions import Lower

from registry.models import (
    EczParent,
    EczTerm,
    Tag,
    TagAlias,
    TagEczMapping,
    TagEczParent,
    TagParent,
)
from registry.services.ecz_taxonomy import (
    TaxonomyTermDisplay,
    display_ecz_term,
    display_native_tag,
    parse_taxonomy_key,
)

DEFAULT_PAGE_SIZE = 12
MAX_PAGE_SIZE = 50


@dataclass(frozen=True)
class TaxonomySearchPage:
    shown: tuple[TaxonomyTermDisplay, ...]
    total: int
    remaining: int
    next_offset: int | None

    def as_dict(self) -> dict:
        return {
            "shown": [serialize_term(item) for item in self.shown],
            "total": self.total,
            "remaining": self.remaining,
            "next_offset": self.next_offset,
        }


@dataclass(frozen=True)
class TaxonomySearchResult:
    query: str
    selected: tuple[TaxonomyTermDisplay, ...]
    circuit_bench: TaxonomySearchPage
    ecz: TaxonomySearchPage
    parent_circuit_bench: TaxonomySearchPage
    parent_ecz: TaxonomySearchPage

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "selected": [serialize_term(item) for item in self.selected],
            "circuit_bench": self.circuit_bench.as_dict(),
            "ecz": self.ecz.as_dict(),
            "unselected_parents": {
                "circuit_bench": self.parent_circuit_bench.as_dict(),
                "ecz": self.parent_ecz.as_dict(),
            },
        }


def search_taxonomy_terms(
    *,
    namespace: str,
    query: str = "",
    selected_keys=(),
    context_keys=(),
    excluded_keys=(),
    cb_offset: int = 0,
    ecz_offset: int = 0,
    parent_cb_offset: int = 0,
    parent_ecz_offset: int = 0,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> TaxonomySearchResult:
    if namespace not in Tag.Namespace.values:
        raise ValueError("Unknown tag namespace.")
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))
    query = " ".join(query.split())[:200]
    selected_key_set = set(selected_keys)
    context_key_set = set(context_keys)
    excluded_native_ids, excluded_ecz_ids = _resolve_keys(excluded_keys, namespace)
    selected_native_ids, selected_ecz_ids = _resolve_keys(selected_key_set, namespace)
    selected_key_set = {
        *(f"cb:{item_id}" for item_id in selected_native_ids),
        *(f"ecz:{code_id}" for code_id in selected_ecz_ids),
    }

    native_terms = _native_displays(
        namespace,
        selected_ids=selected_native_ids,
    )
    ecz_terms = (
        _ecz_displays(selected_code_ids=selected_ecz_ids)
        if namespace == Tag.Namespace.CODE
        else []
    )
    native_terms = [
        item
        for item in native_terms
        if uuid.UUID(item.database_id) not in excluded_native_ids
    ]
    ecz_terms = [
        item
        for item in ecz_terms
        if item.key.removeprefix("ecz:") not in excluded_ecz_ids
    ]
    native_matches = _rank_matches(native_terms, query)
    ecz_matches = _rank_matches(ecz_terms, query, ecz=True)
    selected = tuple(
        [item for item in native_terms if item.key in selected_key_set]
        + [item for item in ecz_terms if item.key in selected_key_set]
    )
    native_page = _page(native_matches, cb_offset, page_size)
    ecz_page = _page(ecz_matches, ecz_offset, page_size)

    visible_keys = {*(item.key for item in selected)}
    if query:
        visible_keys.update(item.key for item in native_page.shown)
        visible_keys.update(item.key for item in ecz_page.shown)
        visible_keys.update(context_key_set)
    parent_native_ids, parent_ecz_ids = _direct_parent_ids(visible_keys, namespace)
    parent_native = [
        item
        for item in _native_displays(namespace, include_ids=parent_native_ids)
        if item.key not in visible_keys
        and uuid.UUID(item.database_id) in parent_native_ids
        and uuid.UUID(item.database_id) not in excluded_native_ids
    ]
    parent_ecz = [
        item
        for item in (
            _ecz_displays(include_code_ids=parent_ecz_ids)
            if namespace == Tag.Namespace.CODE
            else []
        )
        if item.key not in visible_keys
        and item.key.removeprefix("ecz:") in parent_ecz_ids
        and item.key.removeprefix("ecz:") not in excluded_ecz_ids
    ]
    parent_native.sort(key=lambda item: (item.label.casefold(), item.key))
    parent_ecz.sort(key=lambda item: (item.label.casefold(), item.key))
    return TaxonomySearchResult(
        query=query,
        selected=selected,
        circuit_bench=native_page,
        ecz=ecz_page,
        parent_circuit_bench=_page(parent_native, parent_cb_offset, page_size),
        parent_ecz=_page(parent_ecz, parent_ecz_offset, page_size),
    )


def serialize_term(item: TaxonomyTermDisplay) -> dict:
    source, identity = parse_taxonomy_key(item.key)
    return {
        "key": item.key,
        "source": item.source,
        "identity": identity,
        "label": item.label,
        "source_suffix": item.source_suffix,
        "url": item.url,
        "selectable": item.selectable,
        "selected": item.selected,
        "status": item.status,
        "colour": item.colour,
        "border_style": item.border_style,
        "namespace": item.namespace,
        "aliases": list(item.aliases),
        "database_id": item.database_id,
        "slug": item.slug,
        "matched_alias": item.matched_alias,
        "storage_source": source,
    }


def _native_displays(
    namespace: str,
    *,
    selected_ids=(),
    include_ids=(),
) -> list[TaxonomyTermDisplay]:
    alias_queryset = TagAlias.objects.filter(is_active=True).order_by(
        Lower("alias"), "id"
    )
    visible_ids = set(selected_ids) | set(include_ids)
    queryset = (
        Tag.objects.filter(namespace=namespace)
        .filter(
            Q(status__in=(Tag.Status.CUSTOM, Tag.Status.OFFICIAL))
            | Q(id__in=visible_ids)
        )
        .exclude(
            ecz_mappings__status=TagEczMapping.Status.ACTIVE,
        )
        .prefetch_related(
            Prefetch("aliases", queryset=alias_queryset, to_attr="display_aliases")
        )
        .order_by(Lower("label"), "id")
        .distinct()
    )
    selected_ids = set(selected_ids)
    return [
        display_native_tag(tag, selected=tag.id in selected_ids) for tag in queryset
    ]


def _ecz_displays(
    *,
    selected_code_ids=(),
    include_code_ids=(),
) -> list[TaxonomyTermDisplay]:
    visible_ids = set(selected_code_ids) | set(include_code_ids)
    queryset = EczTerm.objects.filter(
        Q(status=EczTerm.Status.CURRENT) | Q(ecz_code_id__in=visible_ids)
    ).order_by(Lower("display_name"), "ecz_code_id")
    selected_code_ids = set(selected_code_ids)
    return [
        display_ecz_term(term, selected=term.ecz_code_id in selected_code_ids)
        for term in queryset
    ]


def _rank_matches(
    terms: list[TaxonomyTermDisplay], query: str, *, ecz: bool = False
) -> list[TaxonomyTermDisplay]:
    normalized = query.casefold()
    if not normalized:
        return sorted(
            terms,
            key=lambda item: (
                0 if item.status == Tag.Status.OFFICIAL else 1,
                item.label.casefold(),
                item.key,
            ),
        )
    ranked = []
    for item in terms:
        label = item.label.casefold()
        aliases = tuple(alias.casefold() for alias in item.aliases)
        matching_alias = next(
            (
                original
                for original in item.aliases
                if normalized in original.casefold()
            ),
            "",
        )
        _source, identity = parse_taxonomy_key(item.key)
        identity = identity.casefold()
        if label == normalized or normalized in aliases:
            rank = 0
        elif ecz and identity == normalized:
            rank = 1
        elif label.startswith(normalized) or any(
            alias.startswith(normalized) for alias in aliases
        ):
            rank = 2
        elif (
            normalized in label
            or normalized in identity
            or any(normalized in alias for alias in aliases)
        ):
            rank = 3
        else:
            continue
        ranked.append(
            (
                rank,
                item.label.casefold(),
                item.key,
                replace(item, matched_alias=matching_alias),
            )
        )
    return [item for _rank, _label, _key, item in sorted(ranked)]


def _page(items, offset, page_size) -> TaxonomySearchPage:
    offset = max(0, int(offset))
    total = len(items)
    shown = tuple(items[offset : offset + page_size])
    consumed = min(total, offset + len(shown))
    remaining = total - consumed
    return TaxonomySearchPage(
        shown=shown,
        total=total,
        remaining=remaining,
        next_offset=consumed if remaining else None,
    )


def _resolve_keys(keys, namespace) -> tuple[set, set[str]]:
    native_ids = set()
    ecz_ids = set()
    legacy_slugs = []
    for key in keys:
        try:
            source, identity = parse_taxonomy_key(key)
        except ValueError:
            legacy_slugs.append(key)
            continue
        if source == "ecz":
            ecz_ids.add(identity)
        else:
            try:
                native_ids.add(uuid.UUID(identity))
            except ValueError:
                continue
    if legacy_slugs:
        native_ids.update(
            Tag.objects.filter(namespace=namespace, slug__in=legacy_slugs).values_list(
                "id", flat=True
            )
        )
    return native_ids, ecz_ids


def _direct_parent_ids(keys, namespace) -> tuple[set, set[str]]:
    native_ids, ecz_code_ids = _resolve_keys(keys, namespace)
    native_parent_ids = set(
        TagParent.objects.filter(child_id__in=native_ids).values_list(
            "parent_id", flat=True
        )
    )
    ecz_parent_term_ids = set(
        TagEczParent.objects.filter(tag_id__in=native_ids).values_list(
            "ecz_term_id", flat=True
        )
    )
    if ecz_code_ids:
        ecz_parent_term_ids.update(
            EczParent.objects.filter(child__ecz_code_id__in=ecz_code_ids).values_list(
                "parent_id", flat=True
            )
        )
    ecz_parent_code_ids = set(
        EczTerm.objects.filter(id__in=ecz_parent_term_ids).values_list(
            "ecz_code_id", flat=True
        )
    )
    return native_parent_ids, ecz_parent_code_ids
