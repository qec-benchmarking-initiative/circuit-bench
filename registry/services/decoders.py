"""Read-only queries and lineage rules for public decoder pages."""

from django.db.models import (
    Case,
    Count,
    IntegerField,
    Prefetch,
    Q,
    QuerySet,
    Value,
    When,
)
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
from registry.services.tag_hierarchy import descendant_slug_groups
from registry.services.tags import active_tag_queryset
from registry.services.visibility import actor_visibility_q

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


def public_decoder_catalogue(
    *,
    query: str = "",
    tag_slug: str = "",
    tag_slugs: tuple[str, ...] = (),
    tag_match: str = "all",
    skeleton_preparation: str = "",
    priors_preparation: str = "",
    probability_output: str = "",
    result_min: int | None = None,
    result_max: int | None = None,
) -> QuerySet[DecoderVersion]:
    """Return published decoder versions matching the simple catalogue filters."""

    decoders = (
        DecoderVersion.objects.filter(state="published", visibility="public")
        .annotate(
            published_result_count=Count(
                "results",
                filter=Q(results__state="published", results__visibility="public"),
                distinct=True,
            )
        )
        .select_related("schema_release")
        .prefetch_related(
            Prefetch(
                "algorithm_tags",
                queryset=_ordered_algorithm_tags().filter(visibility="public"),
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
            | Q(
                algorithm_tags__aliases__alias__icontains=query,
                algorithm_tags__aliases__is_active=True,
            )
        )

    selected_tags = tuple(tag for tag in tag_slugs if tag)
    if tag_slug.strip() and tag_slug.strip() not in selected_tags:
        selected_tags = (*selected_tags, tag_slug.strip())
    if tag_match == "children" and selected_tags:
        tag_groups = descendant_slug_groups(Tag.Namespace.ALGORITHM, selected_tags)
        decoders = decoders.filter(
            algorithm_tags__namespace="algorithm",
            algorithm_tags__slug__in={slug for group in tag_groups for slug in group},
        )
    elif tag_match == "any" and selected_tags:
        decoders = decoders.filter(
            algorithm_tags__namespace="algorithm",
            algorithm_tags__slug__in=selected_tags,
        )
    else:
        for tag_slug_value in selected_tags:
            decoders = decoders.filter(
                algorithm_tags__namespace="algorithm",
                algorithm_tags__slug=tag_slug_value,
            )

    if skeleton_preparation in {"required", "not_required"}:
        decoders = decoders.filter(circuit_skeleton_preparation=skeleton_preparation)
    if priors_preparation in {"required", "not_required"}:
        decoders = decoders.filter(circuit_priors_preparation=priors_preparation)
    if probability_output in {"yes", "no"}:
        decoders = decoders.filter(
            provides_failure_probability=probability_output == "yes"
        )
    if result_min is not None:
        decoders = decoders.filter(published_result_count__gte=result_min)
    if result_max is not None:
        decoders = decoders.filter(published_result_count__lte=result_max)

    return decoders.distinct()


def catalogue_algorithm_tags() -> QuerySet[Tag]:
    """Return tags used by at least one published decoder, official first."""

    return (
        active_tag_queryset(Tag.Namespace.ALGORITHM)
        .filter(Q(status=Tag.Status.OFFICIAL) | Q(decoder_versions__state="published"))
        .distinct()
    )


def public_decoder_detail(viewer=None) -> QuerySet[DecoderVersion]:
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
        Result.objects.filter(
            state="published",
            visibility="public",
            circuit_revision__visibility="public",
            circuit_revision__noise_model__visibility="public",
            evaluator_version__visibility="public",
        )
        .filter(Q(machine__isnull=True) | Q(machine__visibility="public"))
        .select_related("circuit_revision", "evaluator_version", "machine")
        .prefetch_related("scores__score_definition")
        .order_by("-published_at", "id")
    )

    return (
        DecoderVersion.objects.filter(state__in=PUBLIC_DETAIL_STATES)
        .filter(actor_visibility_q(viewer))
        .select_related(
            "schema_release",
            "hyperparameter_schema_artifact",
            "submitted_by",
            "predecessor",
            "successor",
        )
        .prefetch_related(
            Prefetch(
                "algorithm_tags",
                queryset=_ordered_algorithm_tags().filter(actor_visibility_q(viewer)),
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
        candidate = candidate.predecessor
    return None


def public_predecessor(decoder: DecoderVersion) -> DecoderVersion | None:
    predecessor = decoder.predecessor
    if predecessor is not None and predecessor.state in PUBLIC_DETAIL_STATES:
        return predecessor
    return None


def public_successor(decoder: DecoderVersion) -> DecoderVersion | None:
    try:
        successor = decoder.successor
    except DecoderVersion.successor.RelatedObjectDoesNotExist:
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
