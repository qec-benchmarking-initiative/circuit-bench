import pytest

from accounts.api_tokens import (
    ApiTokenError,
    authenticate_personal_api_token,
    issue_personal_api_token,
    revoke_personal_api_token,
)
from accounts.models import Account

pytestmark = pytest.mark.django_db


def test_personal_token_is_shown_once_stored_as_digest_and_revocable():
    account = Account.objects.create_user(display_name="API contributor")
    issued = issue_personal_api_token(
        account=account,
        name="batch agent",
        scopes=["circuits:submit"],
        lifetime_days=90,
    )
    assert issued.secret.startswith("cbp_")
    assert issued.secret not in issued.record.secret_digest
    assert authenticate_personal_api_token(issued.secret).account == account

    assert revoke_personal_api_token(account=account, token_id=issued.record.id)
    with pytest.raises(ApiTokenError, match="expired or been revoked"):
        authenticate_personal_api_token(issued.secret)
