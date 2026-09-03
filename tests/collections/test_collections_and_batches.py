import json

import pytest
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts.api_tokens import issue_personal_api_token
from accounts.models import Account
from registry.demo import DEMO_ACCOUNT_ID, demo_id
from registry.demo_submissions import seed_submission_demo_data
from registry.management.commands.validate_histories import BaseHistoryValidator
from registry.models import (
    BenchmarkRevision,
    CircuitBatch,
    CircuitCollection,
    CircuitRevision,
    EczSyncRun,
    EczTerm,
    NoiseModel,
    RecordHistory,
    Tag,
)
from registry.services.bulk_actions import apply_bulk_action, resolve_targets
from registry.services.circuit_batches import (
    CircuitBatchError,
    commit_batch,
    parse_manifest,
    validate_batch,
)
from registry.services.collections import (
    CollectionError,
    create_collection,
    set_collection_members,
    update_collection,
)
from registry.services.submissions import SubmissionStateError, withdraw_submission
from registry.services.visibility import VisibilityError, set_record_visibility

pytestmark = pytest.mark.django_db

STIM_TEXT = b"""R 0
X_ERROR(0.1) 0
M 0
DETECTOR rec[-1]
OBSERVABLE_INCLUDE(0) rec[-1]
"""


@pytest.fixture
def collection_data(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    seed_submission_demo_data()
    contributor = Account.objects.get(id=demo_id("account/contributor"))
    code_tag = Tag.objects.filter(namespace=Tag.Namespace.CODE).first()
    experiment_tag = Tag.objects.filter(namespace=Tag.Namespace.EXPERIMENT).first()
    noise_model = NoiseModel.objects.filter(state="published").first()
    if not EczTerm.objects.filter(status=EczTerm.Status.CURRENT).exists():
        sync_run = EczSyncRun.objects.create(
            started_at=timezone.now(),
            finished_at=timezone.now(),
            status=EczSyncRun.Status.APPLIED,
            source_repository="https://github.com/errorcorrectionzoo/eczoo_data",
            source_commit="0" * 40,
        )
        EczTerm.objects.create(
            ecz_code_id="test-code",
            raw_name="Test code",
            display_name="Test code",
            first_seen_run=sync_run,
            last_seen_run=sync_run,
        )
    return contributor, code_tag, experiment_tag, noise_model


def test_collection_dag_rejects_a_cycle(collection_data):
    contributor, code_tag, experiment_tag, _noise = collection_data
    first = create_collection(
        actor=contributor,
        slug="first-family",
        name="First family",
        code_tags=[code_tag],
        experiment_tags=[experiment_tag],
    )
    second = create_collection(
        actor=contributor,
        slug="second-family",
        name="Second family",
        code_tags=[code_tag],
        experiment_tags=[experiment_tag],
    )
    set_collection_members(
        first, actor=contributor, circuit_ids=[], child_ids=[second.id]
    )
    with pytest.raises(CollectionError, match="cycle"):
        set_collection_members(
            second, actor=contributor, circuit_ids=[], child_ids=[first.id]
        )


def test_collection_members_must_be_visible_to_the_curator(collection_data):
    contributor, _code_tag, _experiment_tag, _noise = collection_data
    outsider = Account.objects.create_user(display_name="Private record owner")
    collection = create_collection(
        actor=contributor,
        slug="curator-family",
        name="Curator family",
    )
    private_circuit = CircuitRevision.objects.filter(state="published").first()
    private_circuit.submitted_by = outsider
    private_circuit.visibility = "private"
    private_circuit.save(update_fields=["submitted_by", "visibility"])
    private_child = create_collection(
        actor=outsider,
        slug="private-child-family",
        name="Private child family",
        visibility="private",
    )

    with pytest.raises(CollectionError, match="unavailable"):
        set_collection_members(
            collection,
            actor=contributor,
            circuit_ids=[private_circuit.id],
            child_ids=[],
        )
    with pytest.raises(CollectionError, match="unavailable"):
        set_collection_members(
            collection,
            actor=contributor,
            circuit_ids=[],
            child_ids=[private_child.id],
        )


def test_collection_may_contain_another_curators_public_collection(collection_data):
    contributor, _code_tag, _experiment_tag, _noise = collection_data
    outsider = Account.objects.create_user(display_name="Public collection curator")
    parent = create_collection(
        actor=contributor,
        slug="containing-family",
        name="Containing family",
    )
    child = create_collection(
        actor=outsider,
        slug="public-child-family",
        name="Public child family",
    )

    set_collection_members(
        parent,
        actor=contributor,
        circuit_ids=[],
        child_ids=[child.id],
    )

    assert parent.child_memberships.get(removed_at__isnull=True).child == child


def test_published_collection_metadata_remains_editable_with_valid_history(
    collection_data,
):
    contributor, code_tag, experiment_tag, _noise = collection_data
    collection = create_collection(
        actor=contributor,
        slug="editable-family",
        name="Editable family",
    )
    update_collection(
        collection,
        actor=contributor,
        slug=collection.slug,
        name="Edited family",
        description="Curated folder metadata remains mutable.",
        visibility="private",
        code_tags=[code_tag],
        ecz_terms=[],
        experiment_tags=[experiment_tag],
    )

    collection_errors = [
        error
        for error in BaseHistoryValidator().validate()
        if str(collection.history_id) in error
    ]
    assert collection_errors == []


def test_batch_derives_stim_fields_and_commits_collections(collection_data):
    contributor, code_tag, experiment_tag, noise_model = collection_data
    manifest = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "visibility": "private",
            "noise_model": str(noise_model.id),
            "is_css": True,
            "code_tags": [str(code_tag.id)],
            "experiment_tags": [str(experiment_tag.id)],
            "dem_arguments": {"decompose_errors": True},
        },
        "circuits": {
            "distance-3.stim": {
                "slug": "batch-distance-3",
                "name": "Batch distance 3",
                "description": "A batch test circuit.",
                "revision_description": "First revision.",
                "collections": ["new:batch-family"],
            }
        },
        "new_tags": [],
        "new_collections": [
            {
                "client_id": "batch-family",
                "slug": "batch-family",
                "name": "Batch family",
                "visibility": "private",
                "code_tags": [str(code_tag.id)],
                "experiment_tags": [str(experiment_tag.id)],
                "children": [],
            }
        ],
    }
    validation = validate_batch(
        actor=contributor,
        manifest=manifest,
        file_bytes={"distance-3.stim": STIM_TEXT},
        idempotency_key="test-batch-one",
    )
    normalized = validation.batch.normalized_manifest["circuits"][0]
    assert normalized["derived"]["num_detectors"] == 1
    assert normalized["derived"]["num_errors"] == 1
    assert normalized["derived"]["num_observables"] == 1

    circuits = commit_batch(validation.batch.id, actor=contributor)

    assert len(circuits) == 1
    assert circuits[0].state == "pending_review"
    assert circuits[0].visibility == "private"
    collection = CircuitCollection.objects.get(slug="batch-family")
    assert (
        collection.circuit_memberships.get(removed_at__isnull=True).circuit_revision
        == circuits[0]
    )
    assert commit_batch(validation.batch.id, actor=contributor) == circuits


