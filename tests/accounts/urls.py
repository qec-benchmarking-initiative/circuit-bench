from django.urls import include, path

urlpatterns = [
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("allauth.urls")),
    path("", include("pages.urls")),
]
