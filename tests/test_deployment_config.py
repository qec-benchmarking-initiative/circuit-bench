from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_staging_banner_is_controlled_centrally(client, settings):
    settings.DEPLOYMENT_ENVIRONMENT = "staging"
    settings.DEPLOYMENT_GIT_COMMIT = "0123456789abcdef"
    settings.DEPLOYMENT_GIT_MESSAGE = "Show deployment identity in staging banner"

    response = client.get("/")

    assert response.status_code == 200
    assert b"Staging installation" in response.content
    assert b"0123456" in response.content
    assert b"Show deployment identity in staging banner" in response.content


def test_staging_seed_is_disabled_without_explicit_setting(settings):
    settings.ALLOW_DEMO_SEED = False

    with pytest.raises(CommandError, match="ALLOW_DEMO_SEED"):
        call_command("seed_staging")


def test_render_blueprint_uses_staging_branch_and_durable_services():
    blueprint = (Path(__file__).parents[1] / "render.yaml").read_text()

    assert "branch: staging" in blueprint
    assert "healthCheckPath: /health/" in blueprint
    assert "name: circuit-bench-staging-db" in blueprint
    assert "ARTIFACT_STORAGE_BACKEND" in blueprint
    assert "value: r2" in blueprint
    assert "value: circuit-bench" in blueprint
    assert "63b9cf4fbc03f05e1dc6c4e33c421d0a.r2.cloudflarestorage.com" in blueprint
    assert "R2_SECRET_ACCESS_KEY" in blueprint
    assert "sync: false" in blueprint
