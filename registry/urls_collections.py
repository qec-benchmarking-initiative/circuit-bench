from django.urls import path

from registry import views_batches, views_collections

app_name = "collections"

urlpatterns = [
    path("", views_collections.collection_list, name="list"),
    path("new/", views_collections.collection_create, name="create"),
    path("batch-upload/", views_batches.batch_create, name="batch-create"),
    path(
        "batch-upload/schema.json",
        views_batches.batch_schema_json,
        name="batch-schema",
    ),
    path(
        "batch-upload/<uuid:batch_id>/",
        views_batches.batch_preview,
        name="batch-preview",
    ),
    path(
        "batch-upload/<uuid:batch_id>/commit/",
        views_batches.batch_commit,
        name="batch-commit",
    ),
    path("<slug:slug>/edit/", views_collections.collection_edit, name="edit"),
    path("<slug:slug>/members/", views_collections.collection_members, name="members"),
    path("<slug:slug>/", views_collections.collection_detail, name="detail"),
]
