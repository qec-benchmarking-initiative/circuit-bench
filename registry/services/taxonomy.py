"""Transactional curation workflows for tags and noise models.

This module is intentionally independent of the generic submission adapter.  Tags
have a provisional, immediately usable vocabulary route, while noise models enter
the review queue without becoming publicly discoverable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Account
from registry.models import (
    EczTerm,
    NoiseModel,
    RecordEvent,
    SchemaRelease,
    Tag,
    TagAlias,
    TagParent,
)
from registry.models.common import RecordVisibility
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
TAG_GRAPH_ADVISORY_LOCK_ID = 0x434252544147


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
    submission_event: RecordEvent
    approval_event: RecordEvent
    publication_event: RecordEvent


@dataclass(frozen=True)
class NoiseModelSubmissionOutcome:
    noise_model: NoiseModel
    submission_event: RecordEvent


def create_custom_tag(
    *,
    submitter: Account,
    namespace: str,
    slug: str | None = None,
    label: str,
    description: str,
    aliases: Iterable[str] = (),
    parents: Iterable[Tag | str] = (),
    ecz_parents: Iterable[str] = (),
    visibility: str = "public",
) -> TagCreationOutcome:
    """Create an immediately usable custom tag with an explicit system route."""

    _require_active(submitter)
    namespace = namespace.strip()
    label = label.strip()
    description = description.strip()
    aliases = normalise_tag_aliases(aliases)
    parent_ids = normalise_tag_parent_ids(parents)
    ecz_parents = tuple(ecz_parents)
    slug = slug.strip() if slug is not None else ""
    if not slug:
        slug = _available_tag_slug(namespace, label)
    _validate_tag_values(namespace, slug, label, description)
    if visibility not in RecordVisibility.values:
        raise TaxonomyValidationError("Visibility must be public or private.")
    _validate_alias_values(label, aliases)

    try:
        with transaction.atomic():
            graph_edges = _lock_tag_taxonomy_graph()
            parent_tags = _locked_parent_tags(parent_ids, namespace=namespace)
            if Tag.objects.filter(namespace=namespace, slug=slug).exists():
                raise TaxonomyConflictError(
                    "That tag identity is already present as a tag name or alias."
                )
            _require_available_tag_terms(
                namespace=namespace,
                label=label,
                aliases=aliases,
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
                visibility=visibility,
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
                action=RecordEvent.Action.SUBMITTED,
                note="Submitted a custom vocabulary term.",
                details=details,
                payload_snapshot=submission_snapshot(
                    "tag",
                    {
                        "namespace": namespace,
                        "slug": slug,
                        "label": label,
                        "description": description,
                        "visibility": visibility,
                        "aliases": list(aliases),
                        "parent_tag_ids": [str(parent_id) for parent_id in parent_ids],
                        "ecz_parent_ids": [str(parent_id) for parent_id in ecz_parents],
                        "status": Tag.Status.CUSTOM,
                    },
                ),
            )
            for alias in aliases:
                _add_tag_alias_locked(tag, actor=submitter, alias=alias)
            proposed_edges = graph_edges | {
                (tag.id, parent_id) for parent_id in parent_ids
            }
            _assert_tag_taxonomy_acyclic(proposed_edges)
            TagParent.objects.bulk_create(
                TagParent(child=tag, parent=parent_tags[parent_id])
                for parent_id in parent_ids
            )
            if ecz_parents:
                from registry.services.ecz_taxonomy import (
                    EczTaxonomyError,
                    set_tag_ecz_parents,
                )

                try:
                    set_tag_ecz_parents(
                        tag.id,
                        actor=submitter,
                        ecz_terms=ecz_parents,
                    )
                except EczTaxonomyError as error:
                    raise TaxonomyValidationError(str(error)) from error
            approval_event = append_history_event(
                kind="tag",
                record=tag,
                actor_system=CUSTOM_VOCABULARY_SYSTEM,
                action=RecordEvent.Action.APPROVED,
                note="Approved provisionally for immediate custom-vocabulary use.",
                details={**details, "approved_by": "system"},
                caused_by=submission_event,
            )
            publication_event = append_history_event(
                kind="tag",
                record=tag,
                actor_system=CUSTOM_VOCABULARY_SYSTEM,
                action=RecordEvent.Action.PUBLISHED,
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


def normalise_tag_aliases(values: Iterable[str] | str) -> tuple[str, ...]:
    """Return ordered, case-insensitively unique alias text."""

    if isinstance(values, str):
        values = re.split(r"[\n,]", values)
    aliases: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = " ".join(str(raw_value).split())
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            aliases.append(value)
            seen.add(key)
    return tuple(aliases)


def normalise_tag_parent_ids(
    values: Iterable[Tag | str] | Tag | str | None,
) -> tuple:
    """Return ordered, unique Tag primary keys from form or service values."""

    if values is None:
        return ()
    if isinstance(values, (Tag, str)):
        values = (values,)
    parent_ids = []
    seen = set()
    for value in values:
        raw_id = value.id if isinstance(value, Tag) else value
        try:
            parent_id = Tag._meta.pk.to_python(raw_id)
        except (TypeError, ValueError, ValidationError) as error:
            raise TaxonomyValidationError(
                "A selected parent tag is invalid."
            ) from error
        if parent_id not in seen:
            parent_ids.append(parent_id)
            seen.add(parent_id)
    return tuple(parent_ids)


def can_edit_tag(tag: Tag, actor: Account | None) -> bool:
    if actor is None or not actor.is_active:
        return False
    if tag.status == Tag.Status.RETIRED:
        return False
    if actor.is_admin:
        return True
    return tag.status == Tag.Status.CUSTOM and tag.submitted_by_id == actor.id


def can_retire_tag(tag: Tag, actor: Account | None) -> bool:
    """Return whether an account may perform the user-facing delete action."""

    if actor is None or not actor.is_active:
        return False
    if tag.status == Tag.Status.CUSTOM:
        return tag.submitted_by_id == actor.id
    if tag.status == Tag.Status.OFFICIAL:
        return actor.is_admin
    return False


@transaction.atomic
def update_tag(
    tag_id,
    *,
    actor: Account,
    label: str,
    description: str,
    aliases: Iterable[str] | str,
    parents: Iterable[Tag | str] | Tag | str | None = None,
    ecz_parents: Iterable[str] | None = None,
) -> Tag:
    """Edit tag prose and reconcile its durable alias rows."""

    parent_ids = normalise_tag_parent_ids(parents) if parents is not None else None
    ecz_parents = tuple(ecz_parents) if ecz_parents is not None else None
    graph_edges = _lock_tag_taxonomy_graph() if parent_ids is not None else None
    tag = _locked_tag(tag_id)
    if not can_edit_tag(tag, actor):
        raise TaxonomyPermissionError("You cannot edit this tag.")
    label = " ".join(label.split())
    description = description.strip()
    aliases = normalise_tag_aliases(aliases)
    _validate_tag_values(tag.namespace, tag.slug, label, description)
    _validate_alias_values(label, aliases)
    _require_available_tag_terms(
        namespace=tag.namespace,
        label=label,
        aliases=aliases,
        exclude_tag=tag,
    )

    active_aliases = list(
        TagAlias.objects.select_for_update()
        .filter(tag=tag, is_active=True)
        .order_by("added_at", "id")
    )
    existing_by_key = {item.alias.casefold(): item for item in active_aliases}
    desired_by_key = {item.casefold(): item for item in aliases}
    aliases_changed = False
    for key, alias_record in existing_by_key.items():
        if key not in desired_by_key:
            _remove_tag_alias_locked(alias_record, actor=actor)
            aliases_changed = True

    parents_changed = False
    ecz_parents_changed = False
    if parent_ids is not None:
        parent_tags = _locked_parent_tags(parent_ids, namespace=tag.namespace)
        existing_parent_ids = {
            parent_id
            for parent_id in TagParent.objects.filter(child=tag).values_list(
                "parent_id", flat=True
            )
        }
        desired_parent_ids = set(parent_ids)
        proposed_edges = {edge for edge in graph_edges if edge[0] != tag.id} | {
            (tag.id, parent_id) for parent_id in desired_parent_ids
        }
        _assert_tag_taxonomy_acyclic(proposed_edges)
        removed_parent_ids = existing_parent_ids - desired_parent_ids
        added_parent_ids = desired_parent_ids - existing_parent_ids
        if removed_parent_ids:
            TagParent.objects.filter(
                child=tag, parent_id__in=removed_parent_ids
            ).delete()
        if added_parent_ids:
            TagParent.objects.bulk_create(
                TagParent(child=tag, parent=parent_tags[parent_id])
                for parent_id in added_parent_ids
            )
        parents_changed = bool(removed_parent_ids or added_parent_ids)
    if ecz_parents is not None:
        if tag.namespace != Tag.Namespace.CODE:
            if ecz_parents:
                raise TaxonomyValidationError(
                    "Only code tags can have Error Correction Zoo parents."
                )
            ecz_parents = None
    if ecz_parents is not None:
        from registry.services.ecz_taxonomy import (
            EczTaxonomyError,
            set_tag_ecz_parents,
        )

        existing_ecz_parent_ids = set(tag.ecz_parents.values_list("id", flat=True))
        requested_ecz_parent_ids = {
            item.id if isinstance(item, EczTerm) else EczTerm._meta.pk.to_python(item)
            for item in ecz_parents
        }
        ecz_parents_changed = existing_ecz_parent_ids != requested_ecz_parent_ids
        try:
            set_tag_ecz_parents(
                tag.id,
                actor=actor,
                ecz_terms=ecz_parents,
            )
        except EczTaxonomyError as error:
            raise TaxonomyValidationError(str(error)) from error
    for key, alias in desired_by_key.items():
        if key not in existing_by_key:
            _add_tag_alias_locked(tag, actor=actor, alias=alias)
            aliases_changed = True

    changed_fields = []
    if tag.label != label:
        tag.label = label
        changed_fields.append("label")
    if tag.description != description:
        tag.description = description
        changed_fields.append("description")
    if parents_changed:
        changed_fields.append("parents")
    if ecz_parents_changed:
        changed_fields.append("ecz_parents")
    if changed_fields:
        concrete_changed_fields = [
            field for field in changed_fields if field in {"label", "description"}
        ]
        tag.save(update_fields=[*concrete_changed_fields, "updated_at"])
        append_history_event(
            kind="tag",
            record=tag,
            actor=actor,
            action=RecordEvent.Action.EDITED,
            note="Updated this tag.",
            details={
                "policy_version": POLICY_VERSION,
                "changed_fields": changed_fields,
            },
            payload_snapshot=submission_snapshot(
                "tag",
                {
                    "namespace": tag.namespace,
                    "slug": tag.slug,
                    "label": tag.label,
                    "description": tag.description,
                    "aliases": list(aliases),
                    "parent_tag_ids": [
                        str(parent_id)
                        for parent_id in (
                            parent_ids
                            if parent_ids is not None
                            else tag.parents.values_list("id", flat=True)
                        )
                    ],
                    "ecz_parent_ids": [
                        str(term_id)
                        for term_id in tag.ecz_parents.values_list("id", flat=True)
                    ],
                    "status": tag.status,
                },
            ),
        )
    elif aliases_changed:
        tag.save(update_fields=["updated_at"])
    return tag


@transaction.atomic
def retire_tag(tag_id, *, actor: Account) -> Tag:
    """Retire a tag while preserving its identity and every existing reference."""

    tag = _locked_tag(tag_id)
    if not can_retire_tag(tag, actor):
        raise TaxonomyPermissionError("You cannot delete this tag.")
    previous_status = tag.status
    tag.status = Tag.Status.RETIRED
    tag.save(update_fields=["status", "updated_at"])
    append_history_event(
        kind="tag",
        record=tag,
        actor=actor,
        action=RecordEvent.Action.RETIRED,
        note="Deleted this tag from active use.",
        details={
            "policy_version": POLICY_VERSION,
            "previous_status": previous_status,
            "new_status": Tag.Status.RETIRED,
            "public_action": "deleted",
        },
    )
    return tag


@transaction.atomic
def add_tag_alias(tag_id, *, actor: Account, alias: str) -> TagAlias:
    tag = _locked_tag(tag_id)
    if not can_edit_tag(tag, actor):
        raise TaxonomyPermissionError("You cannot edit this tag.")
    alias_values = normalise_tag_aliases((alias,))
    if not alias_values:
        raise TaxonomyValidationError("Provide an alias.")
    _validate_alias_values(tag.label, alias_values)
    _require_available_tag_terms(
        namespace=tag.namespace,
        label=tag.label,
        aliases=alias_values,
        exclude_tag=tag,
    )
    alias_record = _add_tag_alias_locked(tag, actor=actor, alias=alias_values[0])
    tag.save(update_fields=["updated_at"])
    return alias_record


@transaction.atomic
def remove_tag_alias(alias_id, *, actor: Account) -> TagAlias:
    try:
        alias_record = (
            TagAlias.objects.select_for_update()
            .select_related("tag", "tag__history")
            .get(id=alias_id)
        )
    except TagAlias.DoesNotExist as error:
        raise TaxonomyStateError("Tag alias not found.") from error
    if not can_edit_tag(alias_record.tag, actor):
        raise TaxonomyPermissionError("You cannot edit this tag.")
    if not alias_record.is_active:
        raise TaxonomyStateError("That alias is already inactive.")
    alias_record = _remove_tag_alias_locked(alias_record, actor=actor)
    alias_record.tag.save(update_fields=["updated_at"])
    return alias_record


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
        action=RecordEvent.Action.PROMOTED_OFFICIAL,
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
    if tag.status in (Tag.Status.DEPRECATED, Tag.Status.RETIRED):
        raise TaxonomyStateError("This tag is not active.")
    if canonical.namespace != tag.namespace:
        raise TaxonomyValidationError(
            "The canonical replacement must use the same namespace."
        )
    if canonical.status in (Tag.Status.DEPRECATED, Tag.Status.RETIRED) or (
        canonical.canonical_tag_id
    ):
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
        action=RecordEvent.Action.DEPRECATED,
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
        action=RecordEvent.Action.MERGED,
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
    visibility: str = "public",
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
                if NoiseModel.objects.filter(predecessor=locked_predecessor).exists():
                    raise TaxonomyConflictError(
                        "That noise model already has a successor."
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
                predecessor=locked_predecessor,
                curation_status=NoiseModel.CurationStatus.COMMUNITY,
                submitted_by=submitter,
                state=initial_state,
                visibility=visibility,
                published_at=None,
                withdrawn_at=None,
            )
            if locked_predecessor is not None:
                append_history_event(
                    kind="noise_model",
                    record=noise_model,
                    actor=submitter,
                    action=RecordEvent.Action.REVISION_CREATED,
                    note="Created a successor noise-model revision.",
                    details={
                        "policy_version": POLICY_VERSION,
                        "predecessor_id": str(locked_predecessor.id),
                    },
                )
            payload = {
                "visibility": visibility,
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
                    RecordEvent.Action.RESUBMITTED
                    if initial_state == "pending_reapproval"
                    else RecordEvent.Action.SUBMITTED
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
    if noise_model.predecessor_id is not None:
        predecessor = NoiseModel.objects.select_for_update().get(
            id=noise_model.predecessor_id
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
        action=RecordEvent.Action.APPROVED,
        note="Approved this community noise model after admin review.",
        details=details,
        caused_by=latest_snapshot_event("noise_model", noise_model),
    )
    publication_event = append_history_event(
        kind="noise_model",
        record=noise_model,
        actor=reviewer,
        action=RecordEvent.Action.PUBLISHED,
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
        action=RecordEvent.Action.PROMOTED_OFFICIAL,
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
        action=RecordEvent.Action.DEPRECATED,
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


def _validate_alias_values(label: str, aliases: tuple[str, ...]) -> None:
    label_key = label.casefold()
    for alias in aliases:
        if len(alias) > 200:
            raise TaxonomyValidationError(
                "Each tag alias must be at most 200 characters."
            )
        if alias.casefold() == label_key:
            raise TaxonomyValidationError(
                "An alias must differ from the tag's displayed label."
            )


def _require_available_tag_terms(
    *,
    namespace: str,
    label: str,
    aliases: tuple[str, ...],
    exclude_tag: Tag | None = None,
) -> None:
    """Reject terms that would make a namespace picker ambiguous."""

    candidate_terms = (label, *aliases)
    tags = Tag.objects.filter(namespace=namespace)
    namespace_aliases = TagAlias.objects.filter(
        tag__namespace=namespace,
        is_active=True,
    )
    global_aliases = TagAlias.objects.filter(is_active=True)
    if exclude_tag is not None:
        tags = tags.exclude(id=exclude_tag.id)
        namespace_aliases = namespace_aliases.exclude(tag=exclude_tag)
        global_aliases = global_aliases.exclude(tag=exclude_tag)
    for term in candidate_terms:
        if tags.filter(label__iexact=term).exists():
            raise TaxonomyConflictError(
                f"An existing {namespace} tag already uses “{term}”."
            )
        if namespace_aliases.filter(alias__iexact=term).exists():
            raise TaxonomyConflictError(
                f"An existing {namespace} tag already uses “{term}” as an alias."
            )
    for alias in aliases:
        if global_aliases.filter(alias__iexact=alias).exists():
            raise TaxonomyConflictError(
                f"Another tag already uses “{alias}” as an active alias."
            )


def _available_tag_slug(namespace: str, label: str) -> str:
    base = slugify(label)[:200].strip("-") or "tag"
    candidate = base
    suffix = 2
    while Tag.objects.filter(namespace=namespace, slug=candidate).exists():
        ending = f"-{suffix}"
        candidate = f"{base[: 200 - len(ending)].rstrip('-')}{ending}"
        suffix += 1
    return candidate


def _add_tag_alias_locked(tag: Tag, *, actor: Account, alias: str) -> TagAlias:
    alias_record = TagAlias.objects.create(
        tag=tag,
        alias=alias,
        is_active=True,
        added_by=actor,
        removed_by=None,
        removed_at=None,
    )
    append_history_event(
        kind="tag",
        record=tag,
        actor=actor,
        action=RecordEvent.Action.ADDED_ALIAS,
        note=f"Added the alias “{alias}”.",
        details={
            "policy_version": POLICY_VERSION,
            "alias_id": str(alias_record.id),
            "alias": alias,
        },
    )
    return alias_record


def _remove_tag_alias_locked(
    alias_record: TagAlias,
    *,
    actor: Account,
) -> TagAlias:
    alias_record.is_active = False
    alias_record.removed_by = actor
    alias_record.removed_at = timezone.now()
    alias_record.save(update_fields=["is_active", "removed_by", "removed_at"])
    append_history_event(
        kind="tag",
        record=alias_record.tag,
        actor=actor,
        action=RecordEvent.Action.REMOVED_ALIAS,
        note=f"Removed the alias “{alias_record.alias}”.",
        details={
            "policy_version": POLICY_VERSION,
            "alias_id": str(alias_record.id),
            "alias": alias_record.alias,
        },
    )
    return alias_record


def _lock_tag_taxonomy_graph() -> set[tuple]:
    """Serialize hierarchy writers and return the locked directed edge set."""

    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                [TAG_GRAPH_ADVISORY_LOCK_ID],
            )
    return set(
        TagParent.objects.select_for_update().values_list("child_id", "parent_id")
    )


def _locked_parent_tags(parent_ids: tuple, *, namespace: str) -> dict:
    if not parent_ids:
        return {}
    records = {
        tag.id: tag
        for tag in Tag.objects.select_for_update()
        .filter(id__in=parent_ids)
        .order_by("id")
    }
    if set(records) != set(parent_ids):
        raise TaxonomyValidationError("A selected parent tag does not exist.")
    if any(tag.namespace != namespace for tag in records.values()):
        raise TaxonomyValidationError(
            "A parent tag must use the same tag type as its child."
        )
    return records


def _assert_tag_taxonomy_acyclic(edges: set[tuple]) -> None:
    """Reject any directed cycle, including a tag selected as its own parent."""

    adjacency: dict[object, set] = {}
    nodes = set()
    for child_id, parent_id in edges:
        adjacency.setdefault(child_id, set()).add(parent_id)
        nodes.update((child_id, parent_id))

    state = {}

    def visit(node) -> None:
        if state.get(node) == "active":
            raise TaxonomyValidationError(
                "That parent selection would create a cycle in the tag taxonomy."
            )
        if state.get(node) == "complete":
            return
        state[node] = "active"
        for parent_id in adjacency.get(node, ()):
            visit(parent_id)
        state[node] = "complete"

    for node in nodes:
        visit(node)


def validate_tag_taxonomy_acyclic() -> None:
    """Validate the persisted hierarchy, including out-of-band database writes."""

    _assert_tag_taxonomy_acyclic(
        set(TagParent.objects.values_list("child_id", "parent_id"))
    )


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
