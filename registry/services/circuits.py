from collections.abc import Sequence

from django.db.models import (
    Count,
    Prefetch,
    Q,
    QuerySet,
)

from registry.models import (
    CircuitRevision,
    EczTerm,
    NoiseModel,
    Result,
    Tag,
    TagEczMapping,
)
from registry.services.results import public_result_catalogue
from registry.services.tag_hierarchy import (
    descendant_slug_groups,
    inclusive_code_descendant_identities,
)
from registry.services.visibility import actor_visibility_q

PUBLIC_DETAIL_STATES = ("published", "withdrawn")


def _code_tag_queryset(viewer=None):
    return (
        Tag.objects.filter(actor_visibility_q(viewer))
        .prefetch_related(
            Prefetch(
                "ecz_mappings",
                queryset=TagEczMapping.objects.filter(
                    status=TagEczMapping.Status.ACTIVE
                ).select_related("ecz_term"),
                to_attr="active_ecz_mappings",
            )
        )
        .order_by("label", "id")
    )


def circuit_catalogue(
    *,
    query: str = "",
    tag: str = "",
    code_tag_slugs: tuple[str, ...] = (),
    experiment_tag_slugs: tuple[str, ...] = (),
    code_tag_match: str = "all",
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
) -> QuerySet:
    circuits = (
        CircuitRevision.objects.filter(
            state="published",
            visibility="public",
            noise_model__state__in=PUBLIC_DETAIL_STATES,
            noise_model__visibility="public",
        )
        .annotate(
            published_result_count=Count(
                "results",
                filter=Q(results__state="published", results__visibility="public"),
                distinct=True,
            )
        )
        .select_related("noise_model")
        .prefetch_related(
            Prefetch(
                "code_tags",
                queryset=_code_tag_queryset(),
                to_attr="display_code_tags",
            ),
            Prefetch(
                "ecz_terms",
                queryset=EczTerm.objects.order_by("display_name", "ecz_code_id"),
                to_attr="display_ecz_terms",
            ),
            Prefetch(
                "experiment_tags",
                queryset=Tag.objects.filter(visibility="public").order_by(
                    "label", "id"
                ),
                to_attr="display_experiment_tags",
            ),
        )
    )
    if query:
        circuits = circuits.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(code_tags__label__icontains=query)
            | Q(code_tags__slug__icontains=query)
            | Q(ecz_terms__display_name__icontains=query)
            | Q(ecz_terms__ecz_code_id__icontains=query)
            | Q(
                code_tags__aliases__alias__icontains=query,
                code_tags__aliases__is_active=True,
            )
            | Q(experiment_tags__label__icontains=query)
            | Q(experiment_tags__slug__icontains=query)
            | Q(
                experiment_tags__aliases__alias__icontains=query,
                experiment_tags__aliases__is_active=True,
            )
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
    circuits = _filter_code_taxonomy(circuits, code_tag_slugs, code_tag_match)
    selected_experiment_tags = tuple(
        dict.fromkeys(slug for slug in experiment_tag_slugs if slug)
    )
    if experiment_tag_match == "children" and selected_experiment_tags:
        experiment_groups = descendant_slug_groups(
            Tag.Namespace.EXPERIMENT, selected_experiment_tags
        )
        circuits = circuits.filter(
            experiment_tags__namespace="experiment",
            experiment_tags__slug__in={
                slug for group in experiment_groups for slug in group
            },
        )
    elif experiment_tag_match == "any" and selected_experiment_tags:
        circuits = circuits.filter(
            experiment_tags__namespace="experiment",
            experiment_tags__slug__in=selected_experiment_tags,
        )
    else:
        for slug in selected_experiment_tags:
            circuits = circuits.filter(
                experiment_tags__namespace="experiment",
                experiment_tags__slug=slug,
            )
    if noise_model_slugs:
        circuits = circuits.filter(noise_model__slug__in=noise_model_slugs)
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


