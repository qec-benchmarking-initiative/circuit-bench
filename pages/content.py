"""Load and safely render the repository's deliberately small Markdown subset."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.utils.safestring import SafeString, mark_safe

CONTENT_ROOT = Path(settings.BASE_DIR) / "content"
DEFINITION_ROOT = Path(settings.BASE_DIR) / "definitions"
PAGE_FILES = {
    "about": "about.md",
    "query-syntax": "query-syntax.md",
}

_INLINE_PATTERN = re.compile(r"`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)")
_ORDERED_ITEM = re.compile(r"^\s*\d+[.)]\s+(.+)$")
_UNORDERED_ITEM = re.compile(r"^\s*[-*+]\s+(.+)$")
_HEADING = re.compile(r"^(#{1,4})\s+(.+)$")
_LANGUAGE = re.compile(r"^[A-Za-z0-9_-]+$")


class ContentError(ValueError):
    """A version-controlled content file is missing or malformed."""


@dataclass(frozen=True)
class MarkdownDocument:
    slug: str
    title: str
    summary: str
    body_markdown: str
    html: SafeString
    published: date | None = None
    author: str | None = None


def get_page(slug: str) -> MarkdownDocument:
    filename = PAGE_FILES.get(slug)
    if filename is None:
        raise ContentError(f"Unknown static page: {slug}")
    return load_document(CONTENT_ROOT / "pages" / filename, default_slug=slug)


def get_definition(record_type: str, version: str) -> MarkdownDocument:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", record_type) or not re.fullmatch(
        r"[0-9]+\.[0-9]+", version
    ):
        raise ContentError("Invalid definition identifier.")
    path = DEFINITION_ROOT / record_type / f"{version}.md"
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContentError(f"Could not read definition file: {path}") from error
    lines = source.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ContentError(f"Definition file has no title: {path}")
    title = lines[0][2:].strip()
    body = "\n".join(lines[1:]).strip()
    return MarkdownDocument(
        slug=f"{record_type}-{version}",
        title=title,
        summary=f"Versioned {record_type.replace('_', ' ')} definition {version}.",
        body_markdown=body,
        html=render_markdown(body),
    )


def get_blog_post(slug: str) -> MarkdownDocument:
    for document in blog_posts():
        if document.slug == slug:
            return document
    raise ContentError(f"Unknown blog post: {slug}")


def blog_posts() -> list[MarkdownDocument]:
    blog_root = CONTENT_ROOT / "blog"
    documents = [
        load_document(path, default_slug=path.stem)
        for path in sorted(blog_root.glob("*.md"))
    ]
    return sorted(
        documents,
        key=lambda document: (document.published or date.min, document.slug),
        reverse=True,
    )


def load_document(path: Path, *, default_slug: str) -> MarkdownDocument:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ContentError(f"Could not read content file: {path}") from error

    metadata, body = _split_front_matter(source)
    title = metadata.get("title", "").strip()
    if not title:
        raise ContentError(f"Content file has no title: {path}")
    slug = metadata.get("slug", default_slug).strip()
    if not re.fullmatch(r"[-a-z0-9]+", slug):
        raise ContentError(f"Content file has an invalid slug: {path}")
    published = None
    if metadata.get("published"):
        try:
            published = date.fromisoformat(metadata["published"])
        except ValueError as error:
            message = f"Content file has an invalid published date: {path}"
            raise ContentError(message) from error
    return MarkdownDocument(
        slug=slug,
        title=title,
        summary=metadata.get("summary", "").strip(),
        author=metadata.get("author", "").strip() or None,
        published=published,
        body_markdown=body,
        html=render_markdown(body),
    )


def render_markdown(source: str) -> SafeString:
    """Render a constrained Markdown subset after escaping all source text.

    Supported blocks are headings, paragraphs, flat ordered/unordered lists,
    and fenced code.  Inline code and links are supported.  Raw HTML is always
    displayed as text, and links are restricted to ordinary web/mail schemes
    or local absolute/fragment references.
    """

    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_fence = False
    fence_language = ""
    fence_lines: list[str] = []
    heading_ids: dict[str, int] = {}

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind is not None:
            output.append(f"</{list_kind}>")
            list_kind = None

    for line in source.splitlines():
        if in_fence:
            if line.strip().startswith("```"):
                language_class = (
                    f' class="language-{fence_language}"' if fence_language else ""
                )
                output.append(
                    f"<pre><code{language_class}>"
                    f"{html.escape(chr(10).join(fence_lines))}</code></pre>"
                )
                in_fence = False
                fence_language = ""
                fence_lines.clear()
            else:
                fence_lines.append(line)
            continue

        if line.strip().startswith("```"):
            flush_paragraph()
            close_list()
            language = line.strip()[3:].strip()
            fence_language = language if _LANGUAGE.fullmatch(language) else ""
            in_fence = True
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            text = heading.group(2).strip()
            base_id = _heading_id(text)
            occurrence = heading_ids.get(base_id, 0) + 1
            heading_ids[base_id] = occurrence
            identifier = base_id if occurrence == 1 else f"{base_id}-{occurrence}"
            output.append(f'<h{level} id="{identifier}">{_inline(text)}</h{level}>')
            continue

        unordered = _UNORDERED_ITEM.match(line)
        ordered = _ORDERED_ITEM.match(line)
        if unordered or ordered:
            flush_paragraph()
            requested_kind = "ul" if unordered else "ol"
            if list_kind != requested_kind:
                close_list()
                output.append(f"<{requested_kind}>")
                list_kind = requested_kind
            item_text = (unordered or ordered).group(1)
            output.append(f"<li>{_inline(item_text)}</li>")
            continue

        close_list()
        paragraph.append(line.strip())

    if in_fence:
        # An unclosed fence is still rendered safely and visibly.
        output.append(
            f"<pre><code>{html.escape(chr(10).join(fence_lines))}</code></pre>"
        )
    flush_paragraph()
    close_list()
    return mark_safe("\n".join(output))


def _split_front_matter(source: str) -> tuple[dict[str, str], str]:
    lines = source.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContentError("Content files must begin with --- front matter.")
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return metadata, "\n".join(lines[index + 1 :]).strip()
        key, separator, value = line.partition(":")
        if not separator or not key.strip():
            raise ContentError(f"Malformed front-matter line: {line}")
        metadata[key.strip().lower()] = value.strip()
    raise ContentError("Content front matter has no closing --- line.")


def _inline(source: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _INLINE_PATTERN.finditer(source):
        pieces.append(html.escape(source[cursor : match.start()]))
        if match.group(1) is not None:
            pieces.append(f"<code>{html.escape(match.group(1))}</code>")
        else:
            label = html.escape(match.group(2))
            url = match.group(3).strip()
            if _safe_url(url):
                pieces.append(f'<a href="{html.escape(url, quote=True)}">{label}</a>')
            else:
                pieces.append(label)
        cursor = match.end()
    pieces.append(html.escape(source[cursor:]))
    return "".join(pieces)


def _safe_url(url: str) -> bool:
    if url.startswith("#"):
        return True
    if url.startswith("/") and not url.startswith("//"):
        return True
    return urlsplit(url).scheme.lower() in {"http", "https", "mailto"}


def _heading_id(source: str) -> str:
    plain = re.sub(r"[`\[\]()]", "", source).lower()
    identifier = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    return identifier or "section"
