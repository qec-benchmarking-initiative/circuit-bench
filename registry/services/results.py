"""Public result queries shared by leaderboards and the result explorer."""

from collections.abc import Sequence

from django.db.models import Case, IntegerField, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Lower

from registry.models import CircuitRevision, DecoderVersion, Machine, Result, Tag


def public_result_catalogue(
    *,
    query: str = "",
    circuit: CircuitRevision | None = None,
    decoder: DecoderVersion | None = None,
    machine: Machine | None = None,
    algorithm_tag_slugs: Sequence[str] = (),
    algorithm_tag_match: str = "all",
    skeleton_preparation: str = "",
    decoder_priors_preparation: str = "",
    probability_output: str = "",
    code_tag_slugs: Sequence[str] = (),
    code_tag_match: str = "all",
    experiment_tag_slugs: Sequence[str] = (),
    experiment_tag_match: str = "all",
    noise_model_slugs: Sequence[str] = (),
    randomises_priors: str = "",
    is_css: str = "",
    code_distance_min: int | None = None,
    code_distance_max: int | None = None,
    circuit_distance_min: int | None = None,
    circuit_distance_max: int | None = None,
    detector_min: int | None = None,
    detector_max: int | None = None,
    error_min: int | None = None,
    error_max: int | None = None,
    machine_class: str = "",
) -> QuerySet[Result]:
    """Return published results under the same filters on every public page."""

    results = (
        Result.objects.filter(state="published")
        .select_related(
            "decoder_version",
            "circuit_revision",
            "circuit_revision__noise_model",
            "evaluator_version",
            "machine",
        )
        .prefetch_related(
            Prefetch(
                "decoder_version__algorithm_tags",
                queryset=_display_tags(Tag.Namespace.ALGORITHM),
                to_attr="display_algorithm_tags",
            ),
            Prefetch(
                "circuit_revision__code_tags",
                queryset=_display_tags(Tag.Namespace.CODE),
                to_attr="display_code_tags",
            ),
            Prefetch(
                "circuit_revision__experiment_tags",
                queryset=_display_tags(Tag.Namespace.EXPERIMENT),
                to_attr="display_experiment_tags",
            ),
            "scores__score_definition",
        )
    )
    if circuit is not None:
        results = results.filter(circuit_revision=circuit)
    if decoder is not None:
        results = results.filter(decoder_version=decoder)
    if machine is not None:
        results = results.filter(machine=machine)
    if query:
        results = results.filter(
            Q(decoder_version__name__icontains=query)
            | Q(decoder_version__version__icontains=query)
            | Q(decoder_version__slug__icontains=query)
            | Q(circuit_revision__name__icontains=query)
            | Q(circuit_revision__slug__icontains=query)
            | Q(circuit_revision__noise_model__name__icontains=query)
            | Q(machine__slug__icontains=query)
            | Q(evaluator_version__version__icontains=query)
        )

    results = _filter_tags(
        results,
        relation="decoder_version__algorithm_tags",
        namespace=Tag.Namespace.ALGORITHM,
        slugs=algorithm_tag_slugs,
        match=algorithm_tag_match,
    )
    results = _filter_tags(
        results,
        relation="circuit_revision__code_tags",
        namespace=Tag.Namespace.CODE,
        slugs=code_tag_slugs,
        match=code_tag_match,
    )
    results = _filter_tags(
        results,
        relation="circuit_revision__experiment_tags",
        namespace=Tag.Namespace.EXPERIMENT,
        slugs=experiment_tag_slugs,
        match=experiment_tag_match,
    )

    if skeleton_preparation in {"required", "not_required"}:
        results = results.filter(
            decoder_version__circuit_skeleton_preparation=skeleton_preparation
        )
    if decoder_priors_preparation in {"required", "not_required"}:
        results = results.filter(
            decoder_version__circuit_priors_preparation=decoder_priors_preparation
        )
    if probability_output in {"yes", "no"}:
        results = results.filter(
            decoder_version__provides_failure_probability=probability_output == "yes"
        )
    if noise_model_slugs:
        results = results.filter(
            circuit_revision__noise_model__slug__in=noise_model_slugs
        )
    if randomises_priors in {"yes", "no"}:
        results = results.filter(
            circuit_revision__noise_model__randomises_priors=(
                randomises_priors == "yes"
            )
        )
    if is_css in {"yes", "no"}:
        results = results.filter(circuit_revision__is_css=is_css == "yes")

    for value, lookup in (
        (code_distance_min, "circuit_revision__code_distance_upper_bound__gte"),
        (code_distance_max, "circuit_revision__code_distance_upper_bound__lte"),
        (
            circuit_distance_min,
            "circuit_revision__circuit_distance_upper_bound__gte",
        ),
        (
            circuit_distance_max,
            "circuit_revision__circuit_distance_upper_bound__lte",
        ),
        (detector_min, "circuit_revision__num_detectors__gte"),
        (detector_max, "circuit_revision__num_detectors__lte"),
        (error_min, "circuit_revision__num_errors__gte"),
        (error_max, "circuit_revision__num_errors__lte"),
    ):
        if value is not None:
            results = results.filter(**{lookup: value})

    if machine_class == "unreported":
        results = results.filter(machine__isnull=True)
    elif machine_class in {"cpu", "gpu", "fpga", "asic", "hybrid"}:
        results = results.filter(machine__machine_class=machine_class)
    return results.distinct()


def _display_tags(namespace: str) -> QuerySet[Tag]:
    return (
        Tag.objects.filter(namespace=namespace)
        .annotate(
            official_order=Case(
                When(status=Tag.Status.OFFICIAL, then=Value(0)),
                When(status=Tag.Status.CUSTOM, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("official_order", Lower("label"), "id")
    )


def _filter_tags(
    results: QuerySet[Result],
    *,
    relation: str,
    namespace: str,
    slugs: Sequence[str],
    match: str,
) -> QuerySet[Result]:
    selected = tuple(dict.fromkeys(slug for slug in slugs if slug))
    if not selected:
        return results
    namespace_lookup = f"{relation}__namespace"
    slug_lookup = f"{relation}__slug"
    if match == "any":
        return results.filter(
            **{namespace_lookup: namespace, f"{slug_lookup}__in": selected}
        )
    for slug in selected:
        results = results.filter(**{namespace_lookup: namespace, slug_lookup: slug})
    return results
