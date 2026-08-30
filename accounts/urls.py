from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login, name="account_login"),
    path("", views.identity_list, name="account-identity-list"),
    path(
        "identities/<uuid:identity_id>/unlink/",
        views.identity_unlink,
        name="account-identity-unlink",
    ),
]
