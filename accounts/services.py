from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialToken
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Account, ExternalIdentity


class IdentityConflict(Exception):
    """An OAuth identity cannot be attached without merging two accounts."""


@dataclass(frozen=True)
class ProviderIdentity:
    provider: str
    subject: str
    public_identifier: str
    profile_url: str


def provider_identity(social_account: SocialAccount) -> ProviderIdentity:
    """Translate allauth provider data into the stable public projection."""
    provider = social_account.provider
    subject = str(social_account.uid)
    extra_data = social_account.extra_data or {}

    if provider == ExternalIdentity.Provider.GITHUB:
        public_identifier = str(extra_data.get("login") or subject)
        profile_url = str(
            extra_data.get("html_url")
            or f"https://github.com/{quote(public_identifier)}"
        )
    elif provider == ExternalIdentity.Provider.ORCID:
        identifier = extra_data.get("orcid-identifier") or {}
        public_identifier = str(identifier.get("path") or subject)
        profile_url = str(
            identifier.get("uri") or f"https://orcid.org/{quote(public_identifier)}"
        )
    else:
        raise IdentityConflict(
            "Circuit Bench only accepts GitHub and ORCID identities."
        )

    return ProviderIdentity(
        provider=provider,
        subject=subject,
        public_identifier=public_identifier,
        profile_url=profile_url,
    )


def social_login_emails(sociallogin) -> set[str]:
    """Return normalized provider emails used only for collision detection."""
    emails = {
        address.email.strip().casefold()
        for address in sociallogin.email_addresses
        if address.email and address.email.strip()
    }
    extra_email = (sociallogin.account.extra_data or {}).get("email")
    if isinstance(extra_email, str) and extra_email.strip():
        emails.add(extra_email.strip().casefold())
    return emails


def assert_social_login_does_not_merge(request, sociallogin) -> None:
    """Reject identity/email collisions rather than guessing account ownership."""
    identity = provider_identity(sociallogin.account)
    process = sociallogin.state.get("process", "login")

    intended_account = None
    if process == "connect" and request.user.is_authenticated:
        intended_account = request.user
        if sociallogin.is_existing and sociallogin.user != intended_account:
            raise IdentityConflict("That provider identity belongs to another account.")
    elif sociallogin.is_existing:
        intended_account = sociallogin.user

    mapped_identity = (
        ExternalIdentity.objects.select_related("account")
        .filter(provider=identity.provider, provider_subject=identity.subject)
        .first()
    )
    if mapped_identity and (
        intended_account is None or mapped_identity.account_id != intended_account.pk
    ):
        raise IdentityConflict("That provider identity belongs to another account.")

    if intended_account is not None:
        different_subject_exists = (
            ExternalIdentity.objects.filter(
                account=intended_account,
                provider=identity.provider,
            )
            .exclude(provider_subject=identity.subject)
            .exists()
        )
        if different_subject_exists:
            raise IdentityConflict(
                "This account already has a different identity for that provider."
            )

    emails = social_login_emails(sociallogin)
    if not emails:
        return

    email_query = Q()
    for email in emails:
        email_query |= Q(email__iexact=email)
    email_owners = EmailAddress.objects.filter(email_query)
    if intended_account is not None:
        email_owners = email_owners.exclude(user=intended_account)
    if email_owners.exists():
        raise IdentityConflict("That provider email belongs to another account.")


@transaction.atomic
def sync_external_identity(
    social_account: SocialAccount,
    *,
    authenticated_at=None,
) -> ExternalIdentity:
    """Synchronize allauth bookkeeping into the public identity table.

    ``SocialAccount`` remains the private OAuth protocol record. The explicit
    ``ExternalIdentity`` is the stable, public record used by the site. They
    share only provider/subject keys; no OAuth token is copied or retained.
    """
    identity = provider_identity(social_account)
    account = Account.objects.select_for_update().get(pk=social_account.user_id)

    same_subject = (
        ExternalIdentity.objects.select_for_update()
        .filter(provider=identity.provider, provider_subject=identity.subject)
        .first()
    )
    if same_subject and same_subject.account_id != account.pk:
        raise IdentityConflict("That provider identity belongs to another account.")

    same_provider = (
        ExternalIdentity.objects.select_for_update()
        .filter(account=account, provider=identity.provider)
        .first()
    )
    if same_provider and same_provider.provider_subject != identity.subject:
        raise IdentityConflict(
            "This account already has a different identity for that provider."
        )

    defaults = {
        "account": account,
        "public_identifier": identity.public_identifier,
        "profile_url": identity.profile_url,
    }
    if authenticated_at is not None:
        defaults["last_authenticated_at"] = authenticated_at

    external_identity, _ = ExternalIdentity.objects.update_or_create(
        provider=identity.provider,
        provider_subject=identity.subject,
        defaults=defaults,
    )

    # SOCIALACCOUNT_STORE_TOKENS=False prevents creation. This cleanup is a
    # defence against legacy rows or future configuration mistakes.
    SocialToken.objects.filter(account=social_account).delete()
    return external_identity


@transaction.atomic
def unlink_external_identity(*, account: Account, identity_id) -> bool:
    """Remove one identity and matching OAuth bookkeeping, never the last."""
    locked_account = Account.objects.select_for_update().get(pk=account.pk)
    identities = ExternalIdentity.objects.select_for_update().filter(
        account=locked_account
    )
    identity = identities.filter(pk=identity_id).first()
    if identity is None:
        return False
    if identities.count() <= 1:
        raise IdentityConflict("You cannot unlink your last sign-in identity.")

    social_account = (
        SocialAccount.objects.select_for_update()
        .filter(provider=identity.provider, uid=identity.provider_subject)
        .first()
    )
    if social_account and social_account.user_id != locked_account.pk:
        raise IdentityConflict("The provider records disagree about account ownership.")
    if social_account and not (
        SocialAccount.objects.select_for_update()
        .filter(user=locked_account)
        .exclude(pk=social_account.pk)
        .exists()
    ):
        raise IdentityConflict(
            "Link another working sign-in provider before unlinking this one."
        )

    identity.delete()
    if social_account:
        SocialToken.objects.filter(account=social_account).delete()
        social_account.delete()
    return True


def mark_authenticated(social_account: SocialAccount) -> ExternalIdentity:
    return sync_external_identity(social_account, authenticated_at=timezone.now())
