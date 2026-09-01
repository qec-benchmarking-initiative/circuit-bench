"""Central registration metadata for record kinds in the shared write workflow."""

from dataclasses import dataclass

from django.db.models import Model

from registry.models import CircuitRevision, DecoderVersion, Machine, Result
from registry.submission_policy import ENABLED_SUBMISSION_KINDS, SubmissionKind


@dataclass(frozen=True)
class SubmissionKindRegistration:
    kind: SubmissionKind
    model: type[Model]
    lineage_field: str
    reverse_lineage_relation: str | None
    public_route_name: str
    public_argument_attribute: str
    select_related: tuple[str, ...] = ()
    supports_replacement_withdrawal: bool = False


SUBMISSION_KIND_REGISTRY = {
    SubmissionKind.DECODER: SubmissionKindRegistration(
        kind=SubmissionKind.DECODER,
        model=DecoderVersion,
        lineage_field="previous_version",
        reverse_lineage_relation="next_version",
        public_route_name="decoders:detail",
        public_argument_attribute="slug",
        supports_replacement_withdrawal=True,
    ),
    SubmissionKind.CIRCUIT: SubmissionKindRegistration(
        kind=SubmissionKind.CIRCUIT,
        model=CircuitRevision,
        lineage_field="previous_revision",
        reverse_lineage_relation="next_revision",
        public_route_name="circuits:detail",
        public_argument_attribute="slug",
        supports_replacement_withdrawal=True,
    ),
    SubmissionKind.RESULT: SubmissionKindRegistration(
        kind=SubmissionKind.RESULT,
        model=Result,
        lineage_field="supersedes_result",
        reverse_lineage_relation="superseded_by",
        public_route_name="results:detail",
        public_argument_attribute="id",
        select_related=("decoder_version", "circuit_revision", "machine"),
    ),
    SubmissionKind.MACHINE: SubmissionKindRegistration(
        kind=SubmissionKind.MACHINE,
        model=Machine,
        lineage_field="supersedes_machine",
        reverse_lineage_relation=None,
        public_route_name="machines:detail",
        public_argument_attribute="slug",
    ),
}


def submission_registration(
    kind: SubmissionKind | str,
) -> SubmissionKindRegistration:
    """Return metadata only for a complete, enabled shared-workflow kind."""

    kind = SubmissionKind(kind)
    if kind not in ENABLED_SUBMISSION_KINDS:
        raise KeyError(f"Submission kind {kind.value!r} is not enabled.")
    return SUBMISSION_KIND_REGISTRY[kind]


def enabled_submission_registrations() -> tuple[SubmissionKindRegistration, ...]:
    return tuple(submission_registration(kind) for kind in ENABLED_SUBMISSION_KINDS)


# Compatibility projections for the existing service/presenter modules. New
# code should request the registration object instead of defining another map.
MODEL_BY_KIND = {
    registration.kind: registration.model
    for registration in enabled_submission_registrations()
}
LINEAGE_FIELD_BY_KIND = {
    registration.kind: registration.lineage_field
    for registration in enabled_submission_registrations()
}
