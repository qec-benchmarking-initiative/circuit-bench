from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required, login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .models import ExternalIdentity
from .services import IdentityConflict, unlink_external_identity

PROVIDERS = (
    {"id": ExternalIdentity.Provider.GITHUB, "label": "GitHub"},
    {"id": ExternalIdentity.Provider.ORCID, "label": "ORCID"},
)


@login_not_required
def login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("account-identity-list")
    return render(request, "account/login.html")


@login_required
def identity_list(request: HttpRequest) -> HttpResponse:
    identities = list(request.user.external_identities.order_by("provider"))
    connected_providers = {identity.provider for identity in identities}
    oauth_keys = set(
        SocialAccount.objects.filter(user=request.user).values_list(
            "provider", "uid"
        )
    )
    for identity in identities:
        identity.oauth_connected = (
            identity.provider,
            identity.provider_subject,
        ) in oauth_keys
        identity.can_unlink = len(identities) > 1 and (
            not identity.oauth_connected or len(oauth_keys) > 1
        )

    return render(
        request,
        "accounts/identity_list.html",
        {
            "identities": identities,
            "has_unlink_guard": any(
                not identity.can_unlink for identity in identities
            ),
            "missing_providers": [
                provider
                for provider in PROVIDERS
                if provider["id"] not in connected_providers
            ],
        },
    )


@login_required
@require_POST
def identity_unlink(request: HttpRequest, identity_id) -> HttpResponse:
    try:
        removed = unlink_external_identity(
            account=request.user,
            identity_id=identity_id,
        )
    except IdentityConflict as error:
        messages.error(request, str(error))
    else:
        if not removed:
            raise Http404("Identity not found")
        messages.success(request, "Sign-in identity unlinked.")
    return redirect("account-identity-list")
