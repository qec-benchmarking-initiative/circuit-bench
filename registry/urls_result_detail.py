"""URL fragment mounted by ``registry.urls_results`` under ``/results/``."""

from django.urls import path

from registry import views_result_detail

urlpatterns = [
    path("<uuid:result_id>/", views_result_detail.result_detail, name="detail"),
]
