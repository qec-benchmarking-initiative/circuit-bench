from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount, SocialLogin, SocialToken
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.adapters import DecoderBenchSocialAccountAdapter
from accounts.models import Account, ExternalIdentity
from accounts.services import (
    IdentityConflict,
    provider_identity,
    sync_external_identity,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("_accounts_urlconf"),
]


@pytest.fixture
def _accounts_urlconf(settings):
    settings.ROOT_URLCONF = "tests.accounts.urls"
    settings.SOCIALACCOUNT_ADAPTER = (
        "accounts.adapters.DecoderBenchSocialAccountAdapter"
    )


def make_social_account(
    account: Account,
    *,
    provider: str = "github",
    uid: str = "12345",
    extra_data: dict | None = None,
) -> SocialAccount:
    if extra_data is None:
        extra_data = {
            "login": "ada-decoder",
            "html_url": "https://github.com/ada-decoder",
        }
    return SocialAccount.objects.create(
        user=account,
        provider=provider,
        uid=uid,
        extra_data=extra_data,
    )


def make_external_identity(
    account: Account,
    *,
    provider: str = "github",
    subject: str = "12345",
) -> ExternalIdentity:
    if provider == "github":
        public_identifier = "ada-decoder"
        profile_url = "https://github.com/ada-decoder"
    else:
        public_identifier = subject
        profile_url = f"https://orcid.org/{subject}"
    return ExternalIdentity.objects.create(
        account=account,
        provider=provider,
        provider_subject=subject,
        public_identifier=public_identifier,
        profile_url=profile_url,
    )


def test_login_page_has_plain_post_controls_for_both_providers(client):
    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert "Continue with GitHub" in response.content.decode()
    assert "Continue with ORCID" in response.content.decode()
    assert (
        f'action="{reverse("github_login")}?process=login"' in response.content.decode()
    )
    assert (
        f'action="{reverse("orcid_login")}?process=login"' in response.content.decode()
    )
    assert response.content.decode().count('method="post"') == 2
    assert 'type="password"' not in response.content.decode().casefold()


def test_provider_callback_paths_remain_stable():
    assert reverse("github_callback") == "/accounts/github/login/callback/"
    assert reverse("orcid_callback") == "/accounts/orcid/login/callback/"


