from django.urls import path

from registry import views_circuits

app_name = "circuits"

urlpatterns = [
    path("", views_circuits.circuit_list, name="list"),
    path("<slug:slug>/", views_circuits.circuit_detail, name="detail"),
]
