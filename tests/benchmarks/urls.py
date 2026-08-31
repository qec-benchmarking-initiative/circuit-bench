from django.urls import include, path

urlpatterns = [
    path(
        "benchmarks/",
        include("registry.urls_benchmarks", namespace="benchmarks"),
    ),
    path("artifacts/", include("registry.urls_artifacts", namespace="artifacts")),
    path("circuits/", include("registry.urls_circuits", namespace="circuits")),
    path("decoders/", include("registry.urls_decoders", namespace="decoders")),
    path("machines/", include("registry.urls_machines", namespace="machines")),
    path(
        "noise-models/",
        include("registry.urls_noise_models", namespace="noise-models"),
    ),
    path("pickers/", include("registry.urls_pickers", namespace="pickers")),
    path("results/", include("registry.urls_results", namespace="results")),
    path("", include("pages.urls", namespace="pages")),
]
