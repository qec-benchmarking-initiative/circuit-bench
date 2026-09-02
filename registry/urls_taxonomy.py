from django.urls import path

from registry import views_ecz, views_tags, views_taxonomy

app_name = "taxonomy"

urlpatterns = [
    path("ecz/<str:code_id>/", views_ecz.term_detail, name="ecz-detail"),
    path("taxonomy/ecz/", views_ecz.sync_status, name="ecz-status"),
    path(
        "taxonomy/ecz/mappings/new/",
        views_ecz.mapping_create,
        name="ecz-mapping-create",
    ),
    path(
        "taxonomy/ecz/mappings/<uuid:mapping_id>/revoke/",
        views_ecz.mapping_revoke,
        name="ecz-mapping-revoke",
    ),
    path(
        "tags/<str:namespace>/<slug:slug>/",
        views_tags.tag_detail,
        name="tag-detail",
    ),
    path(
        "tags/<str:namespace>/<slug:slug>/edit/",
        views_tags.tag_edit,
        name="tag-edit",
    ),
    path(
        "tags/<str:namespace>/<slug:slug>/delete/",
        views_tags.tag_delete,
        name="tag-delete",
    ),
    path(
        "taxonomy/tags/create.json",
        views_tags.create_tag_json,
        name="tag-create-json",
    ),
    path("taxonomy/tags/new/", views_taxonomy.custom_tag_create, name="tag-create"),
    path(
        "taxonomy/tags/new/preview/<uuid:preview_id>/",
        views_taxonomy.custom_tag_preview,
        name="tag-preview",
    ),
    path(
        "taxonomy/noise-models/new/",
        views_taxonomy.noise_model_submit,
        name="noise-model-create",
    ),
    path(
        "taxonomy/noise-models/new/preview/<uuid:preview_id>/",
        views_taxonomy.noise_model_preview,
        name="noise-model-preview",
    ),
    path(
        "taxonomy/noise-models/<uuid:noise_model_id>/candidate/",
        views_taxonomy.noise_model_candidate,
        name="noise-model-candidate",
    ),
    path("taxonomy/curation/", views_taxonomy.curation_queue, name="curation"),
    path(
        "taxonomy/curation/tags/<uuid:tag_id>/promote/",
        views_taxonomy.tag_promote,
        name="tag-promote",
    ),
    path(
        "taxonomy/curation/tags/<uuid:tag_id>/deprecate/",
        views_taxonomy.tag_deprecate,
        name="tag-deprecate",
    ),
    path(
        "taxonomy/curation/noise-models/<uuid:noise_model_id>/approve/",
        views_taxonomy.noise_model_approve,
        name="noise-model-approve",
    ),
    path(
        "taxonomy/curation/noise-models/<uuid:noise_model_id>/promote/",
        views_taxonomy.noise_model_promote,
        name="noise-model-promote",
    ),
    path(
        "taxonomy/curation/noise-models/<uuid:noise_model_id>/deprecate/",
        views_taxonomy.noise_model_deprecate,
        name="noise-model-deprecate",
    ),
]
