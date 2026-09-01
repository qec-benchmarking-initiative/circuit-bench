"""Transactional creation and approval for user-submitted registry records."""

from dataclasses import dataclass

from django.core.exceptions import (
    ObjectDoesNotExist,
)
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import transaction
from django.utils import timezone
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from accounts.models import Account
from registry.forms_submissions import submission_form_for_payload
from registry.models import (
    CircuitRevision,
    Credit,
    DecoderVersion,
    Machine,
    ModerationEvent,
    Result,
    ResultScore,
    SchemaRelease,
)
from registry.models.common import (
    EDITABLE_CANDIDATE_STATES,
    REVIEW_QUEUE_STATES,
    LifecycleState,
)
from registry.services.histories import (
    append_history_event,
    history_for_new_record,
    submission_snapshot,
)
from registry.submission_policy import (
    ApprovalDecision,
    SubmissionKind,
    approval_decision,
)
from registry.submission_registry import (
    LINEAGE_FIELD_BY_KIND,
    MODEL_BY_KIND,
    submission_registration,
)
from registry.submission_specs import get_submission_schema

PENDING_STATES = REVIEW_QUEUE_STATES
PUBLIC_HISTORY_STATES = ("published", "withdrawn")


class SubmissionError(Exception):
    pass


class SubmissionValidationError(SubmissionError):
    def __init__(self, message: str, *, form=None):
        super().__init__(message)
        self.form = form


class SubmissionStateError(SubmissionError):
    pass


@dataclass(frozen=True)
class SubmissionOutcome:
    kind: SubmissionKind
    record: object
    decision: ApprovalDecision


def validate_submission_payload(
    kind: SubmissionKind | str,
    payload: dict,
    *,
    record=None,
    allow_withdrawn_lineage: bool = False,
) -> dict:
    """Apply the public JSON Schema, then the same semantic form as HTML entry."""

    kind = SubmissionKind(kind)
    validator = Draft202012Validator(
        get_submission_schema(kind), format_checker=FormatChecker()
    )
    errors = sorted(validator.iter_errors(payload), key=_schema_error_sort_key)
    if errors:
        raise SubmissionValidationError(_schema_error_message(errors[0]))

    form = submission_form_for_payload(
        kind,
        payload,
        record=record,
        allow_withdrawn_lineage=allow_withdrawn_lineage,
    )
    if not form.is_valid():
        raise SubmissionValidationError(
            "The submission does not satisfy the registry rules.", form=form
        )
    return form.canonical_payload()


@transaction.atomic
def create_submission(
    kind: SubmissionKind | str, payload: dict, *, submitter: Account
) -> SubmissionOutcome:
    return _create_submission(kind, payload, submitter=submitter)


