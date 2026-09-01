from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import include, path, reverse
from django.utils import timezone

from accounts.models import Account
from registry.models import (
    ArtifactAttachment,
    ArtifactGrant,
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    RecordHistory,
    Result,
    SchemaRelease,
)
from registry.models.common import LifecycleState
from registry.services.artifact_access import (
    artifact_has_public_reference,
    readable_artifacts_for,
)
from registry.services.artifacts import store_artifact_chunks, store_uploaded_artifact

urlpatterns = [
    path(
        "artifacts/",
        include(("registry.urls_artifacts", "artifacts"), namespace="artifacts"),
    ),
    path("", include("pages.urls")),
]

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def artifact_urlconf(settings, tmp_path):
    settings.ROOT_URLCONF = __name__
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.ARTIFACT_STORAGE_BACKEND = "local"


@pytest.fixture
def public_graph():
    published_at = timezone.now()
    submitter = Account.objects.create_user(display_name="Published submitter")
    admin = Account.objects.create_user(display_name="Registry admin", is_admin=True)
    base_artifact, _content = _new_artifact("public-graph-base", uploaded_by=submitter)
    release = SchemaRelease.objects.create(
        record_type=SchemaRelease.RecordType.DECODER,
        version="access-test-0.1",
        json_schema_artifact=base_artifact,
        definitions_artifact=base_artifact,
        permanent_url="https://example.test/schemas/access-test-0.1/",
        state=SchemaRelease.State.FROZEN,
        frozen_at=published_at,
    )
    noise_model = NoiseModel.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="noise_model"),
        slug="access-test-noise",
        name="Access test noise",
        short_description="A test noise model.",
        paper_url="https://example.test/noise",
        randomises_priors=False,
        curation_status=NoiseModel.CurationStatus.COMMUNITY,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    decoder_root = DecoderVersion.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="decoder"),
        slug="access-test-decoder-root",
        name="Access test decoder",
        version="0.1",
        description="First revision.",
        revision_description="First revision.",
        circuit_skeleton_preparation=DecoderVersion.Preparation.NOT_REQUIRED,
        circuit_priors_preparation=DecoderVersion.Preparation.NOT_REQUIRED,
        provides_failure_probability=True,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    decoder = DecoderVersion.objects.create(
        schema_release=release,
        history=decoder_root.history,
        slug="access-test-decoder",
        name="Access test decoder",
        version="0.2",
        predecessor=decoder_root,
        revision_description="Second revision.",
        circuit_skeleton_preparation=DecoderVersion.Preparation.NOT_REQUIRED,
        circuit_priors_preparation=DecoderVersion.Preparation.NOT_REQUIRED,
        provides_failure_probability=True,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    circuit = CircuitRevision.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="circuit"),
        slug="access-test-circuit",
        name="Access test circuit",
        description="First revision.",
        revision_description="First revision.",
        noise_model=noise_model,
        is_css=True,
        code_distance_upper_bound=3,
        circuit_distance_upper_bound=3,
        rounds=3,
        num_detectors=1,
        num_errors=1,
        num_observables=1,
        dem_x_detectors_only=False,
        dem_z_detectors_only=False,
        stim_version="1.0",
        dem_generation_method="stim.Circuit.detector_error_model",
        dem_decompose_errors=False,
        dem_flatten_loops=False,
        dem_allow_gauge_detectors=False,
        dem_approximate_disjoint_errors=False,
        dem_ignore_decomposition_failures=False,
        dem_block_decomposition_from_introducing_remnant_edges=False,
        sampling_circuit_artifact=base_artifact,
        detector_error_model_artifact=base_artifact,
        manifest_artifact=base_artifact,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    evaluator = EvaluatorRelease.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="evaluator"),
        version="access-test-0.1",
        source_url="https://example.test/evaluator",
        source_revision="abc123",
        source_bundle_artifact=base_artifact,
        input_contract_url="https://example.test/evaluator/input",
        summary_contract_url="https://example.test/evaluator/summary",
        submitted_by=submitter,
        state=EvaluatorRelease.State.PUBLISHED,
        published_at=published_at,
    )
    machine = Machine.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="machine"),
        slug="access-test-machine",
        machine_class=Machine.MachineClass.CPU,
        description="Test CPU.",
        status=Machine.EvidenceStatus.PHYSICAL,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    result = Result.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="result"),
        decoder_version=decoder,
        circuit_revision=circuit,
        evaluator_version=evaluator,
        machine=machine,
        shots_total=10,
        successful_shots=9,
        logical_failure_shots=1,
        timeout_shots=0,
        decoder_error_shots=0,
        failure_probability_shots=10,
        latency_shots=10,
        reproduction_status=Result.ReproductionStatus.INDEPENDENT,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    benchmark = BenchmarkRevision.objects.create(
        schema_release=release,
        history=RecordHistory.objects.create(record_kind="benchmark"),
        slug="access-test-benchmark",
        name="Access test benchmark",
        version="0.1",
        description="First revision.",
        revision_description="First revision.",
        recognition_status=BenchmarkRevision.RecognitionStatus.ADMIN_APPROVED,
        manifest_artifact=base_artifact,
        submitted_by=submitter,
        state=LifecycleState.PUBLISHED,
        published_at=published_at,
    )
    return {
        "admin": admin,
        "schema_release": release,
        "decoder": decoder,
        "decoder_root": decoder_root,
        "noise_model": noise_model,
        "circuit": circuit,
        "evaluator": evaluator,
        "result": result,
        "benchmark": benchmark,
    }


