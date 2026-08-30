from django.http import HttpResponse
from django.urls import include, path


def artifact_download_stub(request, artifact_id):
    return HttpResponse(str(artifact_id))


artifact_patterns = (
    [
        path(
            "<uuid:artifact_id>/download/",
            artifact_download_stub,
            name="download",
        )
    ],
    "artifacts",
)

urlpatterns = [
    path("decoders/", include("registry.urls_decoders", namespace="decoders")),
    path("artifacts/", include(artifact_patterns, namespace="artifacts")),
    path("", include("pages.urls")),
]
