import pytest
from django.contrib import admin
from django.test import RequestFactory

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id, seed_demo_data
from registry.models import DecoderVersion, RecordEvent, ResultAuthorApprovalEvent

pytestmark = pytest.mark.django_db


def _request():
    request = RequestFactory().get("/admin/")
    request.user = Account.objects.get(id=DEMO_ACCOUNT_ID)
    return request


def test_published_exact_records_are_read_only_and_not_deletable_in_raw_admin():
    seed_demo_data()
    record = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    model_admin = admin.site._registry[DecoderVersion]

    readonly = set(model_admin.get_readonly_fields(_request(), record))

    assert {field.name for field in record._meta.fields} <= readonly
    assert not model_admin.has_delete_permission(_request(), record)


@pytest.mark.parametrize("model", [RecordEvent, ResultAuthorApprovalEvent])
def test_append_only_audit_models_have_no_raw_admin_write_controls(model):
    seed_demo_data()
    model_admin = admin.site._registry[model]

    assert not model_admin.has_add_permission(_request())
    assert not model_admin.has_delete_permission(_request())
    assert {field.name for field in model._meta.fields} == set(
        model_admin.get_readonly_fields(_request())
    )
