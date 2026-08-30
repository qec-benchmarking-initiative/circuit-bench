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

from registry.models import CircuitRevision, NoiseModel, Result, Tag

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


def circuit_catalogue(
    *,
    query: str = "",
    tag: str = "",
    code_tag_slugs: tuple[str, ...] = (),
    experiment_tag_slugs: tuple[str, ...] = (),
    code_tag_match: str = "all",
    experiment_tag_match: str = "all",
    noise_model_slug: str = "",
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
) -> QuerySet:
    circuits = (
        CircuitRevision.objects.filter(
            state="published",
            noise_model__state__in=PUBLIC_DETAIL_STATES,
        )
        .annotate(
            published_result_count=Count(
                "results",
                filter=Q(results__state="published"),
                distinct=True,
            )
        )
        .select_related("noise_model")
        .prefetch_related("code_tags", "experiment_tags")
    )
    if query:
        circuits = circuits.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(code_tags__label__icontains=query)
            | Q(code_tags__slug__icontains=query)
            | Q(experiment_tags__label__icontains=query)
            | Q(experiment_tags__slug__icontains=query)
        )
    if tag:
        namespace, separator, slug = tag.partition(":")
        if not separator or namespace not in {"code", "experiment"} or not slug:
            return circuits.none()
        relation = "code_tags" if namespace == "code" else "experiment_tags"
        circuits = circuits.filter(
            **{
                f"{relation}__namespace": namespace,
                f"{relation}__slug": slug,
            }
        )
    if code_tag_match == "any" and code_tag_slugs:
        circuits = circuits.filter(
            code_tags__namespace="code", code_tags__slug__in=code_tag_slugs
        )
    else:
        for slug in code_tag_slugs:
            circuits = circuits.filter(
                code_tags__namespace="code", code_tags__slug=slug
            )
    if experiment_tag_match == "any" and experiment_tag_slugs:
        circuits = circuits.filter(
            experiment_tags__namespace="experiment",
            experiment_tags__slug__in=experiment_tag_slugs,
        )
    else:
        for slug in experiment_tag_slugs:
            circuits = circuits.filter(
                experiment_tags__namespace="experiment",
                experiment_tags__slug=slug,
            )
    if noise_model_slug:
        circuits = circuits.filter(noise_model__slug=noise_model_slug)
    if randomises_priors in {"yes", "no"}:
        circuits = circuits.filter(
            noise_model__randomises_priors=randomises_priors == "yes"
        )
    if is_css in {"yes", "no"}:
        circuits = circuits.filter(is_css=is_css == "yes")
    for field, minimum, maximum in (
        ("code_distance_upper_bound", code_distance_min, code_distance_max),
        ("circuit_distance_upper_bound", circuit_distance_min, circuit_distance_max),
        ("num_detectors", detector_min, detector_max),
        ("num_errors", error_min, error_max),
    ):
        if minimum is not None:
            circuits = circuits.filter(**{f"{field}__gte": minimum})
        if maximum is not None:
            circuits = circuits.filter(**{f"{field}__lte": maximum})
    return circuits.distinct()


def circuit_detail_queryset() -> QuerySet:
    return (
        CircuitRevision.objects.filter(
            state__in=PUBLIC_DETAIL_STATES,
            noise_model__state__in=PUBLIC_DETAIL_STATES,
        )
        .select_related(
            "schema_release",
            "noise_model",
            "previous_revision",
            "sampling_circuit_artifact",
            "detector_error_model_artifact",
            "manifest_artifact",
            "submitted_by",
        )
        .prefetch_related(
            "code_tags",
            "experiment_tags",
        )
    )


def circuit_result_leaderboard(
    *,
    circuit: CircuitRevision,
    tag_slugs: tuple[str, ...] = (),
    tag_match: str = "all",
    skeleton_preparation: str = "",
    priors_preparation: str = "",
    probability_output: str = "",
    machine_class: str = "",
) -> QuerySet[Result]:
    """Return published results scoped to one circuit and reusable filters."""

    algorithm_tags = (
        Tag.objects.filter(namespace=Tag.Namespace.ALGORITHM)
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
    results = (
        Result.objects.filter(circuit_revision=circuit, state="published")
        .select_related(
            "decoder_version",
            "evaluator_version",
            "machine",
        )
        .prefetch_related(
            Prefetch(
                "decoder_version__algorithm_tags",
                queryset=algorithm_tags,
                to_attr="display_algorithm_tags",
            ),
            "scores__score_definition",
        )
    )

    selected_tags = tuple(tag for tag in tag_slugs if tag)
    if tag_match == "any" and selected_tags:
        results = results.filter(
            decoder_version__algorithm_tags__namespace=Tag.Namespace.ALGORITHM,
            decoder_version__algorithm_tags__slug__in=selected_tags,
        )
    else:
        for selected_tag in selected_tags:
            results = results.filter(
                decoder_version__algorithm_tags__namespace=Tag.Namespace.ALGORITHM,
                decoder_version__algorithm_tags__slug=selected_tag,
            )

    if skeleton_preparation in {"required", "not_required"}:
        results = results.filter(
            decoder_version__circuit_skeleton_preparation=skeleton_preparation
        )
    if priors_preparation in {"required", "not_required"}:
        results = results.filter(
            decoder_version__circuit_priors_preparation=priors_preparation
        )
    if probability_output in {"yes", "no"}:
        results = results.filter(
            decoder_version__provides_failure_probability=probability_output == "yes"
        )
    if machine_class == "unreported":
        results = results.filter(machine__isnull=True)
    elif machine_class in {"cpu", "gpu", "fpga", "asic", "hybrid"}:
        results = results.filter(machine__machine_class=machine_class)

    return results.distinct()


def inherited_circuit_description(circuit: CircuitRevision) -> str | None:
    current = circuit
    visited = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        if current.description:
            return current.description
        current = current.previous_revision
    return None


def noise_model_catalogue(
    *,
    query: str = "",
    status: str = "",
    randomises_priors: str = "",
    circuit_min: int | None = None,
    circuit_max: int | None = None,
) -> QuerySet:
    noise_models = NoiseModel.objects.filter(state="published").annotate(
        circuit_count=Count(
            "circuit_revisions",
            filter=Q(circuit_revisions__state="published"),
            distinct=True,
        )
    )
    if query:
        noise_models = noise_models.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(short_description__icontains=query)
        )
    if status:
        noise_models = noise_models.filter(curation_status=status)
    if randomises_priors in {"yes", "no"}:
        noise_models = noise_models.filter(randomises_priors=randomises_priors == "yes")
    if circuit_min is not None:
        noise_models = noise_models.filter(circuit_count__gte=circuit_min)
    if circuit_max is not None:
        noise_models = noise_models.filter(circuit_count__lte=circuit_max)
    return noise_models


def noise_model_detail_queryset() -> QuerySet:
    published_circuits = CircuitRevision.objects.filter(state="published").order_by(
        "name", "slug"
    )
    return (
        NoiseModel.objects.filter(state__in=PUBLIC_DETAIL_STATES)
        .select_related(
            "schema_release",
            "submitted_by",
            "supersedes_noise_model",
        )
        .prefetch_related(
            Prefetch(
                "circuit_revisions",
                queryset=published_circuits,
                to_attr="published_circuits",
            ),
        )
    )
