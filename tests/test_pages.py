from django.urls import reverse


def test_home_page_uses_shared_shell(client):
    response = client.get(reverse("pages:home"))
    assert response.status_code == 200
    assert b"DecoderBench" in response.content
    assert b"Search the registry" in response.content


def test_component_gallery_renders_difficult_states(client, settings):
    settings.DEBUG = True
    response = client.get(reverse("pages:component-gallery"))
    assert response.status_code == 200
    assert b"Component gallery" in response.content
    assert b"Valid query" in response.content
    assert b"No matching results" in response.content


def test_component_gallery_is_not_available_in_production(client, settings):
    settings.DEBUG = False
    assert client.get(reverse("pages:component-gallery")).status_code == 404