def _create_submission(
    kind: SubmissionKind | str,
    payload: dict,
    *,
    submitter: Account,
    reapproval: bool = False,
) -> SubmissionOutcome:
    kind = SubmissionKind(kind)
    payload = validate_submission_payload(
        kind, payload, allow_withdrawn_lineage=reapproval
    )
    form = submission_form_for_payload(
        kind, payload, allow_withdrawn_lineage=reapproval
    )
    if not form.is_valid():  # Defensive recheck within the transaction.
        raise SubmissionValidationError(
            "The submission became invalid before it was stored.", form=form
        )
    _assert_form_lineage_available(kind, form.cleaned_data)

    decision = approval_decision(kind, submitter, reapproval=reapproval)
    release = _frozen_schema_release(kind)
    published_at = timezone.now() if not decision.requires_review else None
    predecessor = form.cleaned_data.get(LINEAGE_FIELD_BY_KIND[kind])
    history = history_for_new_record(kind.value, predecessor)

    if kind is SubmissionKind.DECODER:
        record = _create_decoder(
            form.cleaned_data, submitter, release, decision, published_at, history
        )
    elif kind is SubmissionKind.CIRCUIT:
        record = _create_circuit(
            form.cleaned_data, submitter, release, decision, published_at, history
        )
    elif kind is SubmissionKind.RESULT:
        record = _create_result(
            form.cleaned_data, submitter, release, decision, published_at, history
        )
    else:
        record = _create_machine(
            form.cleaned_data, submitter, release, decision, published_at, history
        )

    event_details = {
        "policy_version": decision.policy_version,
        "approval_route": decision.route.value,
    }
    if predecessor is not None:
        append_history_event(
            kind=kind.value,
            record=record,
            actor=submitter,
            action=ModerationEvent.Action.REVISION_CREATED,
            note="Created this exact record as a successor revision.",
            details={
                "policy_version": decision.policy_version,
                "predecessor_id": str(predecessor.id),
            },
        )
    submission_event = append_history_event(
        kind=kind.value,
        record=record,
        actor=submitter,
        action=(
            ModerationEvent.Action.RESUBMITTED
            if reapproval
            else ModerationEvent.Action.SUBMITTED
        ),
        note=(
            "Submitted a successor for reapproval."
            if reapproval
            else "Submitted through the Circuit Bench write-side workflow."
        ),
        details={**event_details, "projected_state": decision.initial_state},
        payload_snapshot=submission_snapshot(kind.value, payload),
    )
    if not decision.requires_review:
        approval_event = append_history_event(
            kind=kind.value,
            record=record,
            actor_system="submission_policy",
            action=ModerationEvent.Action.APPROVED,
            note="Approved automatically under submission policy 0.1.",
            details={**event_details, "approved_by": "system"},
            caused_by=submission_event,
        )
        publication_event = append_history_event(
            kind=kind.value,
            record=record,
            actor_system="submission_policy",
            action=ModerationEvent.Action.PUBLISHED,
            note="Published immediately under submission policy 0.1.",
            details={**event_details, "approved_by": "system"},
            caused_by=approval_event,
        )
        record.published_at = publication_event.occurred_at
        record.save(update_fields=["published_at"])
    return SubmissionOutcome(kind=kind, record=record, decision=decision)


