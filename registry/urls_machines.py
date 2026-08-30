from django.urls import path

from registry import views_machines

app_name = "machines"

urlpatterns = [path("<slug:slug>/", views_machines.machine_detail, name="detail")]
