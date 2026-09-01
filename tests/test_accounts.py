import pytest

from accounts.models import Account


@pytest.mark.django_db
def test_accounts_never_store_a_usable_password():
    account = Account.objects.create_user(display_name="Ada Decoder")

    assert account.has_usable_password() is False
    assert account.password.startswith("!")


@pytest.mark.django_db
def test_direct_password_assignment_is_replaced_by_unusable_marker():
    account = Account(display_name="No Password", password="plaintext")
    account.save()

    assert account.has_usable_password() is False
