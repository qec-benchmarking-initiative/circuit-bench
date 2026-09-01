from django.urls import include, path

urlpatterns = [
    path("", include("registry.urls_taxonomy")),
    path("", include("pages.urls")),
]