def test_only_the_batch_contributor_can_commit_a_validated_batch(collection_data):
    contributor, code_tag, experiment_tag, noise_model = collection_data
    manifest = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "noise_model": str(noise_model.id),
            "code_tags": [str(code_tag.id)],
            "experiment_tags": [str(experiment_tag.id)],
        },
        "circuits": {
            "owned.stim": {
                "slug": "contributor-owned-batch-circuit",
                "description": "Batch ownership test.",
                "revision_description": "First revision.",
            }
        },
    }
    validation = validate_batch(
        actor=contributor,
        manifest=manifest,
        file_bytes={"owned.stim": STIM_TEXT},
    )
    admin = Account.objects.get(id=DEMO_ACCOUNT_ID)

    with pytest.raises(PermissionDenied, match="Only the contributor"):
        commit_batch(validation.batch.id, actor=admin)

    assert commit_batch(validation.batch.id, actor=contributor)


def test_private_record_is_hidden_and_owner_controls_visibility(collection_data):
    contributor, _code_tag, _experiment_tag, _noise = collection_data
    circuit = CircuitRevision.objects.filter(submitted_by=contributor).first()
    circuit.visibility = "private"
    circuit.save(update_fields=["visibility"])
    outsider = Account.objects.create_user(display_name="Outsider")

    with pytest.raises(PermissionDenied):
        set_record_visibility(
            "circuit", circuit.id, actor=outsider, visibility="public"
        )
    updated = set_record_visibility(
        "circuit", circuit.id, actor=contributor, visibility="public"
    )
    assert updated.visibility == "public"


