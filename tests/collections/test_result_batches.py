import io
import json
import zipfile
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.api_tokens import issue_personal_api_token
from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id
from registry.demo_submissions import seed_submission_demo_data
from registry.models import Result, ResultBatch
from registry.schema_contracts import install_contract
from registry.services.circuit_batches import extract_uploaded_files
from registry.services.result_batches import (
    ResultBatchError,
    commit_batch,
    parse_json,
    validate_batch,
)
from registry.services.submissions import (
    SubmissionValidationError,
    approve_submission,
    submission_payload_for_record,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def data(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    seed_submission_demo_data()
    actor = Account.objects.get(pk=DEMO_ACCOUNT_ID)
    install_contract("result", "0.5", uploader=actor)
    settings.CURRENT_SUBMISSION_SCHEMAS = {
        **settings.CURRENT_SUBMISSION_SCHEMAS,
        "result": "0.5",
    }
    source = Result.objects.filter(state="published").first()
    payload = submission_payload_for_record("result", source)
    payload.update(schema_version="0.5", supersedes_result=None)
    manifest = {
        "schema": "result-batch/0.1",
        "schema_version": "0.5",
        "defaults": {"visibility": "private"},
        "results": {"one.json": {}, "two.json": {}},
    }
    payload.pop("visibility", None)
    files = {name: json.dumps(payload).encode() for name in manifest["results"]}
    return actor, manifest, files


def test_preview_then_atomic_idempotent_submission(data):
    actor, manifest, files = data
    count = Result.objects.count()
    batch = validate_batch(
        actor=actor, manifest=manifest, file_bytes=files, idempotency_key="same"
    )
    assert Result.objects.count() == count
    assert (
        validate_batch(
            actor=actor, manifest=manifest, file_bytes=files, idempotency_key="same"
        ).id
        == batch.id
    )
    results = commit_batch(batch.id, actor=actor)
    assert len(results) == 2
    assert all(
        r.state == "pending_review" and r.visibility == "private" for r in results
    )
    assert [r.id for r in commit_batch(batch.id, actor=actor)] == [
        r.id for r in results
    ]
    assert Result.objects.count() == count + 2


def test_invalid_item_rolls_back_whole_commit(data):
    actor, manifest, files = data
    batch = validate_batch(actor=actor, manifest=manifest, file_bytes=files)
    item = batch.items.order_by("position").last()
    item.payload["shots_total"] += 1
    item.save(update_fields=["payload"])
    count = Result.objects.count()
    with pytest.raises(ResultBatchError):
        commit_batch(batch.id, actor=actor)
    assert Result.objects.count() == count
    assert not batch.items.filter(result__isnull=False).exists()
    batch.refresh_from_db()
    assert batch.committed_at is None


def test_zero_decimals_survive_database_round_trip_and_approval(data):
    actor, manifest, files = data
    for name, raw in files.items():
        payload = json.loads(raw)
        payload["preparation_duration_seconds"] = "0"
        for score in payload["scores"]:
            for field in ("value", "point_estimate", "lower_bound", "upper_bound"):
                score[field] = "0"
        files[name] = json.dumps(payload).encode()
    batch = validate_batch(actor=actor, manifest=manifest, file_bytes=files)
    for result in commit_batch(batch.id, actor=actor):
        result.refresh_from_db()
        payload = submission_payload_for_record("result", result)
        assert "E" not in payload["preparation_duration_seconds"]
        for score in payload["scores"]:
            assert "E" not in score["value"]
        approve_submission("result", result.pk, reviewer=actor)
        result.refresh_from_db()
        assert result.state == "published"


def test_approval_validation_error_is_reported_without_server_error(data, client):
    actor, manifest, files = data
    batch = validate_batch(actor=actor, manifest=manifest, file_bytes=files)
    result = commit_batch(batch.id, actor=actor)[0]
    client.force_login(actor)
    with patch(
        "registry.views_submissions.approve_submission",
        side_effect=SubmissionValidationError("Invalid preparation duration"),
    ):
        response = client.post(f"/review/result/{result.pk}/approve/")
    assert response.status_code == 302
    from django.contrib.messages import get_messages

    assert any(
        "Invalid preparation duration" in str(message)
        for message in get_messages(response.wsgi_request)
    )
    result.refresh_from_db()
    assert result.state == "pending_review"


def test_files_schema_permissions_and_zip(data, settings):
    actor, manifest, files = data
    with pytest.raises(ResultBatchError, match="Missing"):
        validate_batch(actor=actor, manifest=manifest, file_bytes={})
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, raw in files.items():
            zipped.writestr(name, raw)
    extracted = extract_uploaded_files(
        [SimpleUploadedFile("results.zip", archive.getvalue())], suffix=".json"
    )
    assert extracted == files
    batch = validate_batch(actor=actor, manifest=manifest, file_bytes=extracted)
    other = Account.objects.get(pk=demo_id("account/contributor"))
    with pytest.raises(PermissionDenied):
        commit_batch(batch.id, actor=other)
    settings.CURRENT_SUBMISSION_SCHEMAS = {
        **settings.CURRENT_SUBMISSION_SCHEMAS,
        "result": "0.6",
    }
    with pytest.raises(ResultBatchError, match="Please refresh"):
        commit_batch(batch.id, actor=actor)
    with pytest.raises(ResultBatchError):
        parse_json(b'{"x":1,"x":2}')
    with pytest.raises(ResultBatchError):
        parse_json(b'{"x": NaN}')


def test_browser_flow_and_api_scope(data, client):
    actor, manifest, files = data
    client.force_login(actor)
    response = client.get("/submit/result/batch/")
    assert response.status_code == 200
    assert "Agent-friendly API" in response.content.decode()
    response = client.post(
        "/submit/result/batch/",
        {
            "manifest_json": json.dumps(manifest),
            "result_files": [
                SimpleUploadedFile(name, raw) for name, raw in files.items()
            ],
        },
    )
    assert response.status_code == 302
    assert client.get(response.url).status_code == 200
    batch = ResultBatch.objects.latest("created_at")
    response = client.post(f"/submit/result/batch/{batch.id}/commit/")
    assert response.status_code == 302
    assert batch.items.filter(result__isnull=False).count() == 2


def test_reference_withdrawn_after_preview_prevents_commit(data):
    from django.utils import timezone

    from registry.models import CircuitRevision

    actor, manifest, files = data
    batch = validate_batch(actor=actor, manifest=manifest, file_bytes=files)
    circuit_id = batch.items.first().payload["circuit_revision"]
    CircuitRevision.objects.filter(id=circuit_id).update(
        state="withdrawn", withdrawn_at=timezone.now()
    )
    with pytest.raises(ResultBatchError):
        commit_batch(batch.id, actor=actor)
    assert not batch.items.filter(result__isnull=False).exists()


def test_token_api_scope_and_idempotency(data, client):
    actor, manifest, files = data
    denied = issue_personal_api_token(
        account=actor, name="wrong-scope", scopes=["circuits:submit"], lifetime_days=30
    )
    response = client.post(
        "/api/0.1/result-batches/validate/",
        headers={"authorization": f"Bearer {denied.secret}"},
    )
    assert response.status_code == 403
    token = issue_personal_api_token(
        account=actor, name="results", scopes=["results:submit"], lifetime_days=30
    )
    headers = {"authorization": f"Bearer {token.secret}"}
    response = client.post(
        "/api/0.1/result-batches/validate/",
        {
            "manifest": json.dumps(manifest),
            "files": [SimpleUploadedFile(name, raw) for name, raw in files.items()],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.content
    url = response.json()["commit_url"]
    first = client.post(url, headers=headers)
    assert first.status_code == 200, first.content
    assert client.post(url, headers=headers).json() == first.json()
