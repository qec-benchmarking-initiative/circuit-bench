from django.urls import path

from registry import views_noise_models

app_name = "noise-models"

urlpatterns = [
    path("", views_noise_models.noise_model_list, name="list"),
    path("<slug:slug>/", views_noise_models.noise_model_detail, name="detail"),
]
