from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

CODE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
YAML_SUFFIXES = {".yml", ".yaml"}
DEFAULT_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_EXPANDED_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 5_000


class EczProjectionError(ValueError):
    """An ECZ source cannot be projected without ambiguity."""


class DuplicateKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that refuses silently overwritten mapping keys."""


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            present = key in mapping
        except TypeError as error:
            raise EczProjectionError("A YAML mapping key is not scalar.") from error
        if present:
            raise EczProjectionError(f"Duplicate YAML mapping key: {key!r}.")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DuplicateKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, order=True)
class EczTermProjection:
    code_id: str
    raw_name: str
    display_name: str
    parent_ids: tuple[str, ...]


@dataclass(frozen=True)
class EczProjection:
    terms: tuple[EczTermProjection, ...]
    source_sha256: str

    @property
    def term_by_id(self) -> dict[str, EczTermProjection]:
        return {term.code_id: term for term in self.terms}

    @property
    def parent_edges(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (term.code_id, parent_id)
            for term in self.terms
            for parent_id in term.parent_ids
        )


@dataclass(frozen=True)
class EczProjectionDiff:
    added_ids: tuple[str, ...]
    retired_ids: tuple[str, ...]
    restored_ids: tuple[str, ...]
    renamed_ids: tuple[str, ...]
    parent_edges_added: tuple[tuple[str, str], ...]
    parent_edges_removed: tuple[tuple[str, str], ...]

    @property
    def changed_term_ids(self) -> frozenset[str]:
        return frozenset(
            (*self.added_ids, *self.retired_ids, *self.restored_ids, *self.renamed_ids)
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.added_ids,
                self.retired_ids,
                self.restored_ids,
                self.renamed_ids,
                self.parent_edges_added,
                self.parent_edges_removed,
            )
        )

    def as_dict(self) -> dict:
        return {
            "terms_added": list(self.added_ids),
            "terms_retired": list(self.retired_ids),
            "terms_restored": list(self.restored_ids),
            "names_changed": list(self.renamed_ids),
            "parent_edges_added": [list(edge) for edge in self.parent_edges_added],
            "parent_edges_removed": [list(edge) for edge in self.parent_edges_removed],
        }


def render_display_name(raw_name: str) -> str:
    """Render ECZ standalone FLM into conservative, safe plain text.

    This deliberately supports only the small name-level subset needed for a
    useful fallback. Unknown commands remain visible as text rather than being
    interpreted as HTML or silently discarded.
    """

    text = " ".join(raw_name.split())
    text = text.replace(r"\(", "").replace(r"\)", "")
    text = text.replace(r"\[", "").replace(r"\]", "")
    text = text.replace("$", "")
    replacements = {
        r"\operatorname": "",
        r"\mathbb": "",
        r"\mathrm": "",
        r"\mathbf": "",
        r"\mathcal": "",
        r"\textit": "",
        r"\textbf": "",
        r"\text": "",
        r"\hyphen": "-",
        r"\quad": " ",
        r"\,": " ",
        "~": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = text.replace("{", "").replace("}", "")
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    return " ".join(text.split())


def parse_source_directory(
    source_directory: str | Path,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
) -> EczProjection:
    root = Path(source_directory).resolve()
    if not root.is_dir():
        raise EczProjectionError(f"ECZ source directory does not exist: {root}")
    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in YAML_SUFFIXES
        and "codes" in path.relative_to(root).parts
    )
    if not candidates:
        raise EczProjectionError("No ECZ code YAML files were found under codes/.")
    if len(candidates) > max_members:
        raise EczProjectionError("The ECZ source contains too many code files.")
    entries = []
    digest = hashlib.sha256()
    expanded_bytes = 0
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        content = path.read_bytes()
        if len(content) > max_member_bytes:
            raise EczProjectionError(f"ECZ source member is too large: {relative}")
        expanded_bytes += len(content)
        if expanded_bytes > max_expanded_bytes:
            raise EczProjectionError("The expanded ECZ source is too large.")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
        entries.append((relative, content))
    return _parse_entries(entries, digest.hexdigest())


def parse_archive(
    archive_bytes: bytes,
    *,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_expanded_bytes: int = DEFAULT_MAX_EXPANDED_BYTES,
) -> EczProjection:
    if len(archive_bytes) > max_archive_bytes:
        raise EczProjectionError("The compressed ECZ archive is too large.")
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    entries = []
    expanded_bytes = 0
    member_count = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*")
    except tarfile.TarError as error:
        raise EczProjectionError(
            "The ECZ download is not a valid tar archive."
        ) from error
    with archive:
        for member in archive:
            member_count += 1
            if member_count > max_members:
                raise EczProjectionError("The ECZ archive contains too many members.")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise EczProjectionError("The ECZ archive contains an unsafe path.")
            if member.issym() or member.islnk():
                raise EczProjectionError("The ECZ archive contains a link member.")
            if not member.isfile():
                continue
            if member.size > max_member_bytes:
                raise EczProjectionError(
                    f"ECZ archive member is too large: {member.name}"
                )
            expanded_bytes += member.size
            if expanded_bytes > max_expanded_bytes:
                raise EczProjectionError("The expanded ECZ archive is too large.")
            if path.suffix.lower() not in YAML_SUFFIXES or "codes" not in path.parts:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                raise EczProjectionError(f"Cannot read ECZ member: {member.name}")
            entries.append((member.name, extracted.read()))
    if not entries:
        raise EczProjectionError("No ECZ code YAML files were found in the archive.")
    return _parse_entries(sorted(entries), archive_digest)


def _parse_entries(entries: Iterable[tuple[str, bytes]], digest: str) -> EczProjection:
    terms = []
    seen_ids = set()
    for source_name, content in entries:
        try:
            decoded = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EczProjectionError(f"ECZ YAML is not UTF-8: {source_name}") from error
        try:
            document = yaml.load(decoded, Loader=DuplicateKeySafeLoader)
        except yaml.YAMLError as error:
            raise EczProjectionError(
                f"Invalid ECZ YAML in {source_name}: {error}"
            ) from error
        if not isinstance(document, Mapping):
            raise EczProjectionError(f"ECZ code entry is not a mapping: {source_name}")
        code_id = document.get("code_id")
        raw_name = document.get("name")
        if not isinstance(code_id, str) or not CODE_ID_PATTERN.fullmatch(code_id):
            raise EczProjectionError(f"Invalid ECZ code_id in {source_name}.")
        if code_id in seen_ids:
            raise EczProjectionError(f"Duplicate ECZ code_id: {code_id}.")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise EczProjectionError(f"Invalid ECZ name for {code_id}.")
        parent_ids = _parent_ids(document.get("relations"), code_id)
        display_name = render_display_name(raw_name)
        if not display_name:
            raise EczProjectionError(f"ECZ name renders empty for {code_id}.")
        terms.append(
            EczTermProjection(
                code_id=code_id,
                raw_name=raw_name,
                display_name=display_name,
                parent_ids=parent_ids,
            )
        )
        seen_ids.add(code_id)
    projection = EczProjection(tuple(sorted(terms)), digest)
    validate_projection(projection)
    return projection


def _parent_ids(relations, code_id: str) -> tuple[str, ...]:
    if relations is None:
        return ()
    if not isinstance(relations, Mapping):
        raise EczProjectionError(f"Invalid relations mapping for {code_id}.")
    if "parents" not in relations:
        return ()
    parents = relations["parents"]
    if parents is None:
        return ()
    if not isinstance(parents, list):
        raise EczProjectionError(f"Invalid parents list for {code_id}.")
    parent_ids = []
    seen = set()
    for parent in parents:
        if not isinstance(parent, Mapping):
            raise EczProjectionError(f"Invalid parent relation for {code_id}.")
        parent_id = parent.get("code_id")
        if not isinstance(parent_id, str) or not CODE_ID_PATTERN.fullmatch(parent_id):
            raise EczProjectionError(f"Invalid parent code_id for {code_id}.")
        if parent_id in seen:
            raise EczProjectionError(
                f"Duplicate parent relation {code_id} -> {parent_id}."
            )
        parent_ids.append(parent_id)
        seen.add(parent_id)
    return tuple(sorted(parent_ids))


def validate_projection(projection: EczProjection) -> None:
    terms = projection.term_by_id
    if len(terms) != len(projection.terms):
        raise EczProjectionError("The ECZ projection contains duplicate code IDs.")
    for child_id, parent_id in projection.parent_edges:
        if child_id == parent_id:
            raise EczProjectionError(f"ECZ term {child_id} is its own parent.")
        if parent_id not in terms:
            raise EczProjectionError(
                f"ECZ term {child_id} has missing parent {parent_id}."
            )
    _assert_acyclic(terms, projection.parent_edges)


def _assert_acyclic(
    terms: Mapping[str, EczTermProjection],
    edges: Iterable[tuple[str, str]],
) -> None:
    parents = defaultdict(set)
    for child_id, parent_id in edges:
        parents[child_id].add(parent_id)
    visiting = set()
    visited = set()

    def visit(code_id: str, path: tuple[str, ...]) -> None:
        if code_id in visiting:
            cycle = " -> ".join((*path, code_id))
            raise EczProjectionError(f"The ECZ parent graph contains a cycle: {cycle}.")
        if code_id in visited:
            return
        visiting.add(code_id)
        for parent_id in sorted(parents[code_id]):
            visit(parent_id, (*path, code_id))
        visiting.remove(code_id)
        visited.add(code_id)

    for code_id in sorted(terms):
        visit(code_id, ())


def projection_content_sha256(projection: EczProjection) -> str:
    payload = [
        {
            "code_id": term.code_id,
            "raw_name": term.raw_name,
            "display_name": term.display_name,
            "parent_ids": term.parent_ids,
        }
        for term in projection.terms
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
