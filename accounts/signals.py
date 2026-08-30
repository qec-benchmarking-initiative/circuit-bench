from allauth.account.signals import authentication_step_completed
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.signals import social_account_added, social_account_removed
from django.dispatch import receiver

from .models import ExternalIdentity
from .services import mark_authenticated


@receiver(
    social_account_added,
    dispatch_uid="decoderbench_sync_added_external_identity",
)
def sync_added_external_identity(sender, request, sociallogin, **kwargs) -> None:
    mark_authenticated(sociallogin.account)


@receiver(
    authentication_step_completed,
    dispatch_uid="decoderbench_sync_authenticated_external_identity",
)
def sync_authenticated_external_identity(
    sender,
    request,
    user,
    method,
    provider=None,
    uid=None,
    **kwargs,
) -> None:
    if method != "socialaccount" or not provider or uid is None:
        return
    social_account = SocialAccount.objects.filter(
        user=user,
        provider=provider,
        uid=str(uid),
    ).first()
    if social_account:
        mark_authenticated(social_account)


@receiver(
    social_account_removed,
    dispatch_uid="decoderbench_remove_external_identity",
)
def remove_external_identity(sender, request, socialaccount, **kwargs) -> None:
    ExternalIdentity.objects.filter(
        account=socialaccount.user,
        provider=socialaccount.provider,
        provider_subject=socialaccount.uid,
    ).delete()
