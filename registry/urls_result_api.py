from django.urls import path

from registry import views_result_api

urlpatterns = [
    path(
        "api/v0.1/results.json", views_result_api.result_records_json, name="api-json"
    ),
    path("api/v0.1/results.csv", views_result_api.result_records_csv, name="api-csv"),
    path(
        "api/v0.1/schema.json", views_result_api.result_record_schema, name="api-schema"
    ),
]