def test_collection_form_reuses_tag_picker_and_private_detail_is_authorized(
    client, collection_data
):
    contributor, code_tag, experiment_tag, _noise = collection_data
    ecz_term = EczTerm.objects.filter(status=EczTerm.Status.CURRENT).first()
    client.force_login(contributor)
    response = client.post(
        reverse("collections:create"),
        {
            "slug": "tagged-private-family",
            "name": "Tagged private family",
            "description": "Collection classification test.",
            "visibility": "private",
            "code_tags": [str(code_tag.id)],
            "ecz_terms": [str(ecz_term.id)],
            "experiment_tags": [str(experiment_tag.id)],
        },
    )
    assert response.status_code == 302
    collection = CircuitCollection.objects.get(slug="tagged-private-family")
    assert list(collection.code_tags.all()) == [code_tag]
    assert list(collection.ecz_terms.all()) == [ecz_term]
    assert list(collection.experiment_tags.all()) == [experiment_tag]

    detail = client.get(collection.get_absolute_url())
    assert detail.status_code == 200
    assert b"Collection classification test" in detail.content
    assert (
        b"tag-picker"
        in client.get(reverse("collections:edit", args=[collection.slug])).content
    )
    client.logout()
    assert client.get(collection.get_absolute_url()).status_code == 404


def test_empty_collection_has_no_direct_member_bulk_controls(client, collection_data):
    contributor, _code_tag, _experiment_tag, _noise = collection_data
    admin = Account.objects.get(id=DEMO_ACCOUNT_ID)
    collection = create_collection(
        actor=contributor,
        slug="empty-family",
        name="Empty family",
    )
    client.force_login(admin)

    content = client.get(collection.get_absolute_url()).content.decode()

    assert "No direct circuit members." in content
    assert 'id="bulk-collection-members"' not in content
    assert "Code classification</dt><dd>" in content


def test_batch_idempotency_key_cannot_alias_different_content(collection_data):
    contributor, code_tag, experiment_tag, noise_model = collection_data

    def manifest(slug):
        return {
            "schema": "circuit-batch/0.1",
            "defaults": {
                "noise_model": str(noise_model.id),
                "is_css": True,
                "code_tags": [str(code_tag.id)],
                "experiment_tags": [str(experiment_tag.id)],
            },
            "circuits": {
                "one.stim": {
                    "slug": slug,
                    "description": "Idempotency test.",
                    "revision_description": "First revision.",
                }
            },
        }

    first = validate_batch(
        actor=contributor,
        manifest=manifest("idempotent-first"),
        file_bytes={"one.stim": STIM_TEXT},
        idempotency_key="stable-key",
    )
    assert CircuitBatch.objects.count() == 1
    repeated = validate_batch(
        actor=contributor,
        manifest=manifest("idempotent-first"),
        file_bytes={"one.stim": STIM_TEXT},
        idempotency_key="stable-key",
    )
    assert repeated.batch == first.batch
    with pytest.raises(CircuitBatchError, match="different batch"):
        validate_batch(
            actor=contributor,
            manifest=manifest("idempotent-second"),
            file_bytes={"one.stim": STIM_TEXT},
            idempotency_key="stable-key",
        )


