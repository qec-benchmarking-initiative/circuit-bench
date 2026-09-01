from django.urls import path

from registry import views_review_decisions

app_name = "review-decisions"

urlpatterns = [
    path(
        "review/<str:kind>/<uuid:record_id>/request-changes/",
        views_review_decisions.request_changes_view,
        name="request-changes",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/reject/",
        views_review_decisions.reject_view,
        name="reject",
    ),
    path(
        "review/<str:kind>/<uuid:record_id>/resubmit/",
        views_review_decisions.resubmit_view,
        name="resubmit",
    ),
]
