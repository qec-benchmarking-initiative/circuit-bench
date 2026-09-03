from django.urls import path

from registry import views_bulk

app_name = "bulk"

urlpatterns = [
    path("bulk/preview/", views_bulk.bulk_preview, name="preview"),
    path("bulk/commit/", views_bulk.bulk_commit, name="commit"),
]
