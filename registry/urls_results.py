from django.urls import path

from registry import views_results
from registry.urls_result_api import urlpatterns as api_urlpatterns
from registry.urls_result_detail import urlpatterns as detail_urlpatterns

app_name = "results"

urlpatterns = [
    *api_urlpatterns,
    *detail_urlpatterns,
    path("", views_results.result_list, name="list"),
]
