from __future__ import annotations

from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.db import transaction
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .services import (
    IdentityConflict,
    assert_social_login_does_not_merge,
    sync_external_identity,
)


class DecoderBenchSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Keep OAuth provider records separate and refuse inferred account merges."""

    def pre_social_login(self, request, sociallogin) -> None:
        try:
            assert_social_login_does_not_merge(request, sociallogin)
        except IdentityConflict as error:
            raise ImmediateHttpResponse(
                render(
                    request,
                    "account/identity_conflict.html",
                    {"identity_error": str(error)},
                    status=409,
                )
            ) from error

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        extra_data = sociallogin.account.extra_data or {}
        display_name = (
            data.get("name")
            or " ".join(
                part for part in (data.get("first_name"), data.get("last_name")) if part
            )
            or extra_data.get("login")
            or str(sociallogin.account.uid)
        )
        user.display_name = str(display_name).strip()[:200]
        user.set_unusable_password()
        return user

    @transaction.atomic
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form=form)
        sync_external_identity(
            sociallogin.account,
            authenticated_at=timezone.now(),
        )
        return user

    def validate_disconnect(self, account, accounts) -> None:
        # allauth checks its SocialAccount count first. Mirror the invariant in
        # the application's public identity projection as well.
        has_other_identity = (
            account.user.external_identities.exclude(
                provider=account.provider,
                provider_subject=account.uid,
            ).exists()
        )
        if not has_other_identity:
            raise self.validation_error("disconnect_last")

    def get_connect_redirect_url(self, request, socialaccount) -> str:
        try:
            return reverse("account-identity-list")
        except NoReverseMatch:
            return super().get_connect_redirect_url(request, socialaccount)
