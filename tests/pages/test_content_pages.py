from django.urls import reverse

from pages.content import render_markdown
from registry.result_query import RESULT_FIELDS


def test_about_page_is_rendered_from_version_controlled_markdown(client):
    response = client.get(reverse("pages:about"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "About Circuit Bench" in content
    assert "Meaning stays attached to the number" in content
    assert "version 0.1 development drafts" in content
    assert reverse("pages:query-syntax") in content


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


def test_blog_index_is_newest_first_and_posts_have_stable_routes(client):
    response = client.get(reverse("pages:blog-index"))

    assert response.status_code == 200
    content = response.content.decode()
    assert content.index("Why Circuit Bench starts from exact records") < content.index(
        "A single query contract for tables and scripts"
    )

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