def submission_payload_for_record(kind: SubmissionKind | str, record) -> dict:
    """Return the canonical editable submission payload for an exact record."""

    kind = SubmissionKind(kind)
    if kind is SubmissionKind.DECODER:
        return {
            "slug": record.slug,
            "name": record.name,
            "version": record.version,
            "previous_version": _id_or_none(record.previous_version_id),
            "description": record.description,
            "revision_description": record.revision_description,
            "circuit_skeleton_preparation": record.circuit_skeleton_preparation,
            "circuit_priors_preparation": record.circuit_priors_preparation,
            "provides_failure_probability": record.provides_failure_probability,
            "hyperparameter_definitions": record.hyperparameter_definitions,
            "hyperparameter_schema_artifact": _id_or_none(
                record.hyperparameter_schema_artifact_id
            ),
            "algorithm_tags": [
                str(item)
                for item in record.algorithm_tags.order_by("id").values_list(
                    "id", flat=True
                )
            ],
        }
    if kind is SubmissionKind.CIRCUIT:
        return {
            "slug": record.slug,
            "name": record.name,
            "previous_revision": _id_or_none(record.previous_revision_id),
            "description": record.description,
            "revision_description": record.revision_description,
            "noise_model": str(record.noise_model_id),
            "is_css": record.is_css,
            "code_distance_upper_bound": record.code_distance_upper_bound,
            "circuit_distance_upper_bound": record.circuit_distance_upper_bound,
            "rounds": record.rounds,
            "num_detectors": record.num_detectors,
            "num_errors": record.num_errors,
            "num_observables": record.num_observables,
            "dem_x_detectors_only": record.dem_x_detectors_only,
            "dem_z_detectors_only": record.dem_z_detectors_only,
            "stim_version": record.stim_version,
            "dem_decompose_errors": record.dem_decompose_errors,
            "dem_flatten_loops": record.dem_flatten_loops,
            "dem_allow_gauge_detectors": record.dem_allow_gauge_detectors,
            "dem_approximate_disjoint_errors": record.dem_approximate_disjoint_errors,
            "dem_ignore_decomposition_failures": (
                record.dem_ignore_decomposition_failures
            ),
            "dem_block_decomposition_from_introducing_remnant_edges": (
                record.dem_block_decomposition_from_introducing_remnant_edges
            ),
            "sampling_circuit_artifact": str(record.sampling_circuit_artifact_id),
            "detector_error_model_artifact": str(
                record.detector_error_model_artifact_id
            ),
            "manifest_artifact": str(record.manifest_artifact_id),
            "code_tags": [
                str(item)
                for item in record.code_tags.order_by("id").values_list("id", flat=True)
            ],
            "experiment_tags": [
                str(item)
                for item in record.experiment_tags.order_by("id").values_list(
                    "id", flat=True
                )
            ],
        }
    if kind is SubmissionKind.RESULT:
        return {
            "decoder_version": str(record.decoder_version_id),
            "circuit_revision": str(record.circuit_revision_id),
            "evaluator_version": str(record.evaluator_version_id),
            "machine": _id_or_none(record.machine_id),
            "description": record.description,
            "hyperparameter_values": record.hyperparameter_values,
            "hyperparameter_values_artifact": _id_or_none(
                record.hyperparameter_values_artifact_id
            ),
            "shots_total": record.shots_total,
            "successful_shots": record.successful_shots,
            "logical_failure_shots": record.logical_failure_shots,
            "timeout_shots": record.timeout_shots,
            "decoder_error_shots": record.decoder_error_shots,
            "failure_probability_shots": record.failure_probability_shots,
            "latency_shots": record.latency_shots,
            "preparation_duration_seconds": _decimal_or_none(
                record.preparation_duration_seconds
            ),
            "training_workload_description": record.training_workload_description,
            "software_environment": record.software_environment,
            "t_1000_ns": record.t_1000_ns,
            "supersedes_result": _id_or_none(record.supersedes_result_id),
            "reproduction_status": record.reproduction_status,
            "scores": [
                {
                    "score_definition": str(score.score_definition_id),
                    "value": str(score.value),
                    "point_estimate": _decimal_or_none(score.point_estimate),
                    "lower_bound": _decimal_or_none(score.lower_bound),
                    "upper_bound": _decimal_or_none(score.upper_bound),
                    "confidence_level": _decimal_or_none(score.confidence_level),
                    "sample_count": score.sample_count,
                    "event_count": score.event_count,
                    "details": score.details,
                }
                for score in record.scores.order_by("score_definition_id")
            ],
        }
    return {
        "slug": record.slug,
        "machine_class": record.machine_class,
        "description": record.description,
        "status": record.status,
        "supersedes_machine": _id_or_none(record.supersedes_machine_id),
    }


def candidate_review_route(kind: SubmissionKind | str, record) -> LifecycleState:
    """Recover the review queue a mutable candidate must return to.

    A changes-requested state deliberately does not erase whether the exact
    candidate was awaiting first approval or reapproval after withdrawal.
    """

    kind = SubmissionKind(kind)
    if record.state == LifecycleState.PENDING_REAPPROVAL:
        return LifecycleState.PENDING_REAPPROVAL
    latest_transition = (
        record.moderation_events.filter(
            action__in=(
                ModerationEvent.Action.SUBMITTED,
                ModerationEvent.Action.RESUBMITTED,
                ModerationEvent.Action.REQUESTED_CHANGES,
            )
        )
        .order_by("-sequence", "-id")
        .first()
    )
    if latest_transition is not None:
        key = (
            "previous_state"
            if latest_transition.action == ModerationEvent.Action.REQUESTED_CHANGES
            else "projected_state"
        )
        projected = latest_transition.details.get(key)
        if projected in REVIEW_QUEUE_STATES:
            return LifecycleState(projected)
    predecessor_id = getattr(record, f"{LINEAGE_FIELD_BY_KIND[kind]}_id")
    if predecessor_id is not None:
        predecessor = getattr(record, LINEAGE_FIELD_BY_KIND[kind])
        if predecessor.state == LifecycleState.WITHDRAWN:
            return LifecycleState.PENDING_REAPPROVAL
    return LifecycleState.PENDING_REVIEW


