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
    path("circuits/", include("registry.urls_circuits", namespace="circuits")),
    path("machines/", include("registry.urls_machines", namespace="machines")),
    path(
        "noise-models/",
        include("registry.urls_noise_models", namespace="noise-models"),
    ),
    path("pickers/", include("registry.urls_pickers", namespace="pickers")),
    path("artifacts/", include(artifact_patterns, namespace="artifacts")),
    path("", include("pages.urls")),
]
