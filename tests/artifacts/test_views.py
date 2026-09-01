import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import include, path, reverse

from accounts.models import Account
from registry.models import Artifact, SchemaRelease
from registry.services.artifacts import local_artifact_path

urlpatterns = [
    path(
        "artifacts/",
        include(
            ("registry.urls_artifacts", "artifacts"),
            namespace="artifacts",
        ),
    ),
    path("", include("pages.urls")),
]


@pytest.fixture(autouse=True)
def artifact_urlconf(settings):
    settings.ROOT_URLCONF = __name__


@pytest.fixture
def uploader(db):
    return Account.objects.create_user(display_name="Web uploader")


@pytest.mark.django_db
def test_development_upload_inspection_and_deduplication(
    client, settings, tmp_path, uploader
):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path / "media"
    client.force_login(uploader)
    content = b"small artifact\n"

    first_response = client.post(
        reverse("artifacts:upload"),
        {
            "file": SimpleUploadedFile(
                "../first.txt", content, content_type="text/plain"
            ),
            "expected_byte_size": len(content),
        },
    )
    assert first_response.status_code == 302
    artifact = Artifact.objects.get()
    assert first_response.url == reverse(
        "artifacts:detail", kwargs={"artifact_id": artifact.id}
    )

    second_response = client.post(
        reverse("artifacts:upload"),
        {"file": SimpleUploadedFile("second.txt", content)},
        follow=True,
    )
    assert second_response.status_code == 200
    assert b"Reused the existing file" in second_response.content
    assert Artifact.objects.count() == 1
    assert b"Integrity verified" in second_response.content


@pytest.mark.django_db
def test_download_returns_verified_bytes_and_integrity_headers(
    client, settings, tmp_path, uploader
):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path / "media"
    client.force_login(uploader)
    client.post(
        reverse("artifacts:upload"),
        {"file": SimpleUploadedFile("measurement.json", b'{"shots":10}\n')},
    )
    artifact = Artifact.objects.get()

    response = client.get(
        reverse("artifacts:download", kwargs={"artifact_id": artifact.id})
    )

    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b'{"shots":10}\n'
    assert response["ETag"] == f'"{artifact.sha256}"'
    assert response["Content-Length"] == str(artifact.byte_size)
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "measurement.json" in response["Content-Disposition"]


@pytest.mark.django_db
def test_corruption_is_visible_and_download_is_refused(
    client, settings, tmp_path, uploader
):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path / "media"
    client.force_login(uploader)
    client.post(
        reverse("artifacts:upload"),
        {"file": SimpleUploadedFile("immutable.bin", b"correct")},
    )
    artifact = Artifact.objects.get()
    local_artifact_path(artifact).write_bytes(b"wrong")

    detail = client.get(
        reverse("artifacts:detail", kwargs={"artifact_id": artifact.id})
    )
    download = client.get(
        reverse("artifacts:download", kwargs={"artifact_id": artifact.id})
    )

    assert detail.status_code == 200
    assert b"Integrity failed" in detail.content
    assert download.status_code == 409
    assert b"integrity verification failed" in download.content


@pytest.mark.django_db
def test_inspection_is_development_only_but_download_remains_available(
    client, settings, tmp_path, uploader
):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path / "media"
    client.force_login(uploader)
    client.post(
        reverse("artifacts:upload"),
        {"file": SimpleUploadedFile("public.bin", b"download")},
    )
    artifact = Artifact.objects.get()
    settings.DEBUG = False

    assert client.get(reverse("artifacts:index")).status_code == 404
    response = client.get(
        reverse("artifacts:download", kwargs={"artifact_id": artifact.id})
    )
    assert response.status_code == 200
    response.close()


@pytest.mark.django_db
def test_schema_release_permanent_page_and_downloads_are_public(
    client, settings, tmp_path, uploader
):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path / "media"
    client.force_login(uploader)
    for filename, content in (
        ("0.1.schema.json", b'{"type":"object"}\n'),
        ("0.1.md", b"# Definitions\n"),
    ):
        client.post(
            reverse("artifacts:upload"),
            {"file": SimpleUploadedFile(filename, content)},
        )
    schema_artifact, definitions_artifact = Artifact.objects.order_by("created_at")
    release = SchemaRelease.objects.create(
        record_type="decoder",
        version="test-public",
        json_schema_artifact=schema_artifact,
        definitions_artifact=definitions_artifact,
        permanent_url=(
            "https://registry.example/artifacts/schema-releases/decoder/test-public/"
        ),
        state="draft",
    )
    settings.DEBUG = False

    response = client.get(
        reverse(
            "artifacts:schema-release-detail",
            kwargs={
                "record_type": release.record_type,
                "version": release.version,
            },
        )
    )

    assert response.status_code == 200
    assert (
        reverse("artifacts:download", args=[schema_artifact.id])
        in response.content.decode()
    )
    assert (
        reverse("artifacts:download", args=[definitions_artifact.id])
        in response.content.decode()
    )


@pytest.mark.django_db
def test_anonymous_development_upload_redirects_to_login(client, settings):
    settings.DEBUG = True
    response = client.get(reverse("artifacts:upload"))
    assert response.status_code == 302
    assert response.url.startswith("/accounts/login/")