def _new_artifact(label: str, *, uploaded_by: Account):
    content = f"private bytes for {label}\n".encode()
    artifact, created = store_artifact_chunks(
        [content],
        uploaded_by=uploaded_by,
        media_type="application/octet-stream",
        original_filename=f"{label}.bin",
    )
    assert created
    return artifact, content


def _download(client, artifact):
    return client.get(reverse("artifacts:download", args=[artifact.id]))


def _assert_downloaded(response, content: bytes):
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == content


def _make_public_reference(case: str, artifact, graph):
    if case.startswith("schema_"):
        field = {
            "schema_json": "json_schema_artifact",
            "schema_definitions": "definitions_artifact",
        }[case]
        release = graph["schema_release"]
        setattr(release, field, artifact)
        release.save(update_fields=[field])
        return

    if case.endswith("_attachment"):
        subject_name = case.removesuffix("_attachment")
        field = {
            "decoder": "decoder_version",
            "noise_model": "noise_model",
            "circuit": "circuit_revision",
            "result": "result",
            "evaluator": "evaluator_release",
            "benchmark": "benchmark_revision",
        }[subject_name]
        ArtifactAttachment.objects.create(
            artifact=artifact,
            role="other",
            position=97,
            **{field: graph[subject_name]},
        )
        return

    subject_name, field = {
        "decoder_schema": ("decoder", "hyperparameter_schema_artifact"),
        "circuit_sampling": ("circuit", "sampling_circuit_artifact"),
        "circuit_dem": ("circuit", "detector_error_model_artifact"),
        "circuit_manifest": ("circuit", "manifest_artifact"),
        "evaluator_source": ("evaluator", "source_bundle_artifact"),
        "result_hyperparameters": ("result", "hyperparameter_values_artifact"),
        "benchmark_manifest": ("benchmark", "manifest_artifact"),
    }[case]
    subject = graph[subject_name]
    setattr(subject, field, artifact)
    subject.save(update_fields=[field])


@pytest.mark.parametrize(
    "reference_case",
    [
        "schema_json",
        "schema_definitions",
        "decoder_schema",
        "circuit_sampling",
        "circuit_dem",
        "circuit_manifest",
        "evaluator_source",
        "result_hyperparameters",
        "benchmark_manifest",
        "decoder_attachment",
        "noise_model_attachment",
        "circuit_attachment",
        "result_attachment",
        "evaluator_attachment",
        "benchmark_attachment",
    ],
)
def test_every_artifact_relation_can_make_a_file_public(public_graph, reference_case):
    owner = Account.objects.create_user(display_name=f"Owner {reference_case}")
    artifact, _content = _new_artifact(reference_case, uploaded_by=owner)

    _make_public_reference(reference_case, artifact, public_graph)

    assert artifact_has_public_reference(artifact)


def test_anonymous_user_can_download_a_publicly_referenced_file(client, public_graph):
    owner = Account.objects.create_user(display_name="Public file uploader")
    artifact, content = _new_artifact("public-decoder-file", uploaded_by=owner)
    _make_public_reference("decoder_schema", artifact, public_graph)

    _assert_downloaded(_download(client, artifact), content)


@pytest.mark.parametrize(
    "private_state",
    [
        LifecycleState.DRAFT,
        LifecycleState.PENDING_REVIEW,
        LifecycleState.PENDING_REAPPROVAL,
        LifecycleState.CHANGES_REQUESTED,
        LifecycleState.REJECTED,
    ],
)
def test_unpublished_submission_file_is_limited_to_uploader_and_admin(
    client, public_graph, private_state
):
    owner = Account.objects.create_user(display_name=f"Uploader {private_state}")
    other = Account.objects.create_user(display_name=f"Other {private_state}")
    artifact, content = _new_artifact(private_state, uploaded_by=owner)
    decoder = public_graph["decoder"]
    decoder.hyperparameter_schema_artifact = artifact
    decoder.state = private_state
    decoder.published_at = None
    decoder.withdrawn_at = None
    decoder.save(
        update_fields=[
            "hyperparameter_schema_artifact",
            "state",
            "published_at",
            "withdrawn_at",
        ]
    )

    assert _download(client, artifact).status_code == 404

    client.force_login(other)
    assert _download(client, artifact).status_code == 404

    client.force_login(owner)
    _assert_downloaded(_download(client, artifact), content)

    client.force_login(public_graph["admin"])
    _assert_downloaded(_download(client, artifact), content)