def _filter_code_taxonomy(queryset, identities, match):
    if match == "children":
        identities = inclusive_code_descendant_identities(identities)
        match = "any"
    predicates = []
    for identity in identities:
        source, separator, value = identity.partition(":")
        if separator and source == "ecz" and value:
            predicates.append(
                Q(ecz_terms__ecz_code_id=value)
                | Q(
                    code_tags__ecz_mappings__status=TagEczMapping.Status.ACTIVE,
                    code_tags__ecz_mappings__ecz_term__ecz_code_id=value,
                )
            )
        elif separator and source == "cb" and value:
            predicates.append(Q(code_tags__namespace="code", code_tags__id=value))
        elif not separator and identity:
            predicates.append(Q(code_tags__namespace="code", code_tags__slug=identity))
    if match == "any" and predicates:
        combined = Q()
        for predicate in predicates:
            combined |= predicate
        return queryset.filter(combined)
    for predicate in predicates:
        queryset = queryset.filter(predicate)
    return queryset


def circuit_detail_queryset(viewer=None) -> QuerySet:
    return (
        CircuitRevision.objects.filter(
            state__in=PUBLIC_DETAIL_STATES,
            noise_model__state__in=PUBLIC_DETAIL_STATES,
        )
        .filter(actor_visibility_q(viewer))
        .filter(actor_visibility_q(viewer, "noise_model__"))
        .select_related(
            "schema_release",
            "noise_model",
            "predecessor",
            "sampling_circuit_artifact",
            "detector_error_model_artifact",
            "manifest_artifact",
            "submitted_by",
        )
        .prefetch_related(
            Prefetch(
                "code_tags",
                queryset=_code_tag_queryset(viewer),
                to_attr="display_code_tags",
            ),
            Prefetch(
                "ecz_terms",
                queryset=EczTerm.objects.order_by("display_name", "ecz_code_id"),
                to_attr="display_ecz_terms",
            ),
            Prefetch(
                "experiment_tags",
                queryset=Tag.objects.filter(actor_visibility_q(viewer)).order_by(
                    "label", "id"
                ),
                to_attr="display_experiment_tags",
            ),
        )
    )


def circuit_result_leaderboard(
    *,
    circuit: CircuitRevision,
    viewer=None,
    tag_slugs: tuple[str, ...] = (),
    tag_match: str = "all",
    skeleton_preparation: str = "",
    priors_preparation: str = "",
    probability_output: str = "",
    machine_class: str = "",
) -> QuerySet[Result]:
    """Return published results scoped to one circuit and reusable filters."""
    return public_result_catalogue(
        circuit=circuit,
        viewer=viewer,
        algorithm_tag_slugs=tag_slugs,
        algorithm_tag_match=tag_match,
        skeleton_preparation=skeleton_preparation,
        decoder_priors_preparation=priors_preparation,
        probability_output=probability_output,
        machine_class=machine_class,
    )


def inherited_circuit_description(circuit: CircuitRevision) -> str | None:
    current = circuit
    visited = set()
    while current is not None and current.id not in visited:
        visited.add(current.id)
        if current.description:
            return current.description
        current = current.predecessor
    return None


def noise_model_catalogue(
    *,
    query: str = "",
    status: str = "",
    randomises_priors: str = "",
    circuit_min: int | None = None,
    circuit_max: int | None = None,
) -> QuerySet:
    noise_models = NoiseModel.objects.filter(
        state="published", visibility="public"
    ).annotate(
        circuit_count=Count(
            "circuit_revisions",
            filter=Q(
                circuit_revisions__state="published",
                circuit_revisions__visibility="public",
            ),
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


def noise_model_detail_queryset(viewer=None) -> QuerySet:
    published_circuits = (
        CircuitRevision.objects.filter(state="published")
        .filter(actor_visibility_q(viewer))
        .order_by("name", "slug")
    )
    return (
        NoiseModel.objects.filter(state__in=PUBLIC_DETAIL_STATES)
        .filter(actor_visibility_q(viewer))
        .select_related(
            "schema_release",
            "submitted_by",
            "predecessor",
        )
        .prefetch_related(
            Prefetch(
                "circuit_revisions",
                queryset=published_circuits,
                to_attr="published_circuits",
            ),
        )
    )
