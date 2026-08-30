from django.urls import path

from registry import views_artifacts

app_name = "artifacts"

urlpatterns = [
    path("", views_artifacts.artifact_index, name="index"),
    path("upload/", views_artifacts.artifact_upload, name="upload"),
    path(
        "schema-releases/<str:record_type>/<str:version>/",
        views_artifacts.schema_release_detail,
        name="schema-release-detail",
    ),
    path("<uuid:artifact_id>/", views_artifacts.artifact_detail, name="detail"),
    path(
        "<uuid:artifact_id>/download/",
        views_artifacts.artifact_download,
        name="download",
    ),
]
