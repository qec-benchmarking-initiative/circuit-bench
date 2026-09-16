from django.urls import path

from registry import views_batches, views_result_batches

app_name = "api-0.1"

urlpatterns = [
    path(
        "schemas/result-batch.json",
        views_result_batches.schema,
        name="result-batch-schema",
    ),
    path(
        "result-batches/validate/",
        views_result_batches.api_validate,
        name="result-batch-validate",
    ),
    path(
        "result-batches/<uuid:batch_id>/commit/",
        views_result_batches.api_commit,
        name="result-batch-commit",
    ),
    path("openapi.json", views_batches.openapi_json, name="openapi"),
    path(
        "schemas/circuit-batch.json",
        views_batches.batch_schema_json,
        name="batch-schema",
    ),
    path(
        "circuit-batches/validate/",
        views_batches.api_batch_validate,
        name="batch-validate",
    ),
    path(
        "circuit-batches/<uuid:batch_id>/commit/",
        views_batches.api_batch_commit,
        name="batch-commit",
    ),
]