def test_orphan_file_is_limited_to_uploader_and_admin(client, public_graph):
    owner = Account.objects.create_user(display_name="Orphan uploader")
    other = Account.objects.create_user(display_name="Other scientist")
    artifact, content = _new_artifact("orphan", uploaded_by=owner)

    assert not artifact_has_public_reference(artifact)
    assert _download(client, artifact).status_code == 404

    client.force_login(other)
    assert _download(client, artifact).status_code == 404

    client.force_login(owner)
    _assert_downloaded(_download(client, artifact), content)

    client.force_login(public_graph["admin"])
    _assert_downloaded(_download(client, artifact), content)


def test_second_uploader_of_deduplicated_private_bytes_receives_access_grant(client):
    first = Account.objects.create_user(display_name="First byte supplier")
    second = Account.objects.create_user(display_name="Second byte supplier")
    outsider = Account.objects.create_user(display_name="Unrelated account")
    content = b"identical unpublished scientific bytes\n"

    artifact, first_created = store_uploaded_artifact(
        SimpleUploadedFile("first.dem", content), uploaded_by=first
    )
    reused, second_created = store_uploaded_artifact(
        SimpleUploadedFile("second.dem", content), uploaded_by=second
    )

    assert first_created
    assert not second_created
    assert reused.id == artifact.id
    assert artifact.uploaded_by == first
    assert set(
        ArtifactGrant.objects.filter(artifact=artifact).values_list(
            "account_id", "source"
        )
    ) == {
        (first.id, ArtifactGrant.Source.UPLOAD),
        (second.id, ArtifactGrant.Source.UPLOAD),
    }

    client.force_login(first)
    _assert_downloaded(_download(client, artifact), content)
    client.force_login(second)
    _assert_downloaded(_download(client, artifact), content)
    assert readable_artifacts_for(second).filter(pk=artifact.pk).exists()

    client.force_login(outsider)
    assert _download(client, artifact).status_code == 404
    assert not readable_artifacts_for(outsider).filter(pk=artifact.pk).exists()


def test_one_public_reference_makes_a_file_shared_with_private_submission_public(
    client, public_graph
):
    owner = Account.objects.create_user(display_name="Shared file uploader")
    artifact, content = _new_artifact("shared", uploaded_by=owner)
    pending = public_graph["decoder"]
    published = public_graph["decoder_root"]
    pending.hyperparameter_schema_artifact = artifact
    pending.state = LifecycleState.PENDING_REVIEW
    pending.published_at = None
    pending.save(
        update_fields=["hyperparameter_schema_artifact", "state", "published_at"]
    )
    published.hyperparameter_schema_artifact = artifact
    published.save(update_fields=["hyperparameter_schema_artifact"])

    _assert_downloaded(_download(client, artifact), content)


def test_withdrawn_exact_record_keeps_its_file_public(client, public_graph):
    owner = Account.objects.create_user(display_name="Withdrawn file uploader")
    artifact, content = _new_artifact("withdrawn", uploaded_by=owner)
    decoder = public_graph["decoder"]
    decoder.hyperparameter_schema_artifact = artifact
    decoder.state = LifecycleState.WITHDRAWN
    decoder.withdrawn_at = timezone.now()
    decoder.save(
        update_fields=[
            "hyperparameter_schema_artifact",
            "state",
            "withdrawn_at",
        ]
    )

    _assert_downloaded(_download(client, artifact), content)


def test_draft_schema_release_files_remain_private_until_frozen(client, public_graph):
    owner = Account.objects.create_user(display_name="Contract uploader")
    artifact, content = _new_artifact("draft-schema", uploaded_by=owner)
    release = public_graph["schema_release"]
    release.json_schema_artifact = artifact
    release.state = SchemaRelease.State.DRAFT
    release.frozen_at = None
    release.save(update_fields=["json_schema_artifact", "state", "frozen_at"])

    assert not artifact_has_public_reference(artifact)
    assert _download(client, artifact).status_code == 404

    client.force_login(owner)
    _assert_downloaded(_download(client, artifact), content)


def test_circuit_file_is_not_public_when_its_noise_model_is_not_public(
    client, public_graph
):
    owner = Account.objects.create_user(display_name="Circuit file uploader")
    artifact, _content = _new_artifact("private-circuit", uploaded_by=owner)
    circuit = public_graph["circuit"]
    circuit.sampling_circuit_artifact = artifact
    circuit.save(update_fields=["sampling_circuit_artifact"])
    circuit.noise_model.state = LifecycleState.PENDING_REVIEW
    circuit.noise_model.published_at = None
    circuit.noise_model.save(update_fields=["state", "published_at"])

    assert not artifact_has_public_reference(artifact)
    assert _download(client, artifact).status_code == 404


def test_result_file_is_not_public_when_its_provenance_is_not_public(
    client, public_graph
):
    owner = Account.objects.create_user(display_name="Result file uploader")
    artifact, _content = _new_artifact("private-result", uploaded_by=owner)
    result = public_graph["result"]
    result.hyperparameter_values_artifact = artifact
    result.save(update_fields=["hyperparameter_values_artifact"])
    result.decoder_version.state = LifecycleState.CHANGES_REQUESTED
    result.decoder_version.published_at = None
    result.decoder_version.save(update_fields=["state", "published_at"])

    assert not artifact_has_public_reference(artifact)
    assert _download(client, artifact).status_code == 404
