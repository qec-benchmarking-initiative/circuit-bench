"""Read-side helpers for tag pickers and public tag pages."""

from django.db.models import Case, IntegerField, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Lower

from registry.models import Tag, TagAlias
from registry.services.visibility import actor_visibility_q


def active_tag_queryset(
    namespace: str | None = None,
    *,
    include_ids=(),
    actor=None,
) -> QuerySet[Tag]:
    """Return selectable tags with their active aliases in display order."""

    queryset = Tag.objects.filter(
        ~Q(status__in=(Tag.Status.DEPRECATED, Tag.Status.RETIRED))
        | Q(id__in=include_ids)
    )
    queryset = queryset.filter(actor_visibility_q(actor))
    if namespace is not None:
        queryset = queryset.filter(namespace=namespace)
    alias_queryset = TagAlias.objects.filter(is_active=True).order_by(
        Lower("alias"), "id"
    )
    parent_queryset = Tag.objects.prefetch_related(
        Prefetch(
            "aliases",
            queryset=alias_queryset,
            to_attr="display_aliases",
        )
    ).order_by(Lower("label"), "id")
    return (
        queryset.annotate(
            official_order=Case(
                When(status=Tag.Status.OFFICIAL, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .prefetch_related(
            Prefetch(
                "aliases",
                queryset=alias_queryset,
                to_attr="display_aliases",
            ),
            Prefetch("parents", queryset=parent_queryset, to_attr="display_parents"),
        )
        .order_by("namespace", "official_order", Lower("label"), "id")
    )


def tag_detail_queryset(viewer=None) -> QuerySet[Tag]:
    return (
        Tag.objects.filter(actor_visibility_q(viewer))
        .select_related(
            "schema_release",
            "history",
            "submitted_by",
            "curated_by",
            "canonical_tag",
        )
        .prefetch_related(
            Prefetch(
                "aliases",
                queryset=TagAlias.objects.filter(is_active=True)
                .select_related("added_by")
                .order_by(Lower("alias"), "id"),
                to_attr="display_aliases",
            )
        )
    )
