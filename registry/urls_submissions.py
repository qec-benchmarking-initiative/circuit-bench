from django.urls import path

from registry import views_result_batches, views_submissions

app_name = "submissions"

urlpatterns = [
    path(
        "submit/result/batch/", views_result_batches.create, name="result-batch-create"
    ),
    path(
        "submit/result/batch/schema.json",
        views_result_batches.schema,
        name="result-batch-schema",
    ),
    path(
        "submit/result/batch/<uuid:batch_id>/",
        views_result_batches.preview,
        name="result-batch-preview",
    ),
    path(
        "submit/result/batch/<uuid:batch_id>/commit/",
        views_result_batches.commit,
        name="result-batch-commit",
    ),
    path("submit/", views_submissions.submission_hub, name="hub"),
    path(
        "submit/preview/<uuid:preview_id>/",
        views_submissions.submission_preview,
        name="preview",
    ),
    path(
        "submit/preview/<uuid:preview_id>/submit/",
        views_submissions.submission_commit,
        name="commit",
    ),
    path(
        "submit/<str:kind>/schema.json",
        views_submissions.submission_schema,
        name="schema",
    ),
    path("submit/<str:kind>/", views_submissions.submission_create, name="create"),
    path("profile/", views_submissions.profile, name="profile"),
    path("review/", views_submissions.review_dashboard, name="review"),
    path(
        "review/daily-quote/rotate/",
        views_submissions.rotate_daily_quote,
        name="rotate-daily-quote",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/",
        views_submissions.submission_record,
        name="record",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/edit/",
        views_submissions.submission_edit,
        name="edit",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/successor/",
        views_submissions.submission_successor,
        name="successor",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/withdraw/",
        views_submissions.submission_withdraw,
        name="withdraw",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/approve/",
        views_submissions.review_approve,
        name="approve",
    ),
]