def candidate_lineage_is_locked(kind: SubmissionKind | str, record) -> bool:
    """Return whether an in-place edit must retain its predecessor exactly."""

    kind = SubmissionKind(kind)
    return bool(
        getattr(record, f"{LINEAGE_FIELD_BY_KIND[kind]}_id")
        and candidate_review_route(kind, record) == LifecycleState.PENDING_REAPPROVAL
    )


@transaction.atomic
def update_pending_submission(
    kind: SubmissionKind | str,
    record_id,
    payload: dict,
    *,
    actor: Account,
) -> object:
    """Edit an unpublished candidate without changing its exact UUID."""

    kind = SubmissionKind(kind)
    record = _managed_record(kind, record_id, actor=actor)
    if record.state not in EDITABLE_CANDIDATE_STATES:
        raise SubmissionStateError(
            "Only pending submissions or submissions with requested changes can "
            "be edited in place."
        )

    if candidate_lineage_is_locked(kind, record):
        payload = dict(payload)
        source = getattr(record, f"{LINEAGE_FIELD_BY_KIND[kind]}_id")
        payload[LINEAGE_FIELD_BY_KIND[kind]] = _id_or_none(source)

    payload = validate_submission_payload(kind, payload, record=record)
    form = submission_form_for_payload(kind, payload, record=record)
    if not form.is_valid():
        raise SubmissionValidationError(
            "The edit became invalid before it was stored.", form=form
        )
    _update_record(kind, record, form.cleaned_data)
    append_history_event(
        kind=kind.value,
        record=record,
        actor=actor,
        action=ModerationEvent.Action.EDITED,
        note="Edited while awaiting review; the exact candidate UUID was retained.",
        details={"policy_version": "0.1", "state": record.state},
        payload_snapshot=submission_snapshot(kind.value, payload),
    )
    return record


@transaction.atomic
def create_successor_submission(
    kind: SubmissionKind | str,
    source_id,
    payload: dict,
    *,
    actor: Account,
    withdraw_source: bool = False,
) -> SubmissionOutcome:
    """Create an immutable successor, optionally withdrawing its source atomically."""

    kind = SubmissionKind(kind)
    source = _managed_record(kind, source_id, actor=actor)
    if source.state not in PUBLIC_HISTORY_STATES:
        raise SubmissionStateError(
            "Only a published or withdrawn record can receive a successor."
        )
    _assert_successor_available(kind, source)
    if withdraw_source:
        if kind not in {SubmissionKind.DECODER, SubmissionKind.CIRCUIT}:
            raise SubmissionStateError(
                "Only decoder and circuit revisions support replacement withdrawal."
            )
        if source.state != "published":
            raise SubmissionStateError(
                "Only a published predecessor can be withdrawn during revision."
            )
        source = withdraw_submission(
            kind,
            source.id,
            actor=actor,
            note=(
                "Withdrawn while submitting an immutable successor revision for "
                "reapproval."
            ),
        )
    payload = dict(payload)
    payload[LINEAGE_FIELD_BY_KIND[kind]] = str(source.id)
    outcome = _create_submission(
        kind,
        payload,
        submitter=actor,
        reapproval=source.state == "withdrawn",
    )
    return outcome


@transaction.atomic
def withdraw_submission(
    kind: SubmissionKind | str,
    record_id,
    *,
    actor: Account,
    note: str,
) -> object:
    kind = SubmissionKind(kind)
    record = _managed_record(kind, record_id, actor=actor)
    if record.state != "published":
        raise SubmissionStateError("Only a published record can be withdrawn.")
    event = append_history_event(
        kind=kind.value,
        record=record,
        actor=actor,
        action=ModerationEvent.Action.WITHDRAWN,
        note=note.strip() or "Withdrawn by the uploader or an admin.",
        details={"policy_version": "0.1"},
    )
    record.state = "withdrawn"
    record.withdrawn_at = event.occurred_at
    record.full_clean(exclude=_full_clean_exclusions(kind))
    record.save(update_fields=["state", "withdrawn_at"])
    return record


