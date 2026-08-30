from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("artifacts/", include("registry.urls_artifacts")),
    path("circuits/", include("registry.urls_circuits")),
    path("decoders/", include("registry.urls_decoders")),
    path("noise-models/", include("registry.urls_noise_models")),
    path("", include("pages.urls")),
]
