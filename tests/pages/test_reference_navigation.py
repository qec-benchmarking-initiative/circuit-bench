import pytest
from django.urls import reverse

from pages.content import blog_posts, definition_documents, static_pages

pytestmark = pytest.mark.django_db


def test_home_and_about_index_link_every_static_document(client):
    home = client.get(reverse("pages:home"))
    about = client.get(reverse("pages:about"))

    assert home.status_code == about.status_code == 200
    for document in static_pages():
        expected = (
            reverse("pages:about")
            if document.slug == "about"
            else reverse("pages:query-syntax")
        )
        assert expected in home.content.decode()
        assert expected in about.content.decode()
    for post in blog_posts():
        expected = reverse("pages:blog-detail", args=[post.slug])
        assert expected in home.content.decode()
        assert expected in about.content.decode()
    for document in definition_documents():
        expected = reverse("pages:definition", args=document.slug.rsplit("-", 1))
        assert expected in home.content.decode()
        assert expected in about.content.decode()


def test_about_primary_navigation_points_to_collection(client):
    home = client.get(reverse("pages:home")).content.decode()
    about = client.get(reverse("pages:about")).content.decode()

    assert f'href="{reverse("pages:about")}"' in home
    assert ">About</a>" in home
    assert "All reference pages" in about
    assert 'aria-current="page">About</a>' in about


def test_reference_tab_is_not_marked_as_current_on_registry_search(client, db):
    search = client.get(reverse("pages:search"), {"q": "anything"}).content.decode()

    assert 'aria-current="page">About</a>' not in search