@transaction.atomic
def approve_submission(
    kind: SubmissionKind | str,
    record_id,
    *,
    reviewer: Account,
) -> object:
    kind = SubmissionKind(kind)
    if not reviewer.is_active or not reviewer.is_admin:
        raise PermissionError("Only active admins may approve submissions.")
    model = MODEL_BY_KIND[kind]
    try:
        record = model.objects.select_for_update().get(id=record_id)
    except model.DoesNotExist as error:
        raise SubmissionStateError("Submission not found.") from error
    if record.state not in PENDING_STATES:
        raise SubmissionStateError("Only pending submissions can be approved.")
    if (
        record.state == "pending_review"
        and not approval_decision(kind, reviewer).requires_review
    ):
        raise SubmissionStateError(
            f"{kind.value.title()} records do not normally require review."
        )

    previous_state = record.state
    _revalidate_record_for_publication(kind, record)
    details = {
        "policy_version": "0.1",
        "approval_route": "admin_review",
        "approved_by": str(reviewer.id),
        "approved_by_name": reviewer.display_name,
        "previous_state": previous_state,
    }
    approval_event = append_history_event(
        kind=kind.value,
        record=record,
        actor=reviewer,
        action=ModerationEvent.Action.APPROVED,
        note="Approved by an admin after publication-time revalidation.",
        details=details,
    )
    publication_event = append_history_event(
        kind=kind.value,
        record=record,
        actor=reviewer,
        action=ModerationEvent.Action.PUBLISHED,
        note="Published as the result of admin approval.",
        details=details,
        caused_by=approval_event,
    )
    record.state = "published"
    record.published_at = publication_event.occurred_at
    record.withdrawn_at = None
    record.full_clean(exclude=_full_clean_exclusions(kind))
    record.save(update_fields=["state", "published_at", "withdrawn_at"])
    return record


def record_url(kind: SubmissionKind | str, record) -> str | None:
    from django.urls import reverse

    kind = SubmissionKind(kind)
    if record.state not in PUBLIC_HISTORY_STATES:
        return None
    registration = submission_registration(kind)
    argument = getattr(record, registration.public_argument_attribute)
    return reverse(registration.public_route_name, args=[argument])


def record_label(kind: SubmissionKind | str, record) -> str:
    kind = SubmissionKind(kind)
    if kind is SubmissionKind.DECODER:
        return f"{record.name} {record.version}"
    if kind is SubmissionKind.CIRCUIT:
        return record.name
    if kind is SubmissionKind.RESULT:
        return f"{record.decoder_version} on {record.circuit_revision}"
    return record.slug


def _managed_record(kind: SubmissionKind, record_id, *, actor: Account):
    if not actor.is_active:
        raise PermissionError("Inactive accounts cannot manage submissions.")
    model = MODEL_BY_KIND[kind]
    try:
        record = model.objects.select_for_update().get(id=record_id)
    except model.DoesNotExist as error:
        raise SubmissionStateError("Submission not found.") from error
    if record.submitted_by_id != actor.id and not actor.is_admin:
        raise PermissionError("Only the uploader or an admin may manage this record.")
    return record


def _assert_successor_available(kind, source, *, excluding=None):
    reverse_name = submission_registration(kind).reverse_lineage_relation
    if reverse_name is None:
        return
    try:
        successor = getattr(source, reverse_name)
    except ObjectDoesNotExist:
        return
    if excluding is None or successor.id != excluding.id:
        raise SubmissionStateError("This exact record already has a successor.")


def _assert_form_lineage_available(kind, cleaned, *, excluding=None):
    source = cleaned.get(LINEAGE_FIELD_BY_KIND[kind])
    if source is not None:
        _assert_successor_available(kind, source, excluding=excluding)


