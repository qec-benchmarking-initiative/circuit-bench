from django.urls import path

from registry import views_taxonomy

app_name = "taxonomy"

urlpatterns = [
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
