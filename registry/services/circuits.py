from django.db.models import Count, Prefetch, Q, QuerySet

from registry.models import CircuitRevision, NoiseModel, Result

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


def circuit_catalogue(*, query: str = "", tag: str = "") -> QuerySet:
    circuits = (
        CircuitRevision.objects.filter(
            state="published",
            noise_model__state__in=PUBLIC_DETAIL_STATES,
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
    return circuits.distinct().order_by("name", "slug")


def circuit_detail_queryset() -> QuerySet:
    published_results = (
        Result.objects.filter(state="published")
        .select_related("decoder_version")
        .order_by("-published_at", "id")
    )
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
            Prefetch(
                "results",
                queryset=published_results,
                to_attr="published_results",
            ),
        )
    )


def inherited_circuit_description(circuit: CircuitRevision) -> str | None:
    current = circuit
    visited = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        if current.description:
            return current.description
        current = current.previous_revision
    return None


def noise_model_catalogue(*, query: str = "", status: str = "") -> QuerySet:
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
    return noise_models.order_by("name", "slug")


def noise_model_detail_queryset() -> QuerySet:
    published_circuits = CircuitRevision.objects.filter(
        state="published"
    ).order_by("name", "slug")
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