def _update_record(kind, record, cleaned):
    _assert_form_lineage_available(kind, cleaned, excluding=record)
    if kind is SubmissionKind.DECODER:
        for name in (
            "slug",
            "name",
            "version",
            "previous_version",
            "revision_description",
            "circuit_skeleton_preparation",
            "circuit_priors_preparation",
            "provides_failure_probability",
            "hyperparameter_schema_artifact",
        ):
            setattr(record, name, cleaned[name])
        record.description = cleaned["description"] or None
        record.hyperparameter_definitions = (
            cleaned["hyperparameter_definitions"] or None
        )
        record.full_clean(exclude=_full_clean_exclusions(kind))
        record.save()
        record.algorithm_tags.set(cleaned["algorithm_tags"])
        return
    if kind is SubmissionKind.CIRCUIT:
        for name in (
            "slug",
            "name",
            "previous_revision",
            "revision_description",
            "noise_model",
            "is_css",
            "code_distance_upper_bound",
            "circuit_distance_upper_bound",
            "rounds",
            "num_detectors",
            "num_errors",
            "num_observables",
            "dem_x_detectors_only",
            "dem_z_detectors_only",
            "stim_version",
            "dem_decompose_errors",
            "dem_flatten_loops",
            "dem_allow_gauge_detectors",
            "dem_ignore_decomposition_failures",
            "dem_block_decomposition_from_introducing_remnant_edges",
            "sampling_circuit_artifact",
            "detector_error_model_artifact",
            "manifest_artifact",
        ):
            setattr(record, name, cleaned[name])
        record.description = cleaned["description"] or None
        record.dem_approximate_disjoint_errors = cleaned[
            "dem_approximate_disjoint_errors"
        ]
        record.full_clean(exclude=_full_clean_exclusions(kind))
        record.save()
        record.code_tags.set(cleaned["code_tags"])
        record.experiment_tags.set(cleaned["experiment_tags"])
        return
    if kind is SubmissionKind.RESULT:
        for name in (
            "decoder_version",
            "circuit_revision",
            "evaluator_version",
            "machine",
            "hyperparameter_values_artifact",
            "shots_total",
            "successful_shots",
            "logical_failure_shots",
            "timeout_shots",
            "decoder_error_shots",
            "failure_probability_shots",
            "latency_shots",
            "preparation_duration_seconds",
            "t_1000_ns",
            "supersedes_result",
            "reproduction_status",
        ):
            setattr(record, name, cleaned[name])
        for name in (
            "description",
            "hyperparameter_values",
            "training_workload_description",
            "software_environment",
        ):
            setattr(record, name, cleaned[name] or None)
        record.full_clean()
        record.save()
        record.scores.all().delete()
        _create_result_scores(record, cleaned["scores_json"])
        return
    for name in (
        "slug",
        "machine_class",
        "description",
        "status",
        "supersedes_machine",
    ):
        setattr(record, name, cleaned[name])
    record.full_clean()
    record.save()


def _id_or_none(value):
    return str(value) if value is not None else None


def _decimal_or_none(value):
    return str(value) if value is not None else None


def _create_decoder(cleaned, submitter, release, decision, published_at, history):
    record = DecoderVersion.objects.create(
        schema_release=release,
        history=history,
        slug=cleaned["slug"],
        name=cleaned["name"],
        version=cleaned["version"],
        previous_version=cleaned["previous_version"],
        description=cleaned["description"] or None,
        revision_description=cleaned["revision_description"],
        circuit_skeleton_preparation=cleaned["circuit_skeleton_preparation"],
        circuit_priors_preparation=cleaned["circuit_priors_preparation"],
        provides_failure_probability=cleaned["provides_failure_probability"],
        hyperparameter_definitions=cleaned["hyperparameter_definitions"] or None,
        hyperparameter_schema_artifact=cleaned["hyperparameter_schema_artifact"],
        submitted_by=submitter,
        state=decision.initial_state,
        published_at=published_at,
    )
    record.algorithm_tags.set(cleaned["algorithm_tags"])
    Credit.objects.create(decoder_version=record, position=1, account=submitter)
    return record


