import pytest
from django.urls import reverse

from pages.content import ContentError, render_markdown
from registry.result_query import RESULT_FIELDS


def test_about_page_is_rendered_from_version_controlled_markdown(client):
    response = client.get(reverse("pages:about"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "About Circuit Bench" in content
    assert "Common benchmarks for decoders" in content
    assert "Scientific flexibility vs standardisation" in content
    assert 'href="https://doi.org/10.22331/q-2021-07-06-497"' in content
    assert '<a href="#fn-stim" role="doc-noteref"' in content
    assert 'id="fn-stim" role="doc-endnote"' in content
    assert "<em>Stim: a fast stabilizer circuit simulator</em>" in content
    assert "Quantum <strong>5</strong>, 497 (2021)" in content


def test_query_reference_matches_the_result_record_0_1_contract(client):
    response = client.get(reverse("pages:query-syntax"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "ResultRecord query syntax 0.1" in content
    assert "OData 4.01 URL conventions" in content
    assert "$filter" in content
    assert "$orderby" in content
    assert "$select" in content
    assert "$top" in content
    assert "$skip" in content
    assert "$count=true" in content
    assert "score_ler_upper_95_at_5pct_acceptance_v0_1" in content
    assert "t_1000_ns" in content
    assert "unsupported_option" in content
    assert "2,000 characters and 100 expression nodes" in content
    for field in RESULT_FIELDS:
        assert field.name in content


def test_tags_page_is_rendered_and_linked_from_about(client):
    tags_url = reverse("pages:static-reference", args=["tags"])
    response = client.get(tags_url)

    assert response.status_code == 200
    assert b"Tag system" in response.content
    assert b"decoding-algorithm tags" in response.content
    assert b'href="https://errorcorrectionzoo.org/"' in response.content

    about = client.get(reverse("pages:about"))
    assert tags_url.encode() in about.content


def test_api_guide_is_rendered_and_linked_from_about(client):
    api_url = reverse("pages:static-reference", args=["api"])
    response = client.get(api_url)

    assert response.status_code == 200
    assert b"Circuit Bench API" in response.content
    assert b"Authorization" in response.content
    assert b"/api/0.1/openapi.json" in response.content
    assert api_url.encode() in client.get(reverse("pages:about")).content


def test_blog_index_is_newest_first_and_posts_have_stable_routes(client):
    response = client.get(reverse("pages:blog-index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.index(
        "Why Circuit Bench starts from individual records"
    ) < content.index("A single query contract for tables and scripts")

    detail = client.get(reverse("pages:blog-detail", args=["why-exact-records"]))
    assert detail.status_code == 200
    assert b"The table is a view of evidence" in detail.content
    assert b'datetime="2026-08-31"' in detail.content


def test_unknown_blog_post_returns_404(client):
    assert client.get("/blog/no-such-post/").status_code == 404


def test_versioned_scientific_definitions_have_permanent_rendered_routes(client):
    response = client.get(reverse("pages:definition", args=["result", "0.1"]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Result definitions 0.1" in content
    assert 'id="preparation-and-timing"' in content
    assert 'id="stored-scores"' in content


def test_unknown_or_malformed_definition_returns_404(client):
    assert client.get("/definitions/result/9.9/").status_code == 404
    assert client.get("/definitions/result/not-a-version/").status_code == 404


def test_markdown_renderer_escapes_html_and_rejects_active_link_schemes():
    rendered = str(
        render_markdown(
            "# Safety\n\n<script>alert(1)</script> "
            "[bad](javascript:alert(1)) [good](https://example.org)"
        )
    )

    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert 'href="javascript:' not in rendered
    assert 'href="https://example.org"' in rendered


def test_markdown_renderer_supports_emphasis_in_text_and_link_labels():
    rendered = str(
        render_markdown(
            "**bold** and *italic* and ***both***; "
            "[a *paper* in volume **5**](https://example.org/paper)"
        )
    )

    assert "<strong>bold</strong>" in rendered
    assert "<em>italic</em>" in rendered
    assert "<strong><em>both</em></strong>" in rendered
    assert (
        '<a href="https://example.org/paper">a <em>paper</em> in volume '
        "<strong>5</strong></a>"
    ) in rendered


def test_markdown_renderer_numbers_and_links_reusable_footnotes():
    rendered = str(
        render_markdown(
            "Beta first[^beta], alpha second[^alpha], beta again[^beta].\n\n"
            "[^alpha]: Alpha reference.\n"
            "[^beta]: [*Beta paper*](https://example.org/beta)."
        )
    )

    assert (
        '<a href="#fn-beta" role="doc-noteref" aria-label="Reference 1">[1]</a>'
        in rendered
    )
    assert (
        '<a href="#fn-alpha" role="doc-noteref" aria-label="Reference 2">[2]</a>'
        in rendered
    )
    assert 'id="fnref-beta"' in rendered
    assert 'id="fnref-beta-2"' in rendered
    assert 'id="fn-beta" role="doc-endnote"' in rendered
    assert rendered.index('id="fn-beta"') < rendered.index('id="fn-alpha"')
    assert '<a href="https://example.org/beta"><em>Beta paper</em></a>' in rendered
    assert 'href="#fnref-beta"' in rendered
    assert 'href="#fnref-beta-2"' in rendered


def test_markdown_renderer_leaves_unknown_footnotes_visible_and_rejects_duplicates():
    assert "Missing[^unknown]" in str(render_markdown("Missing[^unknown]"))
    with pytest.raises(ContentError, match="Duplicate footnote definition: duplicate"):
        render_markdown(
            "Text[^duplicate].\n\n[^duplicate]: First.\n[^duplicate]: Second."
        )


def test_markdown_renderer_does_not_extract_footnotes_from_code_fences():
    rendered = str(render_markdown("```markdown\n[^example]: literal\n```"))

    assert "[^example]: literal" in rendered
    assert 'class="footnotes"' not in rendered


def test_all_static_content_pages_use_the_shared_reading_column(client):
    urls = [
        reverse("pages:about"),
        reverse("pages:static-reference", args=["tags"]),
        reverse("pages:query-syntax"),
        reverse("pages:blog-index"),
        reverse("pages:blog-detail", args=["why-exact-records"]),
        reverse("pages:definition", args=["result", "0.1"]),
    ]

    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        assert b'class="page-shell static-page"' in response.content