def test_api_contracts_are_public(client):
    schema = client.get(reverse("api-0.1:batch-schema"))
    assert schema.status_code == 200
    assert schema.json()["properties"]["new_collections"]["items"]["properties"][
        "code_tags"
    ]
    openapi = client.get(reverse("api-0.1:openapi"))
    assert openapi.status_code == 200
    assert openapi.json()["openapi"] == "3.1.0"
    assert "/circuit-batches/validate/" in openapi.json()["paths"]


def test_api_token_validates_and_commits_the_same_batch_contract(
    client, collection_data
):
    contributor, code_tag, experiment_tag, noise_model = collection_data
    issued = issue_personal_api_token(
        account=contributor,
        name="collection batch test",
        scopes=["circuits:submit", "collections:write"],
        lifetime_days=30,
    )
    manifest = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "noise_model": str(noise_model.id),
            "code_tags": [str(code_tag.id)],
            "experiment_tags": [str(experiment_tag.id)],
        },
        "circuits": {
            "api.stim": {
                "slug": "api-batch-circuit",
                "description": "Submitted through the API contract.",
                "revision_description": "First revision.",
                "collections": ["new:api-family"],
            }
        },
        "new_collections": [
            {
                "client_id": "api-family",
                "slug": "api-family",
                "name": "API family",
            }
        ],
    }
    authorization = f"Bearer {issued.secret}"
    response = client.post(
        reverse("api-0.1:batch-validate"),
        {
            "manifest": json.dumps(manifest),
            "files": SimpleUploadedFile("api.stim", STIM_TEXT),
        },
        headers={
            "authorization": authorization,
            "idempotency-key": "api-contract-test",
        },
    )
    assert response.status_code == 200
    batch_id = response.json()["batch_id"]
    committed = client.post(
        reverse("api-0.1:batch-commit", args=[batch_id]),
        headers={"authorization": authorization},
    )
    assert committed.status_code == 200
    assert committed.json()["circuits"][0]["slug"] == "api-batch-circuit"
    assert CircuitCollection.objects.filter(slug="api-family").exists()


