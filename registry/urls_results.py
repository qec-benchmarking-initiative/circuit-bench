from django.urls import path

from registry import views_results

app_name = "results"

urlpatterns = [path("", views_results.result_list, name="list")]
