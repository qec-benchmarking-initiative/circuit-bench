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
from registry.filter_grids import algorithm_grid as build_algorithm_grid
from registry.filter_grids import (
    circuit_grid as build_circuit_grid,
)
from registry.filter_grids import (
    machine_grid as build_machine_grid,
)
from registry.models import DecoderVersion, Machine
from registry.result_tables import result_cell_map
from registry.services.decoders import (
    catalogue_algorithm_tags,
    inherited_description_source,
    public_decoder_catalogue,
    public_decoder_detail,
    public_predecessor,
    public_successor,
)
from registry.services.filter_options import public_circuit_filter_options
from registry.services.results import public_result_catalogue

DECODER_RESULT_COLUMNS = (
    ColumnSpec("result", "Result UUID", default_visible=False),
    ColumnSpec("circuit", "Circuit"),
    ColumnSpec("code_tags", "Code tags", sortable=False, default_visible=False),
    ColumnSpec(
        "experiment_tags", "Experiment tags", sortable=False, default_visible=False
    ),
    ColumnSpec("noise_model", "Noise model"),
    ColumnSpec("machine_class", "Machine type"),
    ColumnSpec("machine", "Machine"),
    ColumnSpec("shots", "Shots", numeric=True, default_direction="desc"),
    ColumnSpec("scores", "Evaluator scores", sortable=False),
    ColumnSpec("reproduction", "Reproduction"),
    ColumnSpec("published", "Published", default_direction="desc"),
)

DECODER_RESULT_SORT_FIELDS = {
    "result": "id",
    "circuit": "circuit_revision__name",
    "noise_model": "circuit_revision__noise_model__name",
    "machine_class": "machine__machine_class",
    "machine": "machine__slug",
    "shots": "shots_total",
    "reproduction": "reproduction_status",
    "published": "published_at",
}


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
        filter_tags = list(catalogue_algorithm_tags())
        result_values = list(
            public_decoder_catalogue().values_list("published_result_count", flat=True)
        )
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
                "filter_tags": filter_tags,
                "algorithm_filter_grid": build_algorithm_grid(
                    grid_id="decoder-algorithm-filters",
                    picker_id="decoder-algorithm-tags",
                    tags=filter_tags,
                    selected_tags=self.tag_slugs,
                    tag_match=self.tag_match,
                    skeleton=self.skeleton_preparation,
                    priors=self.priors_preparation,
                    probability=self.probability_output,
                    result_minimum=self.request.GET.get("result_min", ""),
                    result_maximum=self.request.GET.get("result_max", ""),
                    result_values=result_values,
                ),
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
        result_context = self._result_context(decoder)

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
                **result_context,
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

    def _result_context(self, decoder: DecoderVersion) -> dict[str, object]:
        request = self.request
        code_tags = self._selected("code_tag")
        experiment_tags = self._selected("experiment_tag")
        code_tag_match = self._match("code_tag_match")
        experiment_tag_match = self._match("experiment_tag_match")
        noise_model = request.GET.get("noise_model", "").strip()
        randomises_priors = request.GET.get("priors", "").strip()
        is_css = request.GET.get("css", "").strip()
        machine_class = request.GET.get("machine_class", "").strip()
        valid_machine_classes = {
            value for value, _label in Machine.MachineClass.choices
        }
        if machine_class not in {*valid_machine_classes, "unreported"}:
            machine_class = ""
        raw_ranges = {
            name: request.GET.get(name, "")
            for name in (
                "code_d_min",
                "code_d_max",
                "circuit_d_min",
                "circuit_d_max",
                "detector_min",
                "detector_max",
                "error_min",
                "error_max",
            )
        }
        parsed_ranges = {
            name: parse_nonnegative_int(value) for name, value in raw_ranges.items()
        }
        sort_keys = parse_sort(
            request.GET.get("sort", ""),
            DECODER_RESULT_COLUMNS,
            (("circuit", "asc"),),
        )
        results = list(
            apply_sort(
                public_result_catalogue(
                    decoder=decoder,
                    code_tag_slugs=code_tags,
                    code_tag_match=code_tag_match,
                    experiment_tag_slugs=experiment_tags,
                    experiment_tag_match=experiment_tag_match,
                    noise_model_slug=noise_model,
                    randomises_priors=randomises_priors,
                    is_css=is_css,
                    code_distance_min=parsed_ranges["code_d_min"],
                    code_distance_max=parsed_ranges["code_d_max"],
                    circuit_distance_min=parsed_ranges["circuit_d_min"],
                    circuit_distance_max=parsed_ranges["circuit_d_max"],
                    detector_min=parsed_ranges["detector_min"],
                    detector_max=parsed_ranges["detector_max"],
                    error_min=parsed_ranges["error_min"],
                    error_max=parsed_ranges["error_max"],
                    machine_class=machine_class,
                ),
                sort_keys,
                DECODER_RESULT_SORT_FIELDS,
            )
        )
        table = table_context(request, DECODER_RESULT_COLUMNS, sort_keys)
        detail_url = reverse("decoders:detail", args=[decoder.slug])
        rows = [
            {
                "cells": cells_for_visible_columns(
                    table["visible_column_keys"],
                    result_cell_map(result, filter_url=detail_url),
                )
            }
            for result in results
        ]
        options = public_circuit_filter_options()
        filters_active = bool(
            code_tags
            or experiment_tags
            or noise_model
            or randomises_priors
            or is_css
            or machine_class
            or any(value is not None for value in parsed_ranges.values())
        )
        return {
            "circuit_filter_grid": build_circuit_grid(
                grid_id="decoder-result-circuit-filters",
                code_tags=options["code_tags"],
                selected_code_tags=code_tags,
                code_tag_match=code_tag_match,
                experiment_tags=options["experiment_tags"],
                selected_experiment_tags=experiment_tags,
                experiment_tag_match=experiment_tag_match,
                noise_models=options["noise_models"],
                noise_model_slug=noise_model,
                randomises_priors=randomises_priors,
                is_css=is_css,
                raw_values=raw_ranges,
                distributions=options["distributions"],
            ),
            "machine_filter_grid": build_machine_grid(
                grid_id="decoder-result-machine-filters",
                machine_classes=Machine.MachineClass.choices,
                selected_machine_class=machine_class,
            ),
            "result_count": len(results),
            "result_rows": rows,
            "result_filters_active": filters_active,
            "result_reset_url": detail_url,
            "reset_sort_url": url_without(request, "sort"),
            "raw_sort": request.GET.get("sort", ""),
            "raw_columns": request.GET.get("columns", ""),
            **table,
        }

    def _selected(self, name: str) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                value.strip()
                for value in self.request.GET.getlist(name)
                if value.strip()
            )
        )

    def _match(self, name: str) -> str:
        value = self.request.GET.get(name, "all").strip()
        return value if value in {"all", "any"} else "all"