def test_api_requires_collection_scope_for_declared_collections(
    client, collection_data
):
    contributor, code_tag, experiment_tag, noise_model = collection_data
    issued = issue_personal_api_token(
        account=contributor,
        name="circuit only",
        scopes=["circuits:submit"],
        lifetime_days=30,
    )
    manifest = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "noise_model": str(noise_model.id),
            "code_tags": [str(code_tag.id)],
            "experiment_tags": [str(experiment_tag.id)],
        },
        "circuits": {
            "scoped.stim": {
                "slug": "scoped-api-circuit",
                "description": "Scope test.",
                "revision_description": "First revision.",
            }
        },
        "new_collections": [
            {
                "client_id": "scope-family",
                "slug": "scope-family",
                "name": "Scope family",
            }
        ],
    }
    response = client.post(
        reverse("api-0.1:batch-validate"),
        {
            "manifest": json.dumps(manifest),
            "files": SimpleUploadedFile("scoped.stim", STIM_TEXT),
        },
        headers={"authorization": f"Bearer {issued.secret}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_api_requires_collection_scope_for_existing_collection_membership(
    client, collection_data
):
    contributor, code_tag, experiment_tag, noise_model = collection_data
    collection = create_collection(
        actor=contributor,
        slug="existing-api-family",
        name="Existing API family",
    )
    issued = issue_personal_api_token(
        account=contributor,
        name="circuit submission only",
        scopes=["circuits:submit"],
        lifetime_days=30,
    )
    manifest = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "noise_model": str(noise_model.id),
            "code_tags": [str(code_tag.id)],
            "experiment_tags": [str(experiment_tag.id)],
        },
        "circuits": {
            "existing-collection.stim": {
                "slug": "existing-collection-api-circuit",
                "description": "Existing collection scope test.",
                "revision_description": "First revision.",
                "collections": [str(collection.id)],
            }
        },
    }

    response = client.post(
        reverse("api-0.1:batch-validate"),
        {
            "manifest": json.dumps(manifest),
            "files": SimpleUploadedFile("existing-collection.stim", STIM_TEXT),
        },
        headers={"authorization": f"Bearer {issued.secret}"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_scope"


def test_collection_scope_reuses_bulk_visibility_action(collection_data):
    contributor, _code_tag, _experiment_tag, _noise = collection_data
    circuit = CircuitRevision.objects.filter(submitted_by=contributor).first()
    circuit.visibility = "public"
    circuit.save(update_fields=["visibility"])
    collection = create_collection(
        actor=contributor,
        slug="bulk-family",
        name="Bulk family",
    )
    set_collection_members(
        collection,
        actor=contributor,
        circuit_ids=[circuit.id],
        child_ids=[],
    )

    targets = resolve_targets([], actor=contributor, collection_scope=collection.id)
    assert [target.key for target in targets] == [f"circuit:{circuit.id}"]
    assert apply_bulk_action("make_private", targets, actor=contributor) == 1
    circuit.refresh_from_db()
    assert circuit.visibility == "private"


def test_collection_and_owned_circuits_visibility_has_an_explicit_preview(
    client, collection_data
):
    contributor, _code_tag, _experiment_tag, _noise = collection_data
    outsider = Account.objects.create_user(display_name="Other circuit contributor")
    benchmark = BenchmarkRevision.objects.filter(state="published").first()
    benchmark.recognition_status = BenchmarkRevision.RecognitionStatus.OFFICIAL
    benchmark.save(update_fields=["recognition_status"])
    locked = benchmark.items.select_related("circuit_revision").first().circuit_revision

    def clone_circuit(slug, name, owner):
        values = {
            field.attname: getattr(locked, field.attname)
            for field in locked._meta.concrete_fields
            if not field.primary_key and field.name not in {"created_at", "updated_at"}
        }
        values.update(
            history_id=RecordHistory.objects.create(record_kind="circuit").id,
            predecessor_id=None,
            slug=slug,
            name=name,
            submitted_by_id=owner.id,
        )
        return CircuitRevision.objects.create(**values)

    ordinary = clone_circuit(
        "visibility-owned-circuit", "Visibility owned circuit", contributor
    )
    foreign = clone_circuit(
        "visibility-foreign-circuit", "Visibility foreign circuit", outsider
    )
    for circuit, owner in (
        (locked, contributor),
        (ordinary, contributor),
        (foreign, outsider),
    ):
        circuit.submitted_by = owner
        circuit.visibility = "public"
        circuit.save(update_fields=["submitted_by", "visibility"])
    collection = create_collection(
        actor=contributor,
        slug="visibility-family",
        name="Visibility family",
    )
    set_collection_members(
        collection,
        actor=contributor,
        circuit_ids=[ordinary.id, locked.id, foreign.id],
        child_ids=[],
    )
    client.force_login(contributor)

    detail = client.get(collection.get_absolute_url())
    assert detail.status_code == 200
    assert b"Collection page visibility: Public" in detail.content
    assert b"Changing the collection page visibility does not change any circuit" in (
        detail.content
    )

    preview = client.post(
        reverse("bulk:preview"),
        {
            "return_url": collection.get_absolute_url(),
            "action": "make_private",
            "target": f"collection:{collection.id}",
            "collection_scope": str(collection.id),
            "collection_visibility_cascade": "1",
        },
    )
    assert preview.status_code == 200
    target_keys = {target.key for target in preview.context["targets"]}
    assert target_keys == {
        f"collection:{collection.id}",
        f"circuit:{ordinary.id}",
    }
    assert preview.context["cascade"].skipped_other_owner_count == 1
    assert preview.context["cascade"].skipped_locked[0][0] == locked.name

    committed = client.post(
        reverse("bulk:commit"),
        {
            "return_url": collection.get_absolute_url(),
            "action": "make_private",
            "target": list(target_keys),
            "note": "Private before publication.",
        },
    )
    assert committed.status_code == 302
    collection.refresh_from_db()
    ordinary.refresh_from_db()
    locked.refresh_from_db()
    foreign.refresh_from_db()
    assert collection.visibility == ordinary.visibility == "private"
    assert locked.visibility == foreign.visibility == "public"


def test_official_benchmark_dependency_cannot_be_made_private(collection_data):
    benchmark = BenchmarkRevision.objects.filter(state="published").first()
    benchmark.recognition_status = BenchmarkRevision.RecognitionStatus.OFFICIAL
    benchmark.save(update_fields=["recognition_status"])
    circuit = (
        benchmark.items.select_related("circuit_revision").first().circuit_revision
    )
    with pytest.raises(VisibilityError, match="official benchmark"):
        set_record_visibility(
            "circuit",
            circuit.id,
            actor=Account.objects.get(id=DEMO_ACCOUNT_ID),
            visibility="private",
        )
    with pytest.raises(SubmissionStateError, match="official benchmark"):
        withdraw_submission(
            "circuit",
            circuit.id,
            actor=Account.objects.get(id=DEMO_ACCOUNT_ID),
            note="Should remain available.",
        )


def test_batch_new_tags_support_forward_parent_references(collection_data):
    contributor, _code_tag, experiment_tag, noise_model = collection_data
    manifest = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "noise_model": str(noise_model.id),
            "code_tags": ["new:specific-code"],
            "experiment_tags": [str(experiment_tag.id)],
        },
        "circuits": {
            "nested-tag.stim": {
                "slug": "nested-tag-circuit",
                "description": "Nested tag test.",
                "revision_description": "First revision.",
            }
        },
        "new_tags": [
            {
                "client_id": "specific-code",
                "namespace": "code",
                "label": "Specific batch code",
                "description": "A specific code created by a batch.",
                "parents": ["new:code-family"],
            },
            {
                "client_id": "code-family",
                "namespace": "code",
                "label": "Batch code family",
                "description": "A code family created by a batch.",
            },
        ],
    }
    validation = validate_batch(
        actor=contributor,
        manifest=manifest,
        file_bytes={"nested-tag.stim": STIM_TEXT},
    )
    commit_batch(validation.batch.id, actor=contributor)
    child = Tag.objects.get(label="Specific batch code")
    assert list(child.parents.values_list("label", flat=True)) == ["Batch code family"]


