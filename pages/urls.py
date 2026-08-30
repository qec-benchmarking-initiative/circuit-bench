from django.urls import path

from . import views

app_name = "pages"

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("dev/components/", views.component_gallery, name="component-gallery"),
]