def _create_circuit(cleaned, submitter, release, decision, published_at, history):
    record = CircuitRevision.objects.create(
        schema_release=release,
        history=history,
        slug=cleaned["slug"],
        name=cleaned["name"],
        previous_revision=cleaned["previous_revision"],
        description=cleaned["description"] or None,
        revision_description=cleaned["revision_description"],
        noise_model=cleaned["noise_model"],
        is_css=cleaned["is_css"],
        code_distance_upper_bound=cleaned["code_distance_upper_bound"],
        circuit_distance_upper_bound=cleaned["circuit_distance_upper_bound"],
        rounds=cleaned["rounds"],
        num_detectors=cleaned["num_detectors"],
        num_errors=cleaned["num_errors"],
        num_observables=cleaned["num_observables"],
        dem_x_detectors_only=cleaned["dem_x_detectors_only"],
        dem_z_detectors_only=cleaned["dem_z_detectors_only"],
        stim_version=cleaned["stim_version"],
        dem_generation_method="stim.Circuit.detector_error_model",
        dem_decompose_errors=cleaned["dem_decompose_errors"],
        dem_flatten_loops=cleaned["dem_flatten_loops"],
        dem_allow_gauge_detectors=cleaned["dem_allow_gauge_detectors"],
        dem_approximate_disjoint_errors=cleaned["dem_approximate_disjoint_errors"],
        dem_ignore_decomposition_failures=cleaned["dem_ignore_decomposition_failures"],
        dem_block_decomposition_from_introducing_remnant_edges=cleaned[
            "dem_block_decomposition_from_introducing_remnant_edges"
        ],
        sampling_circuit_artifact=cleaned["sampling_circuit_artifact"],
        detector_error_model_artifact=cleaned["detector_error_model_artifact"],
        manifest_artifact=cleaned["manifest_artifact"],
        submitted_by=submitter,
        state=decision.initial_state,
        published_at=published_at,
    )
    record.code_tags.set(cleaned["code_tags"])
    record.experiment_tags.set(cleaned["experiment_tags"])
    Credit.objects.create(circuit_revision=record, position=1, account=submitter)
    return record


def _create_result(cleaned, submitter, release, decision, published_at, history):
    record = Result.objects.create(
        schema_release=release,
        history=history,
        decoder_version=cleaned["decoder_version"],
        circuit_revision=cleaned["circuit_revision"],
        evaluator_version=cleaned["evaluator_version"],
        machine=cleaned["machine"],
        description=cleaned["description"] or None,
        hyperparameter_values=cleaned["hyperparameter_values"] or None,
        hyperparameter_values_artifact=cleaned["hyperparameter_values_artifact"],
        shots_total=cleaned["shots_total"],
        successful_shots=cleaned["successful_shots"],
        logical_failure_shots=cleaned["logical_failure_shots"],
        timeout_shots=cleaned["timeout_shots"],
        decoder_error_shots=cleaned["decoder_error_shots"],
        failure_probability_shots=cleaned["failure_probability_shots"],
        latency_shots=cleaned["latency_shots"],
        preparation_duration_seconds=cleaned["preparation_duration_seconds"],
        training_workload_description=cleaned["training_workload_description"] or None,
        software_environment=cleaned["software_environment"] or None,
        t_1000_ns=cleaned["t_1000_ns"],
        supersedes_result=cleaned["supersedes_result"],
        reproduction_status=cleaned["reproduction_status"],
        submitted_by=submitter,
        state=decision.initial_state,
        published_at=published_at,
    )
    _create_result_scores(record, cleaned["scores_json"])
    Credit.objects.create(result=record, position=1, account=submitter)
    return record