def test_batch_preview_rejects_cycles_and_duplicate_json_keys(collection_data):
    contributor, _code_tag, experiment_tag, noise_model = collection_data
    cycle = {
        "schema": "circuit-batch/0.1",
        "defaults": {
            "noise_model": str(noise_model.id),
            "code_tags": ["new:first"],
            "experiment_tags": [str(experiment_tag.id)],
        },
        "circuits": {
            "cycle.stim": {
                "slug": "cycle-circuit",
                "description": "Cycle test.",
                "revision_description": "First revision.",
            }
        },
        "new_tags": [
            {
                "client_id": "first",
                "namespace": "code",
                "label": "First cyclic tag",
                "description": "Cycle test.",
                "parents": ["new:second"],
            },
            {
                "client_id": "second",
                "namespace": "code",
                "label": "Second cyclic tag",
                "description": "Cycle test.",
                "parents": ["new:first"],
            },
        ],
    }
    with pytest.raises(CircuitBatchError, match="contain a cycle"):
        validate_batch(
            actor=contributor,
            manifest=cycle,
            file_bytes={"cycle.stim": STIM_TEXT},
        )
    with pytest.raises(CircuitBatchError, match="repeats the key 'schema'"):
        parse_manifest('{"schema":"circuit-batch/0.1","schema":"other","circuits":{}}')