def test_identity_list_requires_login(client):
    response = client.get(reverse("account-identity-list"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


def test_identity_list_shows_public_identity_and_missing_provider(client):
    account = Account.objects.create_user(display_name="Ada Decoder")
    identity = make_external_identity(account)
    make_social_account(account)
    client.force_login(account)

    response = client.get(reverse("account-identity-list"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "<title>Settings · Circuit Bench</title>" in content
    assert "<h1>Settings</h1>" in content
    assert '<h2 id="identities-heading">Sign-in identities</h2>' in content
    assert 'href="/profile/">Profile: Ada Decoder</a>' in content
    assert 'class="account-link active" href="/accounts/">Settings</a>' in content
    assert identity.public_identifier in content
    assert "Link ORCID" in content
    assert "demonstration record" not in content
    assert response.context["identities"][0].can_unlink is False


def test_identity_list_does_not_treat_unconnected_projection_as_fallback(client):
    account = Account.objects.create_user(display_name="Ada Decoder")
    make_external_identity(account)
    make_external_identity(
        account,
        provider="orcid",
        subject="0000-0002-1825-0097",
    )
    make_social_account(account)
    client.force_login(account)

    response = client.get(reverse("account-identity-list"))

    identities = {
        identity.provider: identity for identity in response.context["identities"]
    }
    assert identities["github"].oauth_connected is True
    assert identities["github"].can_unlink is False
    assert identities["orcid"].oauth_connected is False
    assert identities["orcid"].can_unlink is True


def test_unlink_last_identity_is_rejected_server_side(client):
    account = Account.objects.create_user(display_name="Ada Decoder")
    identity = make_external_identity(account)
    social_account = make_social_account(account)
    client.force_login(account)

    response = client.post(
        reverse("account-identity-unlink", args=[identity.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "cannot unlink your last" in response.content.decode().casefold()
    assert ExternalIdentity.objects.filter(pk=identity.pk).exists()
    assert SocialAccount.objects.filter(pk=social_account.pk).exists()


def test_unlink_removes_projection_oauth_record_and_legacy_token(client):
    account = Account.objects.create_user(display_name="Ada Decoder")
    github_identity = make_external_identity(account)
    make_external_identity(
        account,
        provider="orcid",
        subject="0000-0002-1825-0097",
    )
    make_social_account(
        account,
        provider="orcid",
        uid="0000-0002-1825-0097",
        extra_data={
            "orcid-identifier": {
                "path": "0000-0002-1825-0097",
                "uri": "https://orcid.org/0000-0002-1825-0097",
            }
        },
    )
    social_account = make_social_account(account)
    token = SocialToken.objects.create(account=social_account, token="must-not-remain")
    client.force_login(account)

    response = client.post(
        reverse("account-identity-unlink", args=[github_identity.pk]),
    )

    assert response.status_code == 302
    assert not ExternalIdentity.objects.filter(pk=github_identity.pk).exists()
    assert not SocialAccount.objects.filter(pk=social_account.pk).exists()
    assert not SocialToken.objects.filter(pk=token.pk).exists()


def test_unlink_rejects_unconnected_projection_as_fallback_login(client):
    account = Account.objects.create_user(display_name="Ada Decoder")
    github_identity = make_external_identity(account)
    make_external_identity(
        account,
        provider="orcid",
        subject="0000-0002-1825-0097",
    )
    github_account = make_social_account(account)
    client.force_login(account)

    response = client.post(
        reverse("account-identity-unlink", args=[github_identity.pk]),
        follow=True,
    )

    assert response.status_code == 200
    assert "another working sign-in provider" in response.content.decode()
    assert ExternalIdentity.objects.filter(pk=github_identity.pk).exists()
    assert SocialAccount.objects.filter(pk=github_account.pk).exists()


def test_provider_projection_uses_orcid_path_and_public_profile():
    account = Account.objects.create_user(display_name="Ada Decoder")
    social_account = make_social_account(
        account,
        provider="orcid",
        uid="0000-0002-1825-0097",
        extra_data={
            "orcid-identifier": {
                "path": "0000-0002-1825-0097",
                "uri": "https://orcid.org/0000-0002-1825-0097",
            }
        },
    )

    projected = provider_identity(social_account)

    assert projected.public_identifier == "0000-0002-1825-0097"
    assert projected.profile_url == "https://orcid.org/0000-0002-1825-0097"


def test_sync_creates_public_projection_and_deletes_tokens():
    account = Account.objects.create_user(display_name="Ada Decoder")
    social_account = make_social_account(account)
    token = SocialToken.objects.create(account=social_account, token="must-not-remain")
    authenticated_at = timezone.now()

    identity = sync_external_identity(
        social_account,
        authenticated_at=authenticated_at,
    )

    assert identity.account == account
    assert identity.provider_subject == social_account.uid
    assert identity.public_identifier == "ada-decoder"
    assert identity.last_authenticated_at == authenticated_at
    assert not SocialToken.objects.filter(pk=token.pk).exists()


def test_adapter_save_user_creates_account_oauth_record_and_projection():
    request = RequestFactory().post("/accounts/github/login/callback/")
    request.session = {}
    sociallogin = SocialLogin(
        user=Account(display_name="Ada Decoder"),
        account=SocialAccount(
            provider="github",
            uid="12345",
            extra_data={
                "login": "ada-decoder",
                "html_url": "https://github.com/ada-decoder",
            },
        ),
    )

    account = DecoderBenchSocialAccountAdapter(request).save_user(
        request,
        sociallogin,
    )

    assert account.pk is not None
    assert account.has_usable_password() is False
    assert SocialAccount.objects.filter(user=account, uid="12345").exists()
    assert ExternalIdentity.objects.filter(
        account=account,
        provider="github",
        provider_subject="12345",
    ).exists()
    assert not SocialToken.objects.exists()


def test_sync_refuses_provider_subject_owned_by_another_account():
    first_account = Account.objects.create_user(display_name="First")
    second_account = Account.objects.create_user(display_name="Second")
    make_external_identity(first_account)
    social_account = make_social_account(second_account)

    with pytest.raises(IdentityConflict, match="another account"):
        sync_external_identity(social_account)

    assert not ExternalIdentity.objects.filter(account=second_account).exists()


def test_adapter_rejects_provider_email_collision_without_merging():
    owner = Account.objects.create_user(display_name="Existing")
    EmailAddress.objects.create(
        user=owner,
        email="SCIENTIST@example.org",
        verified=True,
        primary=True,
    )
    request = RequestFactory().get("/accounts/github/login/callback/")
    request.user = AnonymousUser()
    candidate = Account(display_name="Candidate")
    sociallogin = SocialLogin(
        user=candidate,
        account=SocialAccount(
            provider="github",
            uid="99999",
            extra_data={"email": "scientist@example.org"},
        ),
        email_addresses=[EmailAddress(email="scientist@example.org")],
    )
    sociallogin.state = {"process": "login"}

    with pytest.raises(ImmediateHttpResponse) as caught:
        DecoderBenchSocialAccountAdapter(request).pre_social_login(
            request,
            sociallogin,
        )

    assert caught.value.response.status_code == 409
    assert Account.objects.count() == 1


def test_adapter_rejects_connecting_identity_owned_by_another_user():
    owner = Account.objects.create_user(display_name="Existing")
    requester = Account.objects.create_user(display_name="Requester")
    social_account = make_social_account(owner)
    make_external_identity(owner)
    request = RequestFactory().get("/accounts/github/login/callback/")
    request.user = requester
    sociallogin = SocialLogin(user=owner, account=social_account)
    sociallogin.state = {"process": "connect"}

    with pytest.raises(ImmediateHttpResponse) as caught:
        DecoderBenchSocialAccountAdapter(request).pre_social_login(
            request,
            sociallogin,
        )

    assert caught.value.response.status_code == 409
    assert social_account.user == owner


def test_successful_authentication_updates_projection_timestamp():
    account = Account.objects.create_user(display_name="Ada Decoder")
    social_account = make_social_account(account)
    identity = make_external_identity(account)
    old_timestamp = timezone.now() - timedelta(days=2)
    identity.last_authenticated_at = old_timestamp
    identity.save(update_fields=["last_authenticated_at"])

    from allauth.account.signals import authentication_step_completed

    authentication_step_completed.send(
        sender=Account,
        request=RequestFactory().get("/"),
        user=account,
        method="socialaccount",
        provider="github",
        uid=social_account.uid,
    )

    identity.refresh_from_db()
    assert identity.last_authenticated_at > old_timestamp


def test_populate_user_derives_required_display_name_from_provider_payload():
    request = RequestFactory().get("/")
    sociallogin = SocialLogin(
        user=Account(),
        account=SocialAccount(
            provider="github",
            uid="12345",
            extra_data={"login": "ada-decoder"},
        ),
    )

    user = DecoderBenchSocialAccountAdapter(request).populate_user(
        request,
        sociallogin,
        {"name": "Ada Decoder"},
    )

    assert user.display_name == "Ada Decoder"
    assert user.has_usable_password() is False


@override_settings(SOCIALACCOUNT_STORE_TOKENS=False)
def test_configuration_does_not_store_new_social_tokens(settings):
    assert settings.SOCIALACCOUNT_STORE_TOKENS is False
