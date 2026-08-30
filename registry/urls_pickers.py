from django.urls import path

from registry import views_pickers

app_name = "pickers"

urlpatterns = [
    path("<slug:picker_key>/", views_pickers.picker_records, name="records"),
]
