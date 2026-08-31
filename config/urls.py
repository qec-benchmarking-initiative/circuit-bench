from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("artifacts/", include("registry.urls_artifacts")),
    path("benchmarks/", include("registry.urls_benchmarks")),
    path("circuits/", include("registry.urls_circuits")),
    path("decoders/", include("registry.urls_decoders")),
    path("machines/", include("registry.urls_machines")),
    path("noise-models/", include("registry.urls_noise_models")),
    path("pickers/", include("registry.urls_pickers")),
    path("results/", include("registry.urls_results")),
    path("", include("pages.urls")),
]
