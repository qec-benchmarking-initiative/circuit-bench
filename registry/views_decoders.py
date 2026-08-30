from urllib.parse import urlencode

from django.urls import NoReverseMatch, reverse
from django.views.generic import DetailView, ListView

from registry.models import DecoderVersion
from registry.services.decoders import (
    catalogue_algorithm_tags,
    inherited_description_source,
    public_decoder_catalogue,
    public_decoder_detail,
    public_predecessor,
    public_successor,
)


class DecoderCatalogueView(ListView):
    context_object_name = "decoders"
    template_name = "decoders/catalogue.html"

    def get_queryset(self):
        self.query = self.request.GET.get("q", "").strip()
        self.tag_slug = self.request.GET.get("tag", "").strip()
        return public_decoder_catalogue(query=self.query, tag_slug=self.tag_slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "query": self.query,
                "selected_tag": self.tag_slug,
                "filter_tags": catalogue_algorithm_tags(),
                "result_count": len(context["decoders"]),
            }
        )
        return context


class DecoderDetailView(DetailView):
    context_object_name = "decoder"
    model = DecoderVersion
    slug_field = "slug"
    slug_url_kwarg = "slug"
    template_name = "decoders/detail.html"

    def get_queryset(self):
        return public_decoder_detail()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        decoder = self.object
        description_source = inherited_description_source(decoder)
        predecessor = public_predecessor(decoder)
        successor = public_successor(decoder)
        list_url = reverse("decoders:list")

        context.update(
            {
                "entity": {
                    "kind": "Decoder version",
                    "name": decoder.name,
                    "version": decoder.version,
                    "status": decoder.state,
                    "status_label": decoder.get_state_display(),
                    "tags": [
                        {
                            "label": tag.label,
                            "status": tag.status,
                            "url": f"{list_url}?{urlencode({'tag': tag.slug})}",
                        }
                        for tag in decoder.display_algorithm_tags
                    ],
                },
                "description_source": description_source,
                "description_source_url": self._decoder_url(description_source),
                "predecessor": predecessor,
                "predecessor_url": self._decoder_url(predecessor),
                "successor": successor,
                "successor_url": self._decoder_url(successor),
                "metadata": self._metadata(decoder),
                "capabilities": self._capabilities(decoder),
                "schema_download_url": self._schema_download_url(decoder),
                "result_columns": [
                    {"label": "Result"},
                    {"label": "Circuit"},
                    {"label": "Shots", "numeric": True},
                    {"label": "Evaluator scores"},
                    {"label": "Reproduction"},
                    {"label": "Published"},
                ],
                "result_rows": self._result_rows(decoder),
            }
        )
        return context

    @staticmethod
    def _decoder_url(decoder: DecoderVersion | None) -> str | None:
        if decoder is None:
            return None
        return reverse("decoders:detail", kwargs={"slug": decoder.slug})

    @staticmethod
    def _schema_download_url(decoder: DecoderVersion) -> str | None:
        artifact = decoder.hyperparameter_schema_artifact
        if artifact is None:
            return None
        try:
            return reverse("artifacts:download", kwargs={"artifact_id": artifact.id})
        except NoReverseMatch:
            return None

    @staticmethod
    def _metadata(decoder: DecoderVersion) -> list[dict[str, object]]:
        return [
            {"label": "Version label", "value": decoder.version},
            {"label": "Stable slug", "value": decoder.slug},
            {"label": "Version UUID", "value": decoder.id},
            {"label": "Schema", "value": decoder.schema_release.public_name},
            {"label": "Submitted by", "value": decoder.submitted_by.display_name},
            {"label": "Created", "value": decoder.created_at},
            {"label": "Published", "value": decoder.published_at},
        ]

    @staticmethod
    def _capabilities(decoder: DecoderVersion) -> list[dict[str, str]]:
        strict_not_required = "Not required (<10 s on first uncached exposure)"
        return [
            {
                "label": "Circuit-skeleton preparation",
                "value": (
                    strict_not_required
                    if decoder.circuit_skeleton_preparation == "not_required"
                    else "Required"
                ),
            },
            {
                "label": "Circuit-prior preparation",
                "value": (
                    strict_not_required
                    if decoder.circuit_priors_preparation == "not_required"
                    else "Required"
                ),
            },
            {
                "label": "Soft output",
                "value": (
                    "Provides per-shot failure probability q in [0, 1]"
                    if decoder.provides_failure_probability
                    else "Does not provide a per-shot failure probability"
                ),
            },
        ]

    @staticmethod
    def _result_rows(decoder: DecoderVersion) -> list[dict[str, object]]:
        rows = []
        for result in decoder.published_results:
            scores = "; ".join(
                (
                    f"{score.score_definition.name}: {score.value} "
                    f"{score.score_definition.unit}"
                ).rstrip()
                for score in sorted(
                    result.scores.all(),
                    key=lambda score: score.score_definition.display_order,
                )
            )
            rows.append(
                {
                    "cells": [
                        {"value": str(result.id)},
                        {"value": result.circuit_revision.name},
                        {"value": result.shots_total, "numeric": True},
                        {"value": scores},
                        {"value": result.get_reproduction_status_display()},
                        {"value": result.published_at},
                    ]
                }
            )
        return rows