def _create_result_scores(record, scores):
    ResultScore.objects.bulk_create(
        [
            ResultScore(
                result=record,
                score_definition_id=item["score_definition"],
                evaluator_version=record.evaluator_version,
                value=item["value"],
                point_estimate=item["point_estimate"],
                lower_bound=item["lower_bound"],
                upper_bound=item["upper_bound"],
                confidence_level=item["confidence_level"],
                sample_count=item["sample_count"],
                event_count=item["event_count"],
                details=item["details"],
            )
            for item in scores
        ]
    )


def _create_machine(cleaned, submitter, release, decision, published_at, history):
    return Machine.objects.create(
        schema_release=release,
        history=history,
        slug=cleaned["slug"],
        machine_class=cleaned["machine_class"],
        description=cleaned["description"],
        status=cleaned["status"],
        supersedes_machine=cleaned["supersedes_machine"],
        submitted_by=submitter,
        state=decision.initial_state,
        published_at=published_at,
    )


def _frozen_schema_release(kind: SubmissionKind) -> SchemaRelease:
    try:
        return SchemaRelease.objects.get(
            record_type=kind.value,
            version="0.1",
            state=SchemaRelease.State.FROZEN,
        )
    except SchemaRelease.DoesNotExist as error:
        raise SubmissionStateError(
            f"Frozen {kind.value}/0.1 schema release is unavailable."
        ) from error


def _revalidate_record_for_publication(kind: SubmissionKind, record) -> None:
    if kind is SubmissionKind.DECODER:
        if (
            record.previous_version
            and record.previous_version.state not in PUBLIC_HISTORY_STATES
        ):
            raise SubmissionStateError(
                "The previous decoder version is neither published nor "
                "withdrawn history."
            )
        if not record.previous_version and not (record.description or "").strip():
            raise SubmissionStateError("The first decoder version needs a description.")
    elif kind is SubmissionKind.CIRCUIT:
        if (
            record.previous_revision
            and record.previous_revision.state not in PUBLIC_HISTORY_STATES
        ):
            raise SubmissionStateError(
                "The previous circuit revision is neither published nor "
                "withdrawn history."
            )
        if record.noise_model.state != "published":
            raise SubmissionStateError("The referenced noise model is not published.")
        if not record.previous_revision and not (record.description or "").strip():
            raise SubmissionStateError(
                "The first circuit revision needs a description."
            )
    elif kind is SubmissionKind.RESULT:
        references = (
            (record.decoder_version, "decoder version"),
            (record.circuit_revision, "circuit revision"),
            (record.evaluator_version, "evaluator release"),
            (record.machine, "machine"),
        )
        for reference, label in references:
            if reference is None or reference.state != "published":
                raise SubmissionStateError(f"The referenced {label} is not published.")
        if record.scores.exclude(evaluator_version=record.evaluator_version).exists():
            raise SubmissionStateError(
                "A score belongs to a different evaluator release."
            )
        if not record.scores.exists():
            raise SubmissionStateError("A result needs at least one evaluator score.")
        if (
            record.supersedes_result
            and record.supersedes_result.state not in PUBLIC_HISTORY_STATES
        ):
            raise SubmissionStateError(
                "The superseded result is neither published nor withdrawn history."
            )
    elif kind is SubmissionKind.MACHINE:
        if (
            record.supersedes_machine
            and record.supersedes_machine.state not in PUBLIC_HISTORY_STATES
        ):
            raise SubmissionStateError(
                "The superseded machine is neither published nor withdrawn history."
            )
    try:
        record.full_clean(exclude=_full_clean_exclusions(kind))
    except DjangoValidationError as error:
        raise SubmissionStateError(str(error)) from error


def _full_clean_exclusions(kind: SubmissionKind) -> list[str]:
    if kind is SubmissionKind.DECODER:
        return ["algorithm_tags"]
    if kind is SubmissionKind.CIRCUIT:
        return ["code_tags", "experiment_tags"]
    return []


def _schema_error_sort_key(error: JsonSchemaValidationError):
    return tuple(str(part) for part in error.absolute_path)


def _schema_error_message(error: JsonSchemaValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path)
    prefix = f"{path}: " if path else ""
    return f"JSON Schema error — {prefix}{error.message}"
