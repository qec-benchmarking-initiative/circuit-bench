from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("artifacts/", include("registry.urls_artifacts")),
    path("api/0.1/", include("registry.urls_api")),
    path("benchmarks/", include("registry.urls_benchmarks")),
    path("circuits/", include("registry.urls_circuits")),
    path("circuit-collections/", include("registry.urls_collections")),
    path("decoders/", include("registry.urls_decoders")),
    path("machines/", include("registry.urls_machines")),
    path("noise-models/", include("registry.urls_noise_models")),
    path("pickers/", include("registry.urls_pickers")),
    path("results/", include("registry.urls_results")),
    path("", include("registry.urls_bulk")),
    path("", include("registry.urls_credits")),
    path("", include("registry.urls_benchmark_submissions")),
    path("", include("registry.urls_review_decisions")),
    path("", include("registry.urls_taxonomy")),
    path("", include("registry.urls_submissions")),
    path("", include("pages.urls")),
]
