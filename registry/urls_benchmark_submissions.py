from django.urls import path

from registry import views_benchmark_submissions

app_name = "benchmark-submissions"

urlpatterns = [
    path(
        "submit/benchmark/", views_benchmark_submissions.benchmark_create, name="create"
    ),
    path(
        "submit/benchmark/preview/<uuid:preview_id>/",
        views_benchmark_submissions.benchmark_preview,
        name="preview",
    ),
    path(
        "submit/benchmark/preview/<uuid:preview_id>/submit/",
        views_benchmark_submissions.benchmark_commit,
        name="commit",
    ),
    path(
        "submit/benchmark-attempt/",
        views_benchmark_submissions.attempt_create,
        name="attempt-create",
    ),
    path(
        "review/benchmarks/",
        views_benchmark_submissions.benchmark_review_queue,
        name="review",
    ),
    path(
        "review/benchmark/<uuid:record_id>/",
        views_benchmark_submissions.benchmark_candidate,
        name="candidate",
    ),
    path(
        "review/benchmark/<uuid:record_id>/approve/",
        views_benchmark_submissions.benchmark_approve,
        name="approve",
    ),
    path(
        "review/benchmark/<uuid:record_id>/promote/",
        views_benchmark_submissions.benchmark_promote,
        name="promote",
    ),
]
