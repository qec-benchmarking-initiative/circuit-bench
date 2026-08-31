from django.urls import path

from registry import views_benchmarks

app_name = "benchmarks"

urlpatterns = [
    path("", views_benchmarks.benchmark_list, name="list"),
    path("<slug:slug>/", views_benchmarks.benchmark_detail, name="detail"),
]
