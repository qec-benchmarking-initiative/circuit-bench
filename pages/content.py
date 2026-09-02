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
    "tags": "tags.md",
    "query-syntax": "query-syntax.md",
    "submission-policy": "submission-policy.md",
}

_INLINE_PATTERN = re.compile(
    r"`(?P<code>[^`\n]+)`"
    r"|\[\^(?P<footnote>[A-Za-z0-9][A-Za-z0-9_-]*)\]"
    r"|\[(?P<label>[^\]\n]+)\]\((?P<url>[^)\n]+)\)"
    r"|\*\*\*(?P<strong_emphasis>[^*\n]+)\*\*\*"
    r"|\*\*(?P<strong>[^*\n]+)\*\*"
    r"|(?<!\*)\*(?P<emphasis>[^*\n]+)\*(?!\*)"
)
_FOOTNOTE_DEFINITION = re.compile(
    r"^\[\^(?P<identifier>[A-Za-z0-9][A-Za-z0-9_-]*)\]:\s*(?P<body>.*)$"
)
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


@dataclass
class _FootnoteState:
    definitions: dict[str, str]
    order: list[str]
    reference_ids: dict[str, list[str]]

    @classmethod
    def from_definitions(cls, definitions: dict[str, str]) -> _FootnoteState:
        return cls(definitions=definitions, order=[], reference_ids={})

    def reference(self, identifier: str) -> str:
        if identifier not in self.definitions:
            return html.escape(f"[^{identifier}]")
        if identifier not in self.order:
            self.order.append(identifier)
        number = self.order.index(identifier) + 1
        references = self.reference_ids.setdefault(identifier, [])
        suffix = f"-{len(references) + 1}" if references else ""
        reference_id = f"fnref-{identifier}{suffix}"
        references.append(reference_id)
        return (
            f'<sup class="footnote-reference" id="{reference_id}">'
            f'<a href="#fn-{identifier}" role="doc-noteref" '
            f'aria-label="Reference {number}">[{number}]</a></sup>'
        )

    def render(self) -> str:
        if not self.order:
            return ""
        output = [
            '<section class="footnotes" role="doc-endnotes" '
            'aria-labelledby="footnote-references">',
            '<h2 id="footnote-references">References</h2>',
            "<ol>",
        ]
        for number, identifier in enumerate(self.order, start=1):
            backlinks = []
            for occurrence, reference_id in enumerate(
                self.reference_ids[identifier], start=1
            ):
                occurrence_label = (
                    f", occurrence {occurrence}"
                    if len(self.reference_ids[identifier]) > 1
                    else ""
                )
                backlinks.append(
                    f'<a class="footnote-backref" href="#{reference_id}" '
                    f'aria-label="Back to reference {number}{occurrence_label}">↩</a>'
                )
            output.append(
                f'<li id="fn-{identifier}" role="doc-endnote">'
                f"{_inline(self.definitions[identifier])} "
                f'<span class="footnote-backlinks">{" ".join(backlinks)}</span>'
                "</li>"
            )
        output.extend(["</ol>", "</section>"])
        return "\n".join(output)


def get_page(slug: str) -> MarkdownDocument:
    filename = PAGE_FILES.get(slug)
    if filename is None:
        raise ContentError(f"Unknown static page: {slug}")
    return load_document(CONTENT_ROOT / "pages" / filename, default_slug=slug)


def static_pages() -> list[MarkdownDocument]:
    """Return every version-controlled general reference page."""

    return [get_page(slug) for slug in PAGE_FILES]


def definition_documents() -> list[MarkdownDocument]:
    """Return every currently rendered versioned scientific definition."""

    documents = []
    for path in sorted(DEFINITION_ROOT.glob("*/*.md")):
        documents.append(get_definition(path.parent.name, path.stem))
    return documents


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
    and fenced code. Inline code, emphasis, strong emphasis, links, and
    single-line Markdown footnotes are supported. Raw HTML is always displayed
    as text, and links are restricted to ordinary web/mail schemes or local
    absolute/fragment references.
    """

    source, definitions = _extract_footnote_definitions(source)
    footnotes = _FootnoteState.from_definitions(definitions)
    output: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_fence = False
    fence_language = ""
    fence_lines: list[str] = []
    heading_ids: dict[str, int] = {}

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_inline(' '.join(paragraph), footnotes)}</p>")
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
            output.append(
                f'<h{level} id="{identifier}">{_inline(text, footnotes)}</h{level}>'
            )
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
            output.append(f"<li>{_inline(item_text, footnotes)}</li>")
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
    rendered_footnotes = footnotes.render()
    if rendered_footnotes:
        output.append(rendered_footnotes)
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


def _inline(source: str, footnotes: _FootnoteState | None = None) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _INLINE_PATTERN.finditer(source):
        pieces.append(html.escape(source[cursor : match.start()]))
        if match.group("code") is not None:
            pieces.append(f"<code>{html.escape(match.group('code'))}</code>")
        elif match.group("footnote") is not None:
            identifier = match.group("footnote")
            pieces.append(
                footnotes.reference(identifier)
                if footnotes is not None
                else html.escape(match.group(0))
            )
        elif match.group("label") is not None:
            label = _emphasis(match.group("label"))
            url = match.group("url").strip()
            if _safe_url(url):
                pieces.append(f'<a href="{html.escape(url, quote=True)}">{label}</a>')
            else:
                pieces.append(label)
        elif match.group("strong_emphasis") is not None:
            pieces.append(
                "<strong><em>"
                f"{html.escape(match.group('strong_emphasis'))}"
                "</em></strong>"
            )
        elif match.group("strong") is not None:
            pieces.append(f"<strong>{html.escape(match.group('strong'))}</strong>")
        else:
            pieces.append(f"<em>{html.escape(match.group('emphasis'))}</em>")
        cursor = match.end()
    pieces.append(html.escape(source[cursor:]))
    return "".join(pieces)


def _extract_footnote_definitions(source: str) -> tuple[str, dict[str, str]]:
    """Remove footnote definitions while leaving fenced examples untouched."""

    body: list[str] = []
    definitions: dict[str, str] = {}
    in_fence = False
    for line in source.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            body.append(line)
            continue
        definition = None if in_fence else _FOOTNOTE_DEFINITION.match(line)
        if definition is None:
            body.append(line)
            continue
        identifier = definition.group("identifier")
        if identifier in definitions:
            raise ContentError(f"Duplicate footnote definition: {identifier}")
        definitions[identifier] = definition.group("body").strip()
    return "\n".join(body), definitions


def _emphasis(source: str) -> str:
    """Render emphasis in a link label without permitting nested links."""

    escaped = html.escape(source)
    escaped = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<strong><em>\1</em></strong>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)


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
