from urllib.parse import urlencode

from django.urls import NoReverseMatch, reverse
from django.views.generic import DetailView, ListView

from registry.explorer import (
    ColumnSpec,
    apply_sort,
    cells_for_visible_columns,
    parse_nonnegative_int,
    parse_sort,
    table_context,
    url_without,
)
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

    columns = (
        ColumnSpec("name", "Decoder", help_text="Published decoder name"),
        ColumnSpec("version", "Version"),
        ColumnSpec("skeleton", "Skeleton preparation"),
        ColumnSpec("priors", "Prior preparation"),
        ColumnSpec("probability", "Failure probability"),
        ColumnSpec("tags", "Algorithm tags", sortable=False),
        ColumnSpec("results", "Results", numeric=True, default_direction="desc"),
        ColumnSpec("published", "Published", default_direction="desc"),
    )
    sort_fields = {
        "name": "name",
        "version": "version",
        "skeleton": "circuit_skeleton_preparation",
        "priors": "circuit_priors_preparation",
        "probability": "provides_failure_probability",
        "results": "published_result_count",
        "published": "published_at",
    }

    def get_queryset(self):
        self.query = self.request.GET.get("q", "").strip()
        self.tag_slugs = tuple(
            dict.fromkeys(
                tag.strip() for tag in self.request.GET.getlist("tag") if tag.strip()
            )
        )
        self.tag_match = self.request.GET.get("tag_match", "all").strip()
        if self.tag_match not in {"all", "any"}:
            self.tag_match = "all"
        self.skeleton_preparation = self.request.GET.get("skeleton", "").strip()
        self.priors_preparation = self.request.GET.get("priors", "").strip()
        self.probability_output = self.request.GET.get("probability", "").strip()
        self.result_min = parse_nonnegative_int(self.request.GET.get("result_min", ""))
        self.result_max = parse_nonnegative_int(self.request.GET.get("result_max", ""))
        self.sort_keys = parse_sort(
            self.request.GET.get("sort", ""), self.columns, (("name", "asc"),)
        )
        queryset = public_decoder_catalogue(
            query=self.query,
            tag_slugs=self.tag_slugs,
            tag_match=self.tag_match,
            skeleton_preparation=self.skeleton_preparation,
            priors_preparation=self.priors_preparation,
            probability_output=self.probability_output,
            result_min=self.result_min,
            result_max=self.result_max,
        )
        return apply_sort(queryset, self.sort_keys, self.sort_fields)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        table = table_context(self.request, self.columns, self.sort_keys)
        rows = []
        for decoder in context["decoders"]:
            tag_cells = [
                {
                    "label": tag.label,
                    "url": f"{reverse('decoders:list')}?{urlencode({'tag': tag.slug})}",
                    "display_color": tag.display_color,
                }
                for tag in decoder.display_algorithm_tags
            ]
            cell_by_key = {
                "name": {
                    "key": "name",
                    "value": decoder.name,
                    "url": reverse("decoders:detail", kwargs={"slug": decoder.slug}),
                },
                "version": {"key": "version", "value": decoder.version},
                "skeleton": {
                    "key": "skeleton",
                    "value": decoder.get_circuit_skeleton_preparation_display(),
                },
                "priors": {
                    "key": "priors",
                    "value": decoder.get_circuit_priors_preparation_display(),
                },
                "probability": {
                    "key": "probability",
                    "value": "Yes" if decoder.provides_failure_probability else "No",
                },
                "tags": {"key": "tags", "tags": tag_cells},
                "results": {
                    "key": "results",
                    "value": decoder.published_result_count,
                    "numeric": True,
                },
                "published": {"key": "published", "value": decoder.published_at},
            }
            rows.append(
                {
                    "cells": cells_for_visible_columns(
                        table["visible_column_keys"], cell_by_key
                    )
                }
            )

        context.update(table)
        context.update(
            {
                "query": self.query,
                "selected_tags": self.tag_slugs,
                "selected_tag": self.tag_slugs[0] if len(self.tag_slugs) == 1 else "",
                "tag_match": self.tag_match,
                "selected_skeleton": self.skeleton_preparation,
                "selected_priors": self.priors_preparation,
                "selected_probability": self.probability_output,
                "result_min": self.request.GET.get("result_min", ""),
                "result_max": self.request.GET.get("result_max", ""),
                "filter_tags": catalogue_algorithm_tags(),
                "result_count": len(context["decoders"]),
                "table_rows": rows,
                "reset_sort_url": url_without(self.request, "sort"),
                "raw_sort": self.request.GET.get("sort", ""),
                "raw_columns": self.request.GET.get("columns", ""),
                "filters_active": any(
                    (
                        self.query,
                        self.tag_slugs,
                        self.skeleton_preparation,
                        self.priors_preparation,
                        self.probability_output,
                        self.result_min is not None,
                        self.result_max is not None,
                    )
                ),
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
                            "display_color": tag.display_color,
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
