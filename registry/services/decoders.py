"""Read-only queries and lineage rules for public decoder pages."""

from django.db.models import Case, IntegerField, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Lower

from accounts.models import ExternalIdentity
from registry.models import (
    ArtifactAttachment,
    Credit,
    DecoderVersion,
    ExternalLink,
    Result,
    Tag,
)

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


def public_decoder_catalogue(
    *, query: str = "", tag_slug: str = ""
) -> QuerySet[DecoderVersion]:
    """Return published decoder versions matching the simple catalogue filters."""

    decoders = (
        DecoderVersion.objects.filter(state="published")
        .select_related("schema_release")
        .prefetch_related(
            Prefetch(
                "algorithm_tags",
                queryset=_ordered_algorithm_tags(),
                to_attr="display_algorithm_tags",
            )
        )
    )

    query = query.strip()
    if query:
        decoders = decoders.filter(
            Q(name__icontains=query)
            | Q(version__icontains=query)
            | Q(slug__icontains=query)
            | Q(algorithm_tags__label__icontains=query)
            | Q(algorithm_tags__slug__icontains=query)
        )

    tag_slug = tag_slug.strip()
    if tag_slug:
        decoders = decoders.filter(
            algorithm_tags__namespace="algorithm",
            algorithm_tags__slug=tag_slug,
        )

    return decoders.distinct().order_by(Lower("name"), "version", "id")


def catalogue_algorithm_tags() -> QuerySet[Tag]:
    """Return tags used by at least one published decoder, official first."""

    return (
        _ordered_algorithm_tags()
        .filter(decoder_versions__state="published")
        .distinct()
    )


def public_decoder_detail() -> QuerySet[DecoderVersion]:
    """Return the complete, bounded data graph needed by a decoder detail page."""

    visible_credits = (
        Credit.objects.filter(hidden_at__isnull=True)
        .select_related("account")
        .prefetch_related(
            Prefetch(
                "account__external_identities",
                queryset=ExternalIdentity.objects.order_by(
                    "provider", "public_identifier"
                ),
            )
        )
        .order_by("position")
    )
    published_results = (
        Result.objects.filter(state="published")
        .select_related("circuit_revision", "evaluator_version", "machine")
        .prefetch_related("scores__score_definition")
        .order_by("-published_at", "id")
    )

    return (
        DecoderVersion.objects.filter(state__in=PUBLIC_DETAIL_STATES)
        .select_related(
            "schema_release",
            "hyperparameter_schema_artifact",
            "submitted_by",
            "previous_version",
            "next_version",
        )
        .prefetch_related(
            Prefetch(
                "algorithm_tags",
                queryset=_ordered_algorithm_tags(),
                to_attr="display_algorithm_tags",
            ),
            Prefetch("credits", queryset=visible_credits, to_attr="visible_credits"),
            Prefetch(
                "results",
                queryset=published_results,
                to_attr="published_results",
            ),
            Prefetch(
                "external_links",
                queryset=ExternalLink.objects.order_by("position", "id"),
                to_attr="display_external_links",
            ),
            Prefetch(
                "artifact_attachments",
                queryset=ArtifactAttachment.objects.select_related("artifact").order_by(
                    "role", "position", "id"
                ),
                to_attr="display_artifact_attachments",
            ),
        )
    )


def inherited_description_source(decoder: DecoderVersion) -> DecoderVersion | None:
    """Find the nearest version at or before ``decoder`` with a description."""

    candidate: DecoderVersion | None = decoder
    visited: set[object] = set()
    while candidate is not None and candidate.pk not in visited:
        visited.add(candidate.pk)
        if candidate.description and candidate.description.strip():
            return candidate
        candidate = candidate.previous_version
    return None


def public_predecessor(decoder: DecoderVersion) -> DecoderVersion | None:
    predecessor = decoder.previous_version
    if predecessor is not None and predecessor.state in PUBLIC_DETAIL_STATES:
        return predecessor
    return None


def public_successor(decoder: DecoderVersion) -> DecoderVersion | None:
    try:
        successor = decoder.next_version
    except DecoderVersion.next_version.RelatedObjectDoesNotExist:
        return None
    if successor.state in PUBLIC_DETAIL_STATES:
        return successor
    return None


def _ordered_algorithm_tags() -> QuerySet[Tag]:
    return (
        Tag.objects.filter(namespace="algorithm")
        .annotate(
            official_order=Case(
                When(status="official", then=Value(0)),
                When(status="custom", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("official_order", Lower("label"), "id")
    )
