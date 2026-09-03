from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login, name="account_login"),
    path(
        "development-login/<uuid:account_id>/",
        views.development_login,
        name="account-development-login",
    ),
    path("", views.identity_list, name="account-identity-list"),
    path("api-tokens/new/", views.api_token_create, name="account-api-token-create"),
    path(
        "api-tokens/<uuid:token_id>/revoke/",
        views.api_token_revoke,
        name="account-api-token-revoke",
    ),
    path(
        "identities/<uuid:identity_id>/unlink/",
        views.identity_unlink,
        name="account-identity-unlink",
    ),
]
