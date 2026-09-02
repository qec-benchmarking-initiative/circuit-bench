"""Literature-backed algorithm vocabulary for development and staging data."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import Account
from registry.models import RecordHistory, SchemaRelease, Tag, TagAlias, TagParent
from registry.services.histories import (
    append_history_event,
    submission_snapshot,
)

TAXONOMY_FIXTURE_VERSION = "algorithm-literature-0.1"


@dataclass(frozen=True)
class AlgorithmTagSpec:
    slug: str
    label: str
    description: str
    colour: str
    aliases: tuple[str, ...] = ()
    parents: tuple[str, ...] = ()


ALGORITHM_TAG_SPECS = (
    AlgorithmTagSpec(
        "decoder-composition",
        "Decoder composition",
        "Combines or orders multiple decoding stages, hypotheses, or complete "
        "decoders in one decoding pipeline.",
        "#5F6570",
    ),
    AlgorithmTagSpec(
        "post-decoding-method",
        "Post-decoding method",
        "A stage that refines or replaces the candidate produced by an earlier "
        "decoding stage.",
        "#75634D",
        aliases=("Post-decoder",),
        parents=("decoder-composition",),
    ),
    AlgorithmTagSpec(
        "message-passing",
        "Message passing",
        "Iteratively exchanges local messages on a factor, Tanner, or related "
        "graph. Quantum-LDPC examples include belief-propagation pipelines. "
        "Reference: https://arxiv.org/abs/2005.07016",
        "#496A7A",
        aliases=("Message-passing decoder",),
    ),
    AlgorithmTagSpec(
        "machine-learning",
        "Machine learning",
        "Learns some part of the decoding map or policy from data. This family "
        "includes neural-network and reinforcement-learning decoders. References: "
        "https://arxiv.org/abs/2307.03280 and https://arxiv.org/abs/1810.07207",
        "#765278",
        aliases=("ML", "Learned decoder"),
    ),
    AlgorithmTagSpec(
        "local-decoder",
        "Local decoder",
        "Updates the decoding state using spatially local information and rules. "
        "Cellular-automaton decoders are an important example. Reference: "
        "https://arxiv.org/abs/2004.07247",
        "#46736F",
    ),
    AlgorithmTagSpec(
        "approximate-maximum-likelihood",
        "Approximate maximum likelihood",
        "Approximates maximum-likelihood decoding rather than evaluating the true "
        "coset probabilities. Tensor-network contraction is one such method. "
        "Reference: https://arxiv.org/abs/1405.4883",
        "#78653C",
        aliases=("Approximate MLD",),
    ),
    AlgorithmTagSpec(
        "matching",
        "Matching",
        "Constructs a correction from a weighted matching problem, normally "
        "minimum-weight perfect matching in QEC applications. Reference: "
        "https://arxiv.org/abs/quant-ph/0110143",
        "#315F7D",
        aliases=("MWPM", "MWM", "Blossom", "Minimum-weight perfect matching"),
    ),
    AlgorithmTagSpec(
        "clustering",
        "Clustering",
        "Grows and merges clusters of syndrome defects before constructing a "
        "correction. Union-find decoding is a principal example. Reference: "
        "https://arxiv.org/abs/1709.06218",
        "#4E6695",
    ),
    AlgorithmTagSpec(
        "belief-propagation",
        "Belief propagation",
        "Passes probabilistic messages between checks and error variables, usually "
        "on a Tanner graph. Reference: https://arxiv.org/abs/2005.07016",
        "#4D7283",
        aliases=("BP",),
        parents=("message-passing",),
    ),
    AlgorithmTagSpec(
        "ordered-statistics",
        "Ordered statistics",
        "Uses reliability ordering to search a controlled family of candidate "
        "corrections; commonly used after belief propagation. Reference: "
        "https://arxiv.org/abs/2005.07016",
        "#7F5F9A",
        aliases=("OSD", "Ordered-statistics decoding"),
        parents=("post-decoding-method",),
    ),
    AlgorithmTagSpec(
        "neural-network",
        "Neural network",
        "Uses a trained neural network to infer a correction, logical class, or "
        "other decoding output. Reference: https://arxiv.org/abs/2307.03280",
        "#9A4F62",
        aliases=("NN", "Neural decoder"),
        parents=("machine-learning",),
    ),
    AlgorithmTagSpec(
        "convolutional-neural-network",
        "Convolutional neural network",
        "Uses convolutional layers to exploit spatial or spatiotemporal structure "
        "in syndrome data. Reference: https://arxiv.org/abs/2312.03508",
        "#9B5B78",
        aliases=("CNN",),
        parents=("neural-network",),
    ),
    AlgorithmTagSpec(
        "recurrent-neural-network",
        "Recurrent neural network",
        "Processes a syndrome history recurrently or autoregressively. A recurrent "
        "transformer surface-code decoder is described in "
        "https://arxiv.org/abs/2310.05900",
        "#875C86",
        aliases=("RNN", "Recurrent decoder"),
        parents=("neural-network",),
    ),
    AlgorithmTagSpec(
        "graph-neural-network",
        "Graph neural network",
        "Represents syndrome information on a graph and learns a graph-structured "
        "decoding map. Reference: https://arxiv.org/abs/2307.01241",
        "#686097",
        aliases=("GNN", "Graph decoder network"),
        parents=("neural-network",),
    ),
    AlgorithmTagSpec(
        "reinforcement-learning",
        "Reinforcement learning",
        "Learns a decoding policy from rewards assigned to recovery actions or "
        "episodes. Reference: https://arxiv.org/abs/1810.07207",
        "#6F5B91",
        aliases=("RL", "Reinforcement-learning decoder"),
        parents=("machine-learning",),
    ),
    AlgorithmTagSpec(
        "cellular-automaton",
        "Cellular automaton",
        "Applies repeated local update rules across a lattice or decoding graph. "
        "Reference: https://arxiv.org/abs/2004.07247",
        "#387C7A",
        aliases=("CA decoder",),
        parents=("local-decoder",),
    ),
    AlgorithmTagSpec(
        "tensor-network",
        "Tensor network",
        "Estimates coset probabilities by contracting a tensor network, normally "
        "with a tunable contraction approximation. Reference: "
        "https://arxiv.org/abs/1405.4883",
        "#80612E",
        aliases=("TN", "Tensor-network decoder"),
        parents=("approximate-maximum-likelihood",),
    ),
    AlgorithmTagSpec(
        "union-find",
        "Union find",
        "Grows and merges clusters with a disjoint-set data structure, followed by "
        "a peeling-style correction. Reference: https://arxiv.org/abs/1709.06218",
        "#567D46",
        aliases=("UF", "Disjoint-set decoder"),
        parents=("clustering",),
    ),
    AlgorithmTagSpec(
        "fallback",
        "Fallback",
        "A secondary decoding method invoked when another decoding stage declines, "
        "times out, or reports insufficient confidence.",
        "#755844",
        aliases=("Post processing",),
        parents=("decoder-composition",),
    ),
    AlgorithmTagSpec(
        "predecoder",
        "Predecoder",
        "A preliminary stage that resolves selected syndrome structure before the "
        "main decoder is invoked.",
        "#497178",
        aliases=("Pre-decoder",),
        parents=("decoder-composition",),
    ),
    AlgorithmTagSpec(
        "ensemble",
        "Ensemble",
        "Combines outputs, scores, or hypotheses from more than one decoder or "
        "trained model.",
        "#765278",
        aliases=("Decoder ensemble",),
        parents=("decoder-composition",),
    ),
    AlgorithmTagSpec(
        "renormalization-group",
        "Renormalization group",
        "Coarse-grains a decoding problem across length scales. Reference: "
        "https://arxiv.org/abs/1006.1362",
        "#5A6F8C",
        aliases=("RG decoder", "Renormalisation group"),
    ),
    AlgorithmTagSpec(
        "belief-propagation-guided-decimation",
        "Belief-propagation-guided decimation",
        "Uses belief-propagation marginals to select variables for successive "
        "decimation. Reference: https://arxiv.org/abs/2312.10950",
        "#587A87",
        aliases=("BPGD", "BP-guided decimation"),
        parents=("belief-propagation",),
    ),
)


@transaction.atomic
def reconcile_demo_algorithm_taxonomy() -> dict[str, int]:
    """Install the curated development vocabulary without deleting identities."""

    from registry.demo import DEMO_ACCOUNT_ID, demo_id

    curator = Account.objects.get(id=DEMO_ACCOUNT_ID)
    release = SchemaRelease.objects.get(record_type="tag", version="0.1")
    now = timezone.now()
    tags: dict[str, Tag] = {}
    created_count = 0
    updated_count = 0

    for spec in ALGORITHM_TAG_SPECS:
        tag = Tag.objects.filter(
            namespace=Tag.Namespace.ALGORITHM,
            slug=spec.slug,
        ).first()
        created = tag is None
        if created:
            history, _ = RecordHistory.objects.get_or_create(
                id=demo_id(f"history/tag/algorithm/{spec.slug}"),
                defaults={"record_kind": "tag"},
            )
            tag = Tag.objects.create(
                id=demo_id(f"tag/algorithm/{spec.slug}"),
                schema_release=release,
                history=history,
                namespace=Tag.Namespace.ALGORITHM,
                slug=spec.slug,
                label=spec.label,
                description=spec.description,
                status=Tag.Status.OFFICIAL,
                display_color=spec.colour,
                submitted_by=curator,
                curated_by=curator,
                curated_at=now,
            )
            submitted = append_history_event(
                kind="tag",
                record=tag,
                actor=curator,
                action="submitted",
                note=(
                    "Added a literature-backed algorithm term to the development "
                    "vocabulary."
                ),
                details={"fixture": True, "fixture_version": TAXONOMY_FIXTURE_VERSION},
                payload_snapshot=submission_snapshot(
                    "tag",
                    {
                        "namespace": tag.namespace,
                        "slug": tag.slug,
                        "label": tag.label,
                        "description": tag.description,
                        "status": Tag.Status.OFFICIAL,
                    },
                ),
            )
            approved = append_history_event(
                kind="tag",
                record=tag,
                actor_system="demo_seed",
                action="approved",
                note="Approved as deterministic development vocabulary.",
                details={"fixture": True, "fixture_version": TAXONOMY_FIXTURE_VERSION},
                caused_by=submitted,
            )
            append_history_event(
                kind="tag",
                record=tag,
                actor_system="demo_seed",
                action="published",
                note="Published as deterministic development vocabulary.",
                details={"fixture": True, "fixture_version": TAXONOMY_FIXTURE_VERSION},
                caused_by=approved,
            )
            created_count += 1

        changed_fields = []
        for field, value in (
            ("label", spec.label),
            ("description", spec.description),
            ("display_color", spec.colour),
        ):
            if getattr(tag, field) != value:
                setattr(tag, field, value)
                changed_fields.append(field)
        if tag.status == Tag.Status.CUSTOM:
            tag.status = Tag.Status.OFFICIAL
            tag.curated_by = curator
            tag.curated_at = now
            changed_fields.extend(("status", "curated_by", "curated_at"))
            if not tag.record_events.filter(action="promoted_official").exists():
                append_history_event(
                    kind="tag",
                    record=tag,
                    actor=curator,
                    action="promoted_official",
                    note="Promoted into the literature-backed development vocabulary.",
                    details={
                        "fixture": True,
                        "fixture_version": TAXONOMY_FIXTURE_VERSION,
                        "previous_status": Tag.Status.CUSTOM,
                        "new_status": Tag.Status.OFFICIAL,
                        "display_color": spec.colour,
                    },
                )
        if changed_fields:
            tag.save(update_fields=[*changed_fields, "updated_at"])
            updated_count += int(not created)
        tags[spec.slug] = tag

    alias_count = _reconcile_aliases(tags, curator, demo_id)
    edge_count, changed_children = _reconcile_parents(tags)
    for child_slug in changed_children:
        tag = tags[child_slug]
        append_history_event(
            kind="tag",
            record=tag,
            actor=curator,
            action="edited",
            note="Reconciled the literature-backed parent taxonomy.",
            details={
                "fixture": True,
                "fixture_version": TAXONOMY_FIXTURE_VERSION,
                "changed_fields": ["parents"],
            },
            payload_snapshot=submission_snapshot(
                "tag",
                {
                    "namespace": tag.namespace,
                    "slug": tag.slug,
                    "parent_tag_ids": [
                        str(parent_id)
                        for parent_id in tag.parents.order_by("id").values_list(
                            "id", flat=True
                        )
                    ],
                    "status": tag.status,
                },
            ),
        )
    return {
        "tags": len(tags),
        "created": created_count,
        "updated": updated_count,
        "aliases_added": alias_count,
        "parent_edges": edge_count,
    }


def _reconcile_aliases(tags, curator, demo_id) -> int:
    added = 0
    for spec in ALGORITHM_TAG_SPECS:
        tag = tags[spec.slug]
        for alias in spec.aliases:
            existing = TagAlias.objects.filter(
                alias__iexact=alias, is_active=True
            ).first()
            if existing is not None:
                if existing.tag_id != tag.id:
                    raise RuntimeError(
                        f'The development alias "{alias}" belongs to {existing.tag}.'
                    )
                continue
            alias_record = TagAlias.objects.create(
                id=demo_id(f"tag/algorithm/{spec.slug}/alias/{alias.casefold()}"),
                tag=tag,
                alias=alias,
                is_active=True,
                added_by=curator,
            )
            append_history_event(
                kind="tag",
                record=tag,
                actor=curator,
                action="added_alias",
                note=f"Added the alias “{alias}”.",
                details={
                    "fixture": True,
                    "fixture_version": TAXONOMY_FIXTURE_VERSION,
                    "alias_id": str(alias_record.id),
                    "alias": alias,
                },
            )
            added += 1
    return added


def _reconcile_parents(tags) -> tuple[int, set[str]]:
    changed_children = set()
    for spec in ALGORITHM_TAG_SPECS:
        tag = tags[spec.slug]
        desired_ids = {tags[parent_slug].id for parent_slug in spec.parents}
        existing_ids = set(tag.parents.values_list("id", flat=True))
        if existing_ids == desired_ids:
            continue
        TagParent.objects.filter(child=tag).exclude(parent_id__in=desired_ids).delete()
        TagParent.objects.bulk_create(
            TagParent(child=tag, parent_id=parent_id)
            for parent_id in desired_ids - existing_ids
        )
        changed_children.add(spec.slug)
    return TagParent.objects.filter(
        child__namespace=Tag.Namespace.ALGORITHM,
        child__slug__in=tags,
    ).count(), changed_children
