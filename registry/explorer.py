"""Small, query-contract-neutral helpers for scientific explorer tables.

The current HTML explorers expose ordinary text/filter parameters.  This module
keeps sorting and column visibility reproducible in the URL without attempting
to define the later public scripted-query language.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest, QueryDict


@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str
    sortable: bool = True
    numeric: bool = False
    default_visible: bool = True
    default_direction: str = "asc"
    help_text: str = ""


@dataclass(frozen=True)
class SortKey:
    key: str
    direction: str


def parse_sort(
    raw_sort: str,
    columns: Sequence[ColumnSpec],
    default: Sequence[tuple[str, str]],
) -> tuple[SortKey, ...]:
    """Parse the small internal ``sort`` URL parameter against a whitelist."""

    sortable = {column.key for column in columns if column.sortable}
    parsed: list[SortKey] = []
    seen: set[str] = set()
    for raw_key in raw_sort.split(","):
        raw_key = raw_key.strip()
        if not raw_key:
            continue
        direction = "desc" if raw_key.startswith("-") else "asc"
        key = raw_key.removeprefix("-")
        if key not in sortable or key in seen:
            continue
        parsed.append(SortKey(key=key, direction=direction))
        seen.add(key)

    if parsed:
        return tuple(parsed)
    return tuple(SortKey(key=key, direction=direction) for key, direction in default)


def apply_sort(
    queryset: QuerySet,
    sort_keys: Sequence[SortKey],
    field_map: Mapping[str, str],
) -> QuerySet:
    """Apply whitelisted table ordering with a stable UUID tie-breaker."""

    terms = []
    for sort_key in sort_keys:
        field = field_map[sort_key.key]
        terms.append(f"-{field}" if sort_key.direction == "desc" else field)
    terms.append("id")
    return queryset.order_by(*terms)


def table_context(
    request: HttpRequest,
    columns: Sequence[ColumnSpec],
    sort_keys: Sequence[SortKey],
    *,
    clear_on_sort: Sequence[str] = (),
) -> dict[str, Any]:
    """Build table headers, ordinary-click fallbacks and column-choice state."""

    column_by_key = {column.key: column for column in columns}
    raw_columns = request.GET.get("columns", "")
    requested = [key.strip() for key in raw_columns.split(",") if key.strip()]
    visible_keys = [key for key in requested if key in column_by_key]
    if not visible_keys:
        visible_keys = [column.key for column in columns if column.default_visible]

    sort_by_key = {sort_key.key: sort_key for sort_key in sort_keys}
    sort_positions = {
        sort_key.key: index for index, sort_key in enumerate(sort_keys, 1)
    }
    visible_columns = []
    chooser_columns = []
    for column in columns:
        active_sort = sort_by_key.get(column.key)
        direction = active_sort.direction if active_sort else None
        index = sort_positions.get(column.key)
        ordinary_direction = (
            "desc"
            if index == 1 and direction == "asc"
            else "asc"
            if index == 1 and direction == "desc"
            else column.default_direction
        )
        params = _copy_without_page(request.GET)
        for name in clear_on_sort:
            params.pop(name, None)
        params["sort"] = (
            f"-{column.key}" if ordinary_direction == "desc" else column.key
        )
        header = {
            "key": column.key,
            "label": column.label,
            "sortable": column.sortable,
            "numeric": column.numeric,
            "help_text": column.help_text,
            "sort_url": f"?{params.urlencode()}",
            "sort_index": index,
            "sort_order": direction,
            "sort_direction": "↓" if direction == "desc" else "↑",
            "aria_sort": (
                "descending"
                if index == 1 and direction == "desc"
                else "ascending"
                if index == 1
                else None
            ),
        }
        if column.key in visible_keys:
            visible_columns.append(header)
        chooser_columns.append(
            {
                "key": column.key,
                "label": column.label,
                "checked": column.key in visible_keys,
            }
        )

    sort_summary_parts = []
    for item in sort_keys:
        direction_label = "descending" if item.direction == "desc" else "ascending"
        sort_summary_parts.append(f"{column_by_key[item.key].label} {direction_label}")
    sort_summary = ", ".join(sort_summary_parts)
    return {
        "table_columns": visible_columns,
        "column_choices": chooser_columns,
        "visible_column_keys": visible_keys,
        "visible_column_count": len(visible_keys),
        "available_column_count": len(columns),
        "sort_summary": sort_summary,
        "sort_is_default": not request.GET.get("sort", "").strip(),
    }


def cells_for_visible_columns(
    visible_keys: Sequence[str], cell_by_key: Mapping[str, Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    return [cell_by_key[key] for key in visible_keys]


def parse_nonnegative_int(raw: str) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def url_without(request: HttpRequest, *names: str) -> str:
    params = request.GET.copy()
    for name in names:
        params.pop(name, None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else request.path


def _copy_without_page(query: QueryDict) -> QueryDict:
    params = query.copy()
    params.pop("page", None)
    return params
