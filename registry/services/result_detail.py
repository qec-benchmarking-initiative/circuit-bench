"""Bounded read model for an exact public benchmark result."""

from django.db.models import Prefetch, Q, QuerySet

from registry.models import ArtifactAttachment, ExternalLink, Result, ResultScore

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


def public_result_detail() -> QuerySet[Result]:
    """Return the complete, immutable graph used by the public result page.

    Catalogue pages expose published rows only.  An exact URL may continue to
    resolve a withdrawn row so citations do not silently break, matching the
    existing decoder, circuit, noise-model, and machine detail policy.  Draft
    and pending-review records, including records with non-public provenance,
    remain outside this read model.
    """

    scores = ResultScore.objects.select_related(
        "score_definition",
        "score_definition__evaluator_release",
    ).order_by(
        "score_definition__display_order",
        "score_definition__key",
    )
    attachments = ArtifactAttachment.objects.select_related("artifact").order_by(
        "role",
        "position",
        "id",
    )
    external_links = ExternalLink.objects.order_by("position", "id")

    return (
        Result.objects.filter(
            state__in=PUBLIC_DETAIL_STATES,
            decoder_version__state__in=PUBLIC_DETAIL_STATES,
            circuit_revision__state__in=PUBLIC_DETAIL_STATES,
            evaluator_version__state__in=PUBLIC_DETAIL_STATES,
        )
        .filter(Q(machine__isnull=True) | Q(machine__state__in=PUBLIC_DETAIL_STATES))
        .select_related(
            "schema_release",
            "decoder_version",
            "circuit_revision",
            "circuit_revision__noise_model",
            "evaluator_version",
            "evaluator_version__source_bundle_artifact",
            "machine",
            "hyperparameter_values_artifact",
            "predecessor",
            "submitted_by",
        )
        .prefetch_related(
            Prefetch("scores", queryset=scores, to_attr="display_scores"),
            Prefetch(
                "artifact_attachments",
                queryset=attachments,
                to_attr="display_artifact_attachments",
            ),
            Prefetch(
                "external_links",
                queryset=external_links,
                to_attr="display_external_links",
            ),
        )
    )
