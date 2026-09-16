import pytest
from django.test import override_settings

from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID
from registry.demo_submissions import seed_submission_demo_data
from registry.models import DecoderVersion
from registry.schema_contracts import (
    ContractError,
    assert_current,
    field_guidance,
    install_contract,
    release_for,
    schema_status,
    validate_payload,
)
from registry.services.submissions import (
    SubmissionValidationError,
    approve_submission,
    create_submission,
    submission_payload_for_record,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def contracts(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    seed_submission_demo_data()
    admin = Account.objects.get(pk=DEMO_ACCOUNT_ID)
    for version in ("0.2", "0.3"):
        install_contract("decoder", version, uploader=admin)
    settings.CURRENT_SUBMISSION_SCHEMAS = {
        **settings.CURRENT_SUBMISSION_SCHEMAS,
        "decoder": "0.3",
    }
    source = DecoderVersion.objects.filter(state="published").first()
    payload = submission_payload_for_record("decoder", source)
    payload.update(
        slug="contract-test",
        name="Contract test",
        previous_version=None,
        description="Contract test decoder",
        schema_version="0.3",
    )
    return admin, payload


def test_current_submission_and_stale_rejection(contracts):
    admin, payload = contracts
    for version in (None, "0.2"):
        with pytest.raises(ContractError, match="Please refresh"):
            assert_current("decoder", version)
    with pytest.raises(SubmissionValidationError, match="Please refresh"):
        create_submission(
            "decoder", {**payload, "schema_version": "0.2"}, submitter=admin
        )
    record = create_submission("decoder", payload, submitter=admin).record
    assert record.schema_release.version == "0.3"
    assert not schema_status(record)["outdated"]


def test_old_submission_remains_approvable(contracts, settings):
    admin, payload = contracts
    payload["schema_version"] = "0.2"
    with override_settings(
        CURRENT_SUBMISSION_SCHEMAS={
            **settings.CURRENT_SUBMISSION_SCHEMAS,
            "decoder": "0.2",
        }
    ):
        record = create_submission("decoder", payload, submitter=admin).record
    assert schema_status(record)["outdated"]
    with pytest.raises(ContractError):
        validate_payload("decoder", payload)  # Current schema would reject it.
    approve_submission("decoder", record.pk, reviewer=admin)
    record.refresh_from_db()
    assert record.state == "published"
    assert record.schema_release.version == "0.2"


def test_guidance_is_bound_to_recorded_release(contracts):
    old = field_guidance(
        "decoder", "description", release=release_for("decoder", "0.2")
    )
    current = field_guidance("decoder", "description")
    assert old["version"] == "0.2"
    assert current["version"] == "0.3"
    assert old["expanded"] != current["expanded"]
    release = release_for("decoder", "0.2")
    release.version = "99.0"
    with pytest.raises(Exception, match="immutable|frozen|Frozen"):
        release.save()


def test_form_has_version_and_radios(contracts, client):
    client.force_login(contracts[0])
    response = client.get("/submit/decoder/")
    assert response.status_code == 200
    html = response.content.decode()
    assert 'name="schema_version" value="0.3"' in html
    assert 'type="radio"' in html
    assert "Decoder definitions 0.3" in html
    assert '<details class="control-panel field-guidance">' in html
    response = client.post("/submit/decoder/", {"schema_version": "0.2"}, follow=True)
    assert "Please refresh the page" in response.content.decode()


def test_submission_index_and_short_choices(contracts, client):
    from django import forms

    from registry.forms_submissions import DecoderSubmissionForm

    client.force_login(contracts[0])
    html = client.get("/submit/").content.decode()
    assert "Community benchmark" in html
    assert "Noise model submissions are validated and published immediately" in html
    for namespace in ("code", "experiment", "algorithm"):
        assert f"?namespace={namespace}" in html
        page = client.get(f"/taxonomy/tags/new/?namespace={namespace}")
        assert f'value="{namespace}" selected' in page.content.decode()
    form = DecoderSubmissionForm(actor=contracts[0])
    for name in (
        "visibility",
        "circuit_skeleton_preparation",
        "circuit_priors_preparation",
    ):
        assert isinstance(form.fields[name].widget, forms.RadioSelect)
    assert not isinstance(form.fields["previous_version"].widget, forms.RadioSelect)
