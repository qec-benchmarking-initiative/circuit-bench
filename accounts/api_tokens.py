from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Account, PersonalApiToken

TOKEN_PREFIX = "cbp"
MAX_ACTIVE_TOKENS = 20
ALLOWED_SCOPES = frozenset(PersonalApiToken.Scope.values)


class ApiTokenError(ValueError):
    pass


@dataclass(frozen=True)
class IssuedApiToken:
    record: PersonalApiToken
    secret: str


def issue_personal_api_token(
    *,
    account: Account,
    name: str,
    scopes: list[str] | tuple[str, ...],
    lifetime_days: int,
) -> IssuedApiToken:
    name = name.strip()
    selected_scopes = tuple(dict.fromkeys(scopes))
    if not account.is_active:
        raise ApiTokenError("Inactive accounts cannot create API tokens.")
    if not name:
        raise ApiTokenError("Give the token a name.")
    if not selected_scopes or not set(selected_scopes) <= ALLOWED_SCOPES:
        raise ApiTokenError("Select one or more supported permissions.")
    if lifetime_days not in {30, 90, 365}:
        raise ApiTokenError("Choose a supported expiry period.")
    active_count = account.personal_api_tokens.filter(
        revoked_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).count()
    if active_count >= MAX_ACTIVE_TOKENS:
        raise ApiTokenError("Revoke an existing token before creating another.")

    public_id = _new_public_id()
    secret = secrets.token_urlsafe(32)
    complete = f"{TOKEN_PREFIX}_{public_id}_{secret}"
    record = PersonalApiToken.objects.create(
        account=account,
        public_id=public_id,
        secret_digest=_digest(secret),
        display_prefix=f"{TOKEN_PREFIX}_{public_id}",
        name=name,
        scopes=list(selected_scopes),
        expires_at=timezone.now() + timedelta(days=lifetime_days),
    )
    return IssuedApiToken(record=record, secret=complete)


def authenticate_personal_api_token(raw_token: str) -> PersonalApiToken:
    try:
        prefix, public_id, secret = raw_token.split("_", 2)
    except ValueError as error:
        raise ApiTokenError("The bearer token is malformed.") from error
    if prefix != TOKEN_PREFIX or not public_id or not secret:
        raise ApiTokenError("The bearer token is malformed.")
    token = (
        PersonalApiToken.objects.select_related("account")
        .filter(public_id=public_id)
        .first()
    )
    if token is None or not hmac.compare_digest(token.secret_digest, _digest(secret)):
        raise ApiTokenError("The bearer token is invalid.")
    now = timezone.now()
    if token.revoked_at is not None or token.expires_at <= now:
        raise ApiTokenError("The bearer token has expired or been revoked.")
    if not token.account.is_active:
        raise ApiTokenError("The account is inactive.")
    if token.last_used_at is None or token.last_used_at <= now - timedelta(hours=1):
        PersonalApiToken.objects.filter(id=token.id).update(last_used_at=now)
        token.last_used_at = now
    return token


def require_token_scopes(token: PersonalApiToken, required: set[str]) -> None:
    if not required <= set(token.scopes):
        missing = ", ".join(sorted(required - set(token.scopes)))
        raise PermissionError(f"The token lacks required permission: {missing}.")


@transaction.atomic
def revoke_personal_api_token(*, account: Account, token_id) -> bool:
    token = (
        PersonalApiToken.objects.select_for_update()
        .filter(id=token_id, account=account, revoked_at__isnull=True)
        .first()
    )
    if token is None:
        return False
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    return True


def _new_public_id() -> str:
    while True:
        # Hex cannot contain the underscore delimiter used by the token envelope.
        value = secrets.token_hex(9)
        if not PersonalApiToken.objects.filter(public_id=value).exists():
            return value


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
