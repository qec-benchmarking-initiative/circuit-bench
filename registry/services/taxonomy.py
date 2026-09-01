"""Transactional curation workflows for tags and noise models.

This module is intentionally independent of the generic submission adapter.  Tags
have a provisional, immediately usable vocabulary route, while noise models enter
the review queue without becoming publicly discoverable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Account
from registry.models import ModerationEvent, NoiseModel, SchemaRelease, Tag
from registry.services.histories import (
    append_history_event,
    history_for_new_record,
    latest_snapshot_event,
    submission_snapshot,
)

POLICY_VERSION = "0.1"
CUSTOM_VOCABULARY_ROUTE = "provisional_custom_vocabulary"
ADMIN_REVIEW_ROUTE = "admin_review"
CUSTOM_VOCABULARY_SYSTEM = "custom_vocabulary_policy"
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLOUR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
PUBLIC_NOISE_MODEL_STATES = ("published", "withdrawn")
PENDING_NOISE_MODEL_STATES = ("pending_review", "pending_reapproval")


class TaxonomyError(Exception):
    """Base exception for taxonomy workflow failures."""


class TaxonomyPermissionError(TaxonomyError, PermissionError):
    """The account is not allowed to perform the requested action."""


class TaxonomyStateError(TaxonomyError):
    """The requested transition is not valid for the current record state."""


class TaxonomyConflictError(TaxonomyError):
    """An immutable identity or lineage relationship already exists."""


class TaxonomyValidationError(TaxonomyError, ValueError):
    """Submitted values do not satisfy the taxonomy contract."""


@dataclass(frozen=True)
class TagCreationOutcome:
    tag: Tag
    submission_event: ModerationEvent
    approval_event: ModerationEvent
    publication_event: ModerationEvent


@dataclass(frozen=True)
class NoiseModelSubmissionOutcome:
    noise_model: NoiseModel
    submission_event: ModerationEvent


def create_custom_tag(
    *,
    submitter: Account,
    namespace: str,
    slug: str,
    label: str,
    description: str,
) -> TagCreationOutcome:
    """Create an immediately usable custom tag with an explicit system route."""

    _require_active(submitter)
    namespace = namespace.strip()
    slug = slug.strip()
    label = label.strip()
    description = description.strip()
    _validate_tag_values(namespace, slug, label, description)

    try:
        with transaction.atomic():
            if Tag.objects.filter(namespace=namespace, slug=slug).exists():
                raise TaxonomyConflictError(
                    "That tag identity is already present as a tag or canonical alias."
                )
            release = _frozen_schema_release(SchemaRelease.RecordType.TAG)
            history = history_for_new_record("tag")
            tag = Tag.objects.create(
                schema_release=release,
                history=history,
                namespace=namespace,
                slug=slug,
                label=label,
                description=description,
                status=Tag.Status.CUSTOM,
                display_color=None,
                canonical_tag=None,
                submitted_by=submitter,
                curated_by=None,
                curated_at=None,
            )
            details = {
                "policy_version": POLICY_VERSION,
                "approval_route": CUSTOM_VOCABULARY_ROUTE,
                "projected_status": Tag.Status.CUSTOM,
            }
            submission_event = append_history_event(
                kind="tag",
                record=tag,
                actor=submitter,
                action=ModerationEvent.Action.SUBMITTED,
                note="Submitted a custom vocabulary term.",
                details=details,
                payload_snapshot=submission_snapshot(
                    "tag",
                    {
                        "namespace": namespace,
                        "slug": slug,
                        "label": label,
                        "description": description,
                        "status": Tag.Status.CUSTOM,
                    },
                ),
            )
            approval_event = append_history_event(
                kind="tag",
                record=tag,
                actor_system=CUSTOM_VOCABULARY_SYSTEM,
                action=ModerationEvent.Action.APPROVED,
                note="Approved provisionally for immediate custom-vocabulary use.",
                details={**details, "approved_by": "system"},
                caused_by=submission_event,
            )
            publication_event = append_history_event(
                kind="tag",
                record=tag,
                actor_system=CUSTOM_VOCABULARY_SYSTEM,
                action=ModerationEvent.Action.PUBLISHED,
                note="Made immediately available as a custom tag.",
                details={**details, "approved_by": "system"},
                caused_by=approval_event,
            )
            return TagCreationOutcome(
                tag=tag,
                submission_event=submission_event,
                approval_event=approval_event,
                publication_event=publication_event,
            )
    except IntegrityError as error:
        raise TaxonomyConflictError(
            "That tag identity was created by another request."
        ) from error


@transaction.atomic
def promote_tag_official(tag_id, *, curator: Account, display_color: str) -> Tag:
    """Promote one custom tag to official vocabulary."""

    _require_admin(curator)
    display_color = display_color.strip().upper()
    if not COLOUR_PATTERN.fullmatch(display_color):
        raise TaxonomyValidationError(
            "Use a six-digit hexadecimal colour such as #315F7D."
        )
    tag = _locked_tag(tag_id)
    if tag.status != Tag.Status.CUSTOM or tag.canonical_tag_id is not None:
        raise TaxonomyStateError("Only an active custom tag can be promoted.")

    previous_status = tag.status
    tag.status = Tag.Status.OFFICIAL
    tag.display_color = display_color
    tag.curated_by = curator
    tag.curated_at = timezone.now()
    tag.save(update_fields=["status", "display_color", "curated_by", "curated_at"])
    append_history_event(
        kind="tag",
        record=tag,
        actor=curator,
        action=ModerationEvent.Action.PROMOTED_OFFICIAL,
        note="Promoted this term into the official vocabulary.",
        details={
            "policy_version": POLICY_VERSION,
            "previous_status": previous_status,
            "new_status": Tag.Status.OFFICIAL,
            "display_color": display_color,
        },
    )
    return tag


@transaction.atomic
def deprecate_tag(tag_id, *, curator: Account, canonical_tag_id) -> Tag:
    """Deprecate a term and merge its meaning into one canonical term."""

    _require_admin(curator)
    tag_pk = Tag._meta.pk.to_python(tag_id)
    canonical_pk = Tag._meta.pk.to_python(canonical_tag_id)
    if canonical_pk == tag_pk:
        raise TaxonomyValidationError("A tag cannot replace itself.")
    # A deterministic order avoids a lock inversion if two admins concurrently
    # attempt opposing mappings.
    locked = {
        item.id: item
        for item in Tag.objects.select_for_update()
        .filter(id__in=(tag_pk, canonical_pk))
        .order_by("id")
    }
    tag = locked.get(tag_pk)
    canonical = locked.get(canonical_pk)
    if tag is None:
        raise TaxonomyStateError("Tag not found.")
    if canonical is None:
        raise TaxonomyStateError("The canonical replacement does not exist.")
    if tag.status == Tag.Status.DEPRECATED:
        raise TaxonomyStateError("This tag is already deprecated.")
    if canonical.namespace != tag.namespace:
        raise TaxonomyValidationError(
            "The canonical replacement must use the same namespace."
        )
    if canonical.status == Tag.Status.DEPRECATED or canonical.canonical_tag_id:
        raise TaxonomyConflictError(
            "The canonical replacement must itself be an active canonical tag."
        )

    previous_status = tag.status
    tag.status = Tag.Status.DEPRECATED
    tag.canonical_tag = canonical
    tag.curated_by = curator
    tag.curated_at = timezone.now()
    tag.save(update_fields=["status", "canonical_tag", "curated_by", "curated_at"])
    deprecated_event = append_history_event(
        kind="tag",
        record=tag,
        actor=curator,
        action=ModerationEvent.Action.DEPRECATED,
        note="Deprecated this vocabulary term.",
        details={
            "policy_version": POLICY_VERSION,
            "previous_status": previous_status,
            "canonical_tag_id": str(canonical.id),
            "canonical_identity": f"{canonical.namespace}:{canonical.slug}",
        },
    )
    append_history_event(
        kind="tag",
        record=tag,
        actor=curator,
        action=ModerationEvent.Action.MERGED,
        note="Mapped this term permanently to its canonical replacement.",
        details={
            "policy_version": POLICY_VERSION,
            "canonical_tag_id": str(canonical.id),
            "canonical_identity": f"{canonical.namespace}:{canonical.slug}",
        },
        caused_by=deprecated_event,
    )
    return tag


def submit_noise_model(
    *,
    submitter: Account,
    slug: str,
    name: str,
    short_description: str,
    paper_url: str,
    randomises_priors: bool,
    predecessor: NoiseModel | None = None,
) -> NoiseModelSubmissionOutcome:
    """Store a community noise model as a private pending-review candidate."""

    _require_active(submitter)
    slug = slug.strip()
    name = name.strip()
    short_description = short_description.strip()
    paper_url = paper_url.strip()
    _validate_noise_model_values(slug, name, short_description, paper_url)

    try:
        with transaction.atomic():
            locked_predecessor = None
            if predecessor is not None:
                try:
                    locked_predecessor = (
                        NoiseModel.objects.select_for_update()
                        .select_related("history")
                        .get(id=predecessor.id)
                    )
                except NoiseModel.DoesNotExist as error:
                    raise TaxonomyStateError(
                        "The predecessor noise model does not exist."
                    ) from error
                if locked_predecessor.state not in PUBLIC_NOISE_MODEL_STATES:
                    raise TaxonomyStateError(
                        "A predecessor must be published or withdrawn history."
                    )
                if NoiseModel.objects.filter(
                    supersedes_noise_model=locked_predecessor
                ).exists():
                    raise TaxonomyConflictError(
                        "That exact noise model already has a successor."
                    )
            if NoiseModel.objects.filter(slug=slug).exists():
                raise TaxonomyConflictError("That noise-model slug is already in use.")

            release = _frozen_schema_release(SchemaRelease.RecordType.NOISE_MODEL)
            history = history_for_new_record("noise_model", locked_predecessor)
            initial_state = (
                "pending_reapproval"
                if locked_predecessor is not None
                and locked_predecessor.state == "withdrawn"
                else "pending_review"
            )
            noise_model = NoiseModel.objects.create(
                schema_release=release,
                history=history,
                slug=slug,
                name=name,
                short_description=short_description,
                paper_url=paper_url,
                randomises_priors=bool(randomises_priors),
                supersedes_noise_model=locked_predecessor,
                curation_status=NoiseModel.CurationStatus.COMMUNITY,
                submitted_by=submitter,
                state=initial_state,
                published_at=None,
                withdrawn_at=None,
            )
            if locked_predecessor is not None:
                append_history_event(
                    kind="noise_model",
                    record=noise_model,
                    actor=submitter,
                    action=ModerationEvent.Action.REVISION_CREATED,
                    note="Created a successor noise-model revision.",
                    details={
                        "policy_version": POLICY_VERSION,
                        "predecessor_id": str(locked_predecessor.id),
                    },
                )
            payload = {
                "slug": slug,
                "name": name,
                "short_description": short_description,
                "paper_url": paper_url,
                "randomises_priors": bool(randomises_priors),
                "supersedes_noise_model": (
                    str(locked_predecessor.id) if locked_predecessor else None
                ),
                "curation_status": NoiseModel.CurationStatus.COMMUNITY,
            }
            submission_event = append_history_event(
                kind="noise_model",
                record=noise_model,
                actor=submitter,
                action=(
                    ModerationEvent.Action.RESUBMITTED
                    if initial_state == "pending_reapproval"
                    else ModerationEvent.Action.SUBMITTED
                ),
                note=(
                    "Submitted a successor community noise model for reapproval."
                    if initial_state == "pending_reapproval"
                    else "Submitted a community noise model for admin review."
                ),
                details={
                    "policy_version": POLICY_VERSION,
                    "approval_route": ADMIN_REVIEW_ROUTE,
                    "projected_state": initial_state,
                },
                payload_snapshot=submission_snapshot("noise_model", payload),
            )
            return NoiseModelSubmissionOutcome(noise_model, submission_event)
    except IntegrityError as error:
        raise TaxonomyConflictError(
            "The noise-model identity or lineage was claimed by another request."
        ) from error


@transaction.atomic
def approve_and_publish_noise_model(noise_model_id, *, reviewer: Account) -> NoiseModel:
    """Approve a pending community model without granting official status."""

    _require_admin(reviewer)
    noise_model = _locked_noise_model(noise_model_id)
    if noise_model.state not in PENDING_NOISE_MODEL_STATES:
        raise TaxonomyStateError("Only a pending noise model can be approved.")
    if noise_model.curation_status != NoiseModel.CurationStatus.COMMUNITY:
        raise TaxonomyStateError(
            "A submitted noise model must remain community-curated until publication."
        )
    if noise_model.supersedes_noise_model_id is not None:
        predecessor = NoiseModel.objects.select_for_update().get(
            id=noise_model.supersedes_noise_model_id
        )
        if predecessor.state not in PUBLIC_NOISE_MODEL_STATES:
            raise TaxonomyStateError(
                "The predecessor is no longer published or withdrawn history."
            )

    details = {
        "policy_version": POLICY_VERSION,
        "approval_route": ADMIN_REVIEW_ROUTE,
        "approved_by": str(reviewer.id),
        "approved_by_name": reviewer.display_name,
        "curation_status": NoiseModel.CurationStatus.COMMUNITY,
    }
    approval_event = append_history_event(
        kind="noise_model",
        record=noise_model,
        actor=reviewer,
        action=ModerationEvent.Action.APPROVED,
        note="Approved this community noise model after admin review.",
        details=details,
        caused_by=latest_snapshot_event("noise_model", noise_model),
    )
    publication_event = append_history_event(
        kind="noise_model",
        record=noise_model,
        actor=reviewer,
        action=ModerationEvent.Action.PUBLISHED,
        note="Published this approved community noise model.",
        details=details,
        caused_by=approval_event,
    )
    noise_model.state = "published"
    noise_model.published_at = publication_event.occurred_at
    noise_model.withdrawn_at = None
    noise_model.save(update_fields=["state", "published_at", "withdrawn_at"])
    return noise_model


@transaction.atomic
def promote_noise_model_official(noise_model_id, *, curator: Account) -> NoiseModel:
    """Grant official status to an already published community model."""

    _require_admin(curator)
    noise_model = _locked_noise_model(noise_model_id)
    if noise_model.state != "published":
        raise TaxonomyStateError("Only a published noise model can become official.")
    if noise_model.curation_status != NoiseModel.CurationStatus.COMMUNITY:
        raise TaxonomyStateError(
            "Only a community noise model can be promoted to official status."
        )
    noise_model.curation_status = NoiseModel.CurationStatus.OFFICIAL
    noise_model.save(update_fields=["curation_status"])
    append_history_event(
        kind="noise_model",
        record=noise_model,
        actor=curator,
        action=ModerationEvent.Action.PROMOTED_OFFICIAL,
        note="Promoted this published community noise model to official status.",
        details={
            "policy_version": POLICY_VERSION,
            "previous_status": NoiseModel.CurationStatus.COMMUNITY,
            "new_status": NoiseModel.CurationStatus.OFFICIAL,
        },
    )
    return noise_model


@transaction.atomic
def deprecate_noise_model(
    noise_model_id, *, curator: Account, note: str = ""
) -> NoiseModel:
    """Deprecate a published community or official noise model."""

    _require_admin(curator)
    noise_model = _locked_noise_model(noise_model_id)
    if noise_model.state != "published":
        raise TaxonomyStateError("Only a published noise model can be deprecated.")
    if noise_model.curation_status == NoiseModel.CurationStatus.DEPRECATED:
        raise TaxonomyStateError("This noise model is already deprecated.")
    previous_status = noise_model.curation_status
    noise_model.curation_status = NoiseModel.CurationStatus.DEPRECATED
    noise_model.save(update_fields=["curation_status"])
    append_history_event(
        kind="noise_model",
        record=noise_model,
        actor=curator,
        action=ModerationEvent.Action.DEPRECATED,
        note=note.strip() or "Deprecated this noise model.",
        details={
            "policy_version": POLICY_VERSION,
            "previous_status": previous_status,
            "new_status": NoiseModel.CurationStatus.DEPRECATED,
        },
    )
    return noise_model


def _frozen_schema_release(record_type: str) -> SchemaRelease:
    try:
        return SchemaRelease.objects.get(
            record_type=record_type,
            version="0.1",
            state=SchemaRelease.State.FROZEN,
        )
    except SchemaRelease.DoesNotExist as error:
        raise TaxonomyStateError(
            f"Frozen {record_type}/0.1 schema release is unavailable."
        ) from error


def _require_active(account: Account) -> None:
    if not account.is_active:
        raise TaxonomyPermissionError("Inactive accounts cannot submit records.")


def _require_admin(account: Account) -> None:
    if not account.is_active or not account.is_admin:
        raise TaxonomyPermissionError(
            "Only active administrators may curate taxonomy records."
        )


def _validate_tag_values(
    namespace: str, slug: str, label: str, description: str
) -> None:
    if namespace not in Tag.Namespace.values:
        raise TaxonomyValidationError("Select a valid tag namespace.")
    if not SLUG_PATTERN.fullmatch(slug) or len(slug) > 200:
        raise TaxonomyValidationError(
            "Use lowercase words separated by single hyphens for the tag slug."
        )
    if not label or len(label) > 200:
        raise TaxonomyValidationError("Provide a tag label of at most 200 characters.")
    if not description:
        raise TaxonomyValidationError("Provide a tag description.")


def _validate_noise_model_values(
    slug: str, name: str, short_description: str, paper_url: str
) -> None:
    if not SLUG_PATTERN.fullmatch(slug) or len(slug) > 200:
        raise TaxonomyValidationError(
            "Use lowercase words separated by single hyphens for the noise-model slug."
        )
    if not name or len(name) > 200:
        raise TaxonomyValidationError(
            "Provide a noise-model name of at most 200 characters."
        )
    if not short_description:
        raise TaxonomyValidationError("Provide a short description.")
    try:
        URLValidator()(paper_url)
    except ValidationError as error:
        raise TaxonomyValidationError("Provide a valid paper URL.") from error


def _locked_tag(tag_id) -> Tag:
    try:
        return Tag.objects.select_for_update().select_related("history").get(id=tag_id)
    except Tag.DoesNotExist as error:
        raise TaxonomyStateError("Tag not found.") from error


def _locked_noise_model(noise_model_id) -> NoiseModel:
    try:
        return (
            NoiseModel.objects.select_for_update()
            .select_related("history")
            .get(id=noise_model_id)
        )
    except NoiseModel.DoesNotExist as error:
        raise TaxonomyStateError("Noise model not found.") from error
