from django.urls import include, path

urlpatterns = [
    path("", include("registry.urls_credits")),
    path("", include("pages.urls")),
]
