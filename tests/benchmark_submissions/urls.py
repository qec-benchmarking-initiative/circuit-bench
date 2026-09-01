from django.urls import include, path

urlpatterns = [
    path("", include("registry.urls_benchmark_submissions")),
    path("artifacts/", include("registry.urls_artifacts")),
    path("benchmarks/", include("registry.urls_benchmarks")),
    path("", include("pages.urls")),
]
