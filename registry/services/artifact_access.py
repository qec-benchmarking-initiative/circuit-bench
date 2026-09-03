"""Authorization rules for immutable registry file downloads."""

from django.db.models import Exists, OuterRef, Q

from registry.models import (
    Artifact,
    ArtifactGrant,
    BenchmarkRevision,
    CircuitRevision,
    DecoderVersion,
    EvaluatorRelease,
    NoiseModel,
    Result,
    SchemaRelease,
)
from registry.models.common import LifecycleState

PUBLIC_RECORD_STATES = (
    LifecycleState.PUBLISHED,
    LifecycleState.WITHDRAWN,
)


def can_download_artifact(user, artifact: Artifact) -> bool:
    """Backward-compatible name for the registry's general read decision."""

    return can_read_artifact(user, artifact)


def can_read_artifact(user, artifact: Artifact) -> bool:
    """Return whether ``user`` may receive the immutable bytes for ``artifact``.

    Public references make a file public. Otherwise a durable per-account grant or
    active registry-admin status is required. This keeps orphaned uploads private
    without losing access when content-addressed deduplication retains a different
    account in the artifact's legacy ``uploaded_by`` provenance field.
    """

    return readable_artifacts_for(user).filter(pk=artifact.pk).exists()


def readable_artifacts_for(user):
    """Return files visible to a viewer under the same rule as exact downloads."""

    if (
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_admin", False)
    ):
        return Artifact.objects.all()

    artifacts = _with_public_reference_flags(Artifact.objects.all())
    access = _public_reference_condition()
    if getattr(user, "is_authenticated", False):
        artifacts = _with_private_submitter_reference_flags(artifacts, user.pk)
        grant = ArtifactGrant.objects.filter(
            artifact_id=OuterRef("pk"),
            account_id=getattr(user, "pk", None),
        )
        artifacts = artifacts.alias(account_access_grant=Exists(grant))
        access |= Q(account_access_grant=True) | _private_submitter_condition()
    return artifacts.filter(access)


def artifact_has_public_reference(artifact: Artifact) -> bool:
    """Return whether any public registry record directly references a file.

    Exact records remain public after withdrawal, so their files do too. Candidate
    states (draft, pending review or reapproval, changes requested, and rejected)
    never make a file public. Frozen and retired schema releases are permanent
    public references; draft releases remain private until frozen.

    Each subquery deliberately covers both a model's dedicated file fields and its
    generic ``ArtifactAttachment`` relation. Keep this list aligned with the
    artifact foreign keys and ``SUBJECT_FIELDS`` in ``registry.models.artifacts``.
    """

    return (
        _with_public_reference_flags(Artifact.objects.filter(pk=artifact.pk))
        .filter(_public_reference_condition())
        .exists()
    )


def _with_public_reference_flags(artifacts):
    schema_release = SchemaRelease.objects.filter(
        state__in=(SchemaRelease.State.FROZEN, SchemaRelease.State.RETIRED)
    ).filter(
        Q(json_schema_artifact_id=OuterRef("pk"))
        | Q(definitions_artifact_id=OuterRef("pk"))
    )
    decoder = DecoderVersion.objects.filter(
        state__in=PUBLIC_RECORD_STATES, visibility="public"
    ).filter(
        Q(hyperparameter_schema_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    noise_model = NoiseModel.objects.filter(
        state__in=PUBLIC_RECORD_STATES,
        visibility="public",
        artifact_attachments__artifact_id=OuterRef("pk"),
    )
    circuit = CircuitRevision.objects.filter(
        state__in=PUBLIC_RECORD_STATES,
        visibility="public",
        noise_model__state__in=PUBLIC_RECORD_STATES,
        noise_model__visibility="public",
    ).filter(
        Q(sampling_circuit_artifact_id=OuterRef("pk"))
        | Q(detector_error_model_artifact_id=OuterRef("pk"))
        | Q(manifest_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    evaluator = EvaluatorRelease.objects.filter(
        state__in=PUBLIC_RECORD_STATES,
        visibility="public",
    ).filter(
        Q(source_bundle_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    result = (
        Result.objects.filter(
            state__in=PUBLIC_RECORD_STATES,
            visibility="public",
            decoder_version__state__in=PUBLIC_RECORD_STATES,
            decoder_version__visibility="public",
            circuit_revision__state__in=PUBLIC_RECORD_STATES,
            circuit_revision__visibility="public",
            circuit_revision__noise_model__visibility="public",
            evaluator_version__state__in=PUBLIC_RECORD_STATES,
            evaluator_version__visibility="public",
        )
        .filter(
            Q(machine__isnull=True)
            | Q(machine__state__in=PUBLIC_RECORD_STATES, machine__visibility="public")
        )
        .filter(
            Q(hyperparameter_values_artifact_id=OuterRef("pk"))
            | Q(artifact_attachments__artifact_id=OuterRef("pk"))
        )
    )
    benchmark = BenchmarkRevision.objects.filter(
        state__in=PUBLIC_RECORD_STATES,
        visibility="public",
    ).filter(
        Q(manifest_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )

    return artifacts.alias(
        public_schema_release=Exists(schema_release),
        public_decoder=Exists(decoder),
        public_noise_model=Exists(noise_model),
        public_circuit=Exists(circuit),
        public_evaluator=Exists(evaluator),
        public_result=Exists(result),
        public_benchmark=Exists(benchmark),
    )


def _public_reference_condition() -> Q:
    return (
        Q(public_schema_release=True)
        | Q(public_decoder=True)
        | Q(public_noise_model=True)
        | Q(public_circuit=True)
        | Q(public_evaluator=True)
        | Q(public_result=True)
        | Q(public_benchmark=True)
    )


def _with_private_submitter_reference_flags(artifacts, account_id):
    decoder = DecoderVersion.objects.filter(submitted_by_id=account_id).filter(
        Q(hyperparameter_schema_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    noise_model = NoiseModel.objects.filter(
        submitted_by_id=account_id,
        artifact_attachments__artifact_id=OuterRef("pk"),
    )
    circuit = CircuitRevision.objects.filter(submitted_by_id=account_id).filter(
        Q(sampling_circuit_artifact_id=OuterRef("pk"))
        | Q(detector_error_model_artifact_id=OuterRef("pk"))
        | Q(manifest_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    evaluator = EvaluatorRelease.objects.filter(submitted_by_id=account_id).filter(
        Q(source_bundle_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    result = Result.objects.filter(submitted_by_id=account_id).filter(
        Q(hyperparameter_values_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    benchmark = BenchmarkRevision.objects.filter(submitted_by_id=account_id).filter(
        Q(manifest_artifact_id=OuterRef("pk"))
        | Q(artifact_attachments__artifact_id=OuterRef("pk"))
    )
    return artifacts.alias(
        private_submitter_decoder=Exists(decoder),
        private_submitter_noise_model=Exists(noise_model),
        private_submitter_circuit=Exists(circuit),
        private_submitter_evaluator=Exists(evaluator),
        private_submitter_result=Exists(result),
        private_submitter_benchmark=Exists(benchmark),
    )


def _private_submitter_condition() -> Q:
    return (
        Q(private_submitter_decoder=True)
        | Q(private_submitter_noise_model=True)
        | Q(private_submitter_circuit=True)
        | Q(private_submitter_evaluator=True)
        | Q(private_submitter_result=True)
        | Q(private_submitter_benchmark=True)
    )
