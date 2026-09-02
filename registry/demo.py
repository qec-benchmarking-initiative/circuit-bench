import uuid
from decimal import Decimal

from django.conf import settings
from django.contrib.sites.models import Site
from django.db import transaction
from django.utils import timezone

from accounts.models import Account, ExternalIdentity
from registry.models import (
    Artifact,
    ArtifactAttachment,
    BenchmarkAttempt,
    BenchmarkAttemptResult,
    BenchmarkRevision,
    BenchmarkRevisionItem,
    CircuitRevision,
    CircuitRevisionCodeTag,
    CircuitRevisionEczTerm,
    CircuitRevisionExperimentTag,
    Credit,
    DecoderVersion,
    DecoderVersionAlgorithmTag,
    EczTerm,
    EvaluatorRelease,
    ExternalLink,
    Machine,
    NoiseModel,
    RecordHistory,
    Result,
    ResultScore,
    SchemaRelease,
    ScoreDefinition,
    Tag,
    TagAlias,
    TagEczParent,
)
from registry.services.artifacts import store_artifact_chunks
from registry.services.histories import append_history_event, submission_snapshot

DEMO_NAMESPACE = uuid.UUID("f333b191-09a8-4631-8775-3cb6fc51426e")
DEMO_ACCOUNT_ID = uuid.uuid5(DEMO_NAMESPACE, "account/uploader")

LEGACY_DEMO_CODE_TAG_SLUGS = (
    "bacon-shor-code",
    "bivariate-bicycle-144",
    "bivariate-bicycle-code",
    "bosonic-code",
    "cat-code",
    "colour-code",
    "css-code",
    "gkp-code",
    "homological-product-code",
    "hypergraph-product-code",
    "planar-surface-code",
    "quantum-error-correcting-code",
    "quantum-ldpc-code",
    "rotated-surface-code",
    "stabilizer-code",
    "subsystem-code",
    "surface-code",
    "topological-code",
    "toric-code",
    "triangular-colour-code",
    "xzzx-surface-code",
)

DEMO_CIRCUIT_ECZ_CODES = {
    "circuit/rotated-memory-d5": "rotated_surface",
    "circuit/rotated-memory-d3": "rotated_surface",
    "circuit/rotated-memory-d7": "rotated_surface",
    "circuit/rotated-memory-d9": "rotated_surface",
    "circuit/planar-stability-d5": "rotated_surface",
    "circuit/colour-memory-d5": "triangular_color",
    "circuit/bicycle-memory-144": "gross",
    "circuit/surface-cnot-d3": "rotated_surface",
    "submission/circuit/rotated-memory-d7": "rotated_surface",
}


def demo_id(name: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NAMESPACE, name)


def _demo_history(name: str, kind: str) -> RecordHistory:
    history, _created = RecordHistory.objects.get_or_create(
        id=demo_id(f"history/{name}"),
        defaults={"record_kind": kind},
    )
    if history.record_kind != kind:
        raise ValueError(f"Demo history {name} has the wrong record kind.")
    return history


@transaction.atomic
def seed_demo_data() -> dict[str, int]:
    if Account.objects.filter(id=DEMO_ACCOUNT_ID).exists():
        _refresh_demo_presentation()
        return demo_counts()

    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": settings.PUBLIC_SITE_HOST, "name": "Circuit Bench"},
    )
    published_at = timezone.now()

    uploader = Account.objects.create_user(
        id=DEMO_ACCOUNT_ID,
        display_name="Ada Decoder",
        is_admin=True,
    )
    contributor = Account.objects.create_user(
        id=demo_id("account/contributor"),
        display_name="Casey Circuit",
    )
    ExternalIdentity.objects.bulk_create(
        [
            ExternalIdentity(
                id=demo_id("identity/uploader/github"),
                account=uploader,
                provider="github",
                provider_subject="1000001",
                public_identifier="ada-decoder",
                profile_url="https://github.com/ada-decoder",
                last_authenticated_at=published_at,
            ),
            ExternalIdentity(
                id=demo_id("identity/uploader/orcid"),
                account=uploader,
                provider="orcid",
                provider_subject="0000-0002-1825-0097",
                public_identifier="0000-0002-1825-0097",
                profile_url="https://orcid.org/0000-0002-1825-0097",
                last_authenticated_at=published_at,
            ),
            ExternalIdentity(
                id=demo_id("identity/contributor/github"),
                account=contributor,
                provider="github",
                provider_subject="1000002",
                public_identifier="casey-circuit",
                profile_url="https://github.com/casey-circuit",
                last_authenticated_at=published_at,
            ),
        ]
    )

    releases = _create_schema_releases(uploader, published_at)

    matching = Tag.objects.create(
        id=demo_id("tag/algorithm/matching"),
        schema_release=releases["tag"],
        history=_demo_history("tag/algorithm/matching", "tag"),
        namespace="algorithm",
        slug="matching",
        label="Matching",
        description="Uses a matching-based decoding step.",
        status="official",
        display_color="#315f7d",
        submitted_by=uploader,
        curated_by=uploader,
        curated_at=published_at,
    )
    belief_propagation = Tag.objects.create(
        id=demo_id("tag/algorithm/belief-propagation"),
        schema_release=releases["tag"],
        history=_demo_history("tag/algorithm/belief-propagation", "tag"),
        namespace="algorithm",
        slug="belief-propagation",
        label="Belief propagation",
        description="Uses belief propagation in its decoding pipeline.",
        status="custom",
        submitted_by=contributor,
    )
    bicycle_162 = Tag.objects.create(
        id=demo_id("tag/code/bivariate-bicycle-162"),
        schema_release=releases["tag"],
        history=_demo_history("tag/code/bivariate-bicycle-162", "tag"),
        namespace="code",
        slug="bivariate-bicycle-162",
        label="Bivariate bicycle 162",
        description=(
            "The 162-data-qubit member of a bivariate bicycle-code family. "
            "This member is not currently represented by an ECZ entry."
        ),
        status="official",
        display_color="#526e3d",
        submitted_by=uploader,
        curated_by=uploader,
        curated_at=published_at,
    )
    memory = Tag.objects.create(
        id=demo_id("tag/experiment/memory"),
        schema_release=releases["tag"],
        history=_demo_history("tag/experiment/memory", "tag"),
        namespace="experiment",
        slug="memory",
        label="Memory",
        description="Preserves encoded quantum information over time.",
        status="official",
        display_color="#4f704b",
        submitted_by=uploader,
        curated_by=uploader,
        curated_at=published_at,
    )

    fixed_noise = NoiseModel.objects.create(
        id=demo_id("noise/fixed-phenomenological"),
        schema_release=releases["noise_model"],
        history=_demo_history("noise/fixed-phenomenological", "noise_model"),
        slug="fixed-phenomenological",
        name="Fixed phenomenological noise",
        short_description="A simple fixed-prior phenomenological noise model.",
        paper_url="https://example.org/papers/fixed-noise",
        randomises_priors=False,
        curation_status="official",
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    randomised_noise = NoiseModel.objects.create(
        id=demo_id("noise/randomised-phenomenological"),
        schema_release=releases["noise_model"],
        history=_demo_history("noise/randomised-phenomenological", "noise_model"),
        slug="randomised-phenomenological",
        name="Randomised phenomenological noise",
        short_description=(
            "Draws realised priors before freezing each circuit instance."
        ),
        paper_url="https://example.org/papers/randomised-noise",
        randomises_priors=True,
        curation_status="community",
        submitted_by=contributor,
        state="published",
        published_at=published_at,
    )

    decoder_history = _demo_history("decoder/clear-matcher", "decoder")
    decoder_root = DecoderVersion.objects.create(
        id=demo_id("decoder/clear-matcher/0.1"),
        schema_release=releases["decoder"],
        history=decoder_history,
        slug="clear-matcher-0-1",
        name="Clear Matcher",
        version="0.1",
        description="A compact matching decoder used for the demonstration data.",
        revision_description="first revision",
        circuit_skeleton_preparation="not_required",
        circuit_priors_preparation="not_required",
        provides_failure_probability=True,
        hyperparameter_definitions="window: positive integer matching window",
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    decoder = DecoderVersion.objects.create(
        id=demo_id("decoder/clear-matcher/0.2"),
        schema_release=releases["decoder"],
        history=decoder_history,
        slug="clear-matcher-0-2",
        name="Clear Matcher",
        version="0.2",
        predecessor=decoder_root,
        description=None,
        revision_description="Adds calibrated per-shot failure probabilities.",
        circuit_skeleton_preparation="not_required",
        circuit_priors_preparation="not_required",
        provides_failure_probability=True,
        hyperparameter_definitions="window: positive integer matching window",
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    DecoderVersionAlgorithmTag.objects.bulk_create(
        [
            DecoderVersionAlgorithmTag(decoder_version=decoder_root, tag=matching),
            DecoderVersionAlgorithmTag(decoder_version=decoder, tag=matching),
            DecoderVersionAlgorithmTag(
                decoder_version=decoder,
                tag=belief_propagation,
            ),
        ]
    )

    circuit_file = _artifact(
        uploader,
        "circuit/demo-memory.stim",
        "demo-memory.stim",
        "application/vnd.stim+circuit",
        b"R 0\nX_ERROR(0.001) 0\nM 0\nDETECTOR rec[-1]\n",
    )
    dem_file = _artifact(
        uploader,
        "circuit/demo-memory.dem",
        "demo-memory.dem",
        "application/vnd.stim+dem",
        b"error(0.001) D0 L0\n",
    )
    circuit_manifest = _artifact(
        uploader,
        "circuit/demo-memory-manifest.json",
        "demo-memory-manifest.json",
        "application/json",
        b'{"schema":"circuit/0.1","demo":true}\n',
    )
    circuit = CircuitRevision.objects.create(
        id=demo_id("circuit/rotated-memory-d5"),
        schema_release=releases["circuit"],
        history=_demo_history("circuit/rotated-memory-d5", "circuit"),
        slug="rotated-memory-d5",
        name="Rotated surface-code memory d=5",
        description="A small synthetic memory circuit for interface development.",
        revision_description="first revision",
        noise_model=fixed_noise,
        is_css=True,
        code_distance_upper_bound=5,
        circuit_distance_upper_bound=5,
        rounds=5,
        num_detectors=120,
        num_errors=480,
        num_observables=1,
        dem_x_detectors_only=True,
        dem_z_detectors_only=False,
        stim_version="1.15.0",
        dem_decompose_errors=False,
        dem_flatten_loops=False,
        dem_allow_gauge_detectors=False,
        dem_approximate_disjoint_errors=False,
        dem_ignore_decomposition_failures=False,
        dem_block_decomposition_from_introducing_remnant_edges=False,
        sampling_circuit_artifact=circuit_file,
        detector_error_model_artifact=dem_file,
        manifest_artifact=circuit_manifest,
        submitted_by=contributor,
        state="published",
        published_at=published_at,
    )
    CircuitRevisionExperimentTag.objects.create(circuit_revision=circuit, tag=memory)

    machine = Machine.objects.create(
        id=demo_id("machine/demo-cpu"),
        schema_release=releases["machine"],
        history=_demo_history("machine/demo-cpu", "machine"),
        slug="demo-eight-core-cpu",
        machine_class="cpu",
        description="Synthetic eight-core CPU environment for UI development.",
        status="physical",
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    evaluator_bundle = _artifact(
        uploader,
        "evaluator/0.1.tar.gz",
        "circuit-bench-evaluator-0.1.tar.gz",
        "application/gzip",
        b"synthetic evaluator bundle 0.1\n",
    )
    evaluator = EvaluatorRelease.objects.create(
        id=demo_id("evaluator/0.1"),
        schema_release=releases["evaluator"],
        history=_demo_history("evaluator/0.1", "evaluator"),
        version="0.1",
        source_url="https://example.org/circuit-bench/evaluator",
        source_revision="0000000000000000000000000000000000000001",
        source_bundle_artifact=evaluator_bundle,
        input_contract_url="https://example.org/contracts/evaluator-input/0.1",
        summary_contract_url="https://example.org/contracts/evaluator-summary/0.1",
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    brier = ScoreDefinition.objects.create(
        id=demo_id("score/brier-loss-upper-95"),
        evaluator_release=evaluator,
        key="brier-loss-upper-95",
        version="0.1",
        name="Brier loss upper 95% bound",
        description="Provisional test score for calibrated failure probabilities.",
        definition_url="https://example.org/definitions/brier-loss-upper-95/0.1",
        direction="lower_is_better",
        unit="probability",
        primary_value_kind="upper_bound",
        required_inputs={"failure_probability": True, "logical_failure": True},
        parameters={"confidence": "0.95"},
        is_provisional=True,
        display_order=1,
    )
    ler = ScoreDefinition.objects.create(
        id=demo_id("score/ler-upper-95-at-5pct-acceptance"),
        evaluator_release=evaluator,
        key="ler-upper-95-at-5pct-acceptance",
        version="0.1",
        name="LER upper 95% bound at 5% acceptance",
        description="Provisional conditional logical-error score.",
        definition_url="https://example.org/definitions/ler-upper-95-5pct/0.1",
        direction="lower_is_better",
        unit="probability",
        primary_value_kind="upper_bound",
        required_inputs={"failure_probability": True, "logical_failure": True},
        parameters={"confidence": "0.95", "acceptance": "0.05"},
        is_provisional=True,
        display_order=2,
    )
    result = Result.objects.create(
        id=demo_id("result/clear-matcher-rotated-memory"),
        schema_release=releases["result"],
        history=_demo_history("result/clear-matcher-rotated-memory", "result"),
        decoder_version=decoder,
        circuit_revision=circuit,
        evaluator_version=evaluator,
        machine=machine,
        description="Synthetic but arithmetically consistent demonstration result.",
        hyperparameter_values="window=20",
        shots_total=100_000,
        successful_shots=98_800,
        logical_failure_shots=1_000,
        timeout_shots=150,
        decoder_error_shots=50,
        failure_probability_shots=99_800,
        latency_shots=99_800,
        preparation_duration_seconds=Decimal("0.250000000"),
        software_environment="Synthetic development fixture",
        t_1000_ns=25_000_000,
        reproduction_status="decoder_author_verified",
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    ResultScore.objects.bulk_create(
        [
            ResultScore(
                result=result,
                score_definition=brier,
                evaluator_version=evaluator,
                value=Decimal("0.02300000000000000000"),
                point_estimate=Decimal("0.02000000000000000000"),
                lower_bound=Decimal("0.01800000000000000000"),
                upper_bound=Decimal("0.02300000000000000000"),
                confidence_level=Decimal("0.9500000"),
                sample_count=99_800,
                event_count=1_000,
                details={"fixture": True},
            ),
            ResultScore(
                result=result,
                score_definition=ler,
                evaluator_version=evaluator,
                value=Decimal("0.15000000000000000000"),
                point_estimate=Decimal("0.12000000000000000000"),
                lower_bound=Decimal("0.09500000000000000000"),
                upper_bound=Decimal("0.15000000000000000000"),
                confidence_level=Decimal("0.9500000"),
                sample_count=4_990,
                event_count=599,
                details={"acceptance": "0.05", "fixture": True},
            ),
        ]
    )

    benchmark_manifest = _artifact(
        uploader,
        "benchmark/demo-memory-manifest.json",
        "demo-memory-benchmark-manifest.json",
        "application/json",
        b'{"schema":"benchmark/0.1","items":["rotated-memory-d5"]}\n',
    )
    benchmark = BenchmarkRevision.objects.create(
        id=demo_id("benchmark/memory-smoke-test/0.1"),
        schema_release=releases["benchmark"],
        history=_demo_history("benchmark/memory-smoke-test", "benchmark"),
        slug="memory-smoke-test-0-1",
        name="Memory smoke test",
        version="0.1",
        description="A one-circuit benchmark used only for development.",
        revision_description="first revision",
        recognition_status="admin_approved",
        manifest_artifact=benchmark_manifest,
        submitted_by=uploader,
        state="published",
        published_at=published_at,
    )
    BenchmarkRevisionItem.objects.create(
        benchmark_revision=benchmark,
        circuit_revision=circuit,
        position=1,
        is_required=True,
    )
    attempt = BenchmarkAttempt.objects.create(
        id=demo_id("benchmark-attempt/memory-smoke-test/clear-matcher"),
        history=_demo_history(
            "benchmark-attempt/memory-smoke-test/clear-matcher",
            "benchmark_attempt",
        ),
        benchmark_revision=benchmark,
        decoder_version=decoder,
        submitted_by=uploader,
        description="Complete demonstration attempt.",
        state="published",
        published_at=published_at,
    )
    BenchmarkAttemptResult.objects.create(
        benchmark_attempt=attempt,
        circuit_revision=circuit,
        result=result,
    )

    Credit.objects.bulk_create(
        [
            Credit(
                id=demo_id("credit/decoder/uploader"),
                decoder_version=decoder_root,
                position=1,
                account=uploader,
            ),
            Credit(
                id=demo_id("credit/decoder/name"),
                decoder_version=decoder,
                position=1,
                display_name="Example Collaborator",
            ),
            Credit(
                id=demo_id("credit/decoder/uploader-v2"),
                decoder_version=decoder,
                position=2,
                account=uploader,
            ),
            Credit(
                id=demo_id("credit/noise/uploader"),
                noise_model=fixed_noise,
                position=1,
                account=uploader,
            ),
            Credit(
                id=demo_id("credit/circuit/contributor"),
                circuit_revision=circuit,
                position=1,
                account=contributor,
            ),
            Credit(
                id=demo_id("credit/result/uploader"),
                result=result,
                position=1,
                account=uploader,
            ),
            Credit(
                id=demo_id("credit/benchmark/uploader"),
                benchmark_revision=benchmark,
                position=1,
                account=uploader,
            ),
        ]
    )
    ArtifactAttachment.objects.create(
        id=demo_id("attachment/decoder/evaluator-bundle"),
        artifact=evaluator_bundle,
        decoder_version=decoder,
        role="reproduction_bundle",
        position=1,
    )
    ExternalLink.objects.create(
        id=demo_id("link/decoder/source"),
        decoder_version=decoder,
        kind="source",
        url="https://example.org/clear-matcher",
        label="Source repository",
        position=1,
    )
    _ensure_demo_history_events(
        (
            matching,
            belief_propagation,
            bicycle_162,
            memory,
            fixed_noise,
            randomised_noise,
            decoder_root,
            decoder,
            circuit,
            machine,
            evaluator,
            result,
            benchmark,
            attempt,
        )
    )
    _ensure_demo_tag_aliases(uploader)
    reconcile_demo_code_taxonomy()
    from registry.demo_algorithm_taxonomy import reconcile_demo_algorithm_taxonomy

    reconcile_demo_algorithm_taxonomy()

    return demo_counts()


def _ensure_demo_history_events(records) -> None:
    """Give seed records valid histories when they are created after migrations."""

    configurations = {
        Tag: ("tag", None),
        NoiseModel: ("noise_model", "predecessor_id"),
        DecoderVersion: ("decoder", "predecessor_id"),
        CircuitRevision: ("circuit", "predecessor_id"),
        Machine: ("machine", "predecessor_id"),
        EvaluatorRelease: ("evaluator", None),
        Result: ("result", "predecessor_id"),
        BenchmarkRevision: ("benchmark", "predecessor_id"),
        BenchmarkAttempt: ("benchmark_attempt", None),
    }
    for record in records:
        if record.record_events.exists():
            continue
        kind, predecessor_field = configurations[type(record)]
        model = type(record)
        actor = getattr(record, "submitted_by", None)
        predecessor_id = (
            getattr(record, predecessor_field) if predecessor_field else None
        )
        if predecessor_id:
            append_history_event(
                kind=kind,
                record=record,
                actor=actor,
                action="revision_created",
                note="Deterministic development-data revision relationship.",
                details={
                    "fixture": True,
                    "predecessor_id": str(predecessor_id),
                },
            )
        submitted = append_history_event(
            kind=kind,
            record=record,
            actor=actor,
            action="submitted",
            note="Deterministic development-data submission.",
            details={
                "fixture": True,
                "projected_state": getattr(record, "state", None),
            },
            payload_snapshot=submission_snapshot(
                kind,
                {"fixture": True, "record_id": str(record.id)},
            ),
        )
        if getattr(record, "state", None) != "published":
            continue
        approved = append_history_event(
            kind=kind,
            record=record,
            actor_system="demo_seed",
            action="approved",
            note="Approved as deterministic development data.",
            details={
                "fixture": True,
                "approval_route": "deterministic_development_data",
            },
            caused_by=submitted,
        )
        published = append_history_event(
            kind=kind,
            record=record,
            actor_system="demo_seed",
            action="published",
            note="Published as deterministic development data.",
            details={
                "fixture": True,
                "approval_route": "deterministic_development_data",
            },
            caused_by=approved,
        )
        model.objects.filter(id=record.id).update(published_at=published.occurred_at)


def _refresh_demo_presentation() -> None:
    """Keep presentation-only demo metadata current without rebuilding the data set."""
    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": settings.PUBLIC_SITE_HOST, "name": "Circuit Bench"},
    )
    colours = {
        "tag/algorithm/matching": "#315f7d",
        "tag/code/bivariate-bicycle-162": "#526e3d",
        "tag/experiment/memory": "#4f704b",
    }
    for key, display_color in colours.items():
        Tag.objects.filter(id=demo_id(key), status=Tag.Status.OFFICIAL).update(
            display_color=display_color
        )
    Artifact.objects.filter(id=demo_id("artifact/evaluator/0.1.tar.gz")).update(
        original_filename="circuit-bench-evaluator-0.1.tar.gz"
    )
    EvaluatorRelease.objects.filter(id=demo_id("evaluator/0.1")).update(
        source_url="https://example.org/circuit-bench/evaluator"
    )
    uploader = Account.objects.filter(id=DEMO_ACCOUNT_ID).first()
    if uploader is not None:
        _ensure_demo_specific_code_tag(uploader)
        _ensure_demo_tag_aliases(uploader)
        reconcile_demo_code_taxonomy()
        from registry.demo_algorithm_taxonomy import reconcile_demo_algorithm_taxonomy

        reconcile_demo_algorithm_taxonomy()


def _ensure_demo_tag_aliases(uploader: Account) -> None:
    aliases = {
        "tag/code/bivariate-bicycle-162": (
            "162-qubit BB code",
            "BB 162",
        ),
        "tag/experiment/memory": ("Quantum memory",),
    }
    for tag_key, values in aliases.items():
        tag = Tag.objects.filter(id=demo_id(tag_key)).select_related("history").first()
        if tag is None:
            continue
        for alias in values:
            alias_record, created = TagAlias.objects.get_or_create(
                id=demo_id(f"{tag_key}/alias/{alias.casefold()}"),
                defaults={
                    "tag": tag,
                    "alias": alias,
                    "is_active": True,
                    "added_by": uploader,
                },
            )
            if created:
                append_history_event(
                    kind="tag",
                    record=tag,
                    actor=uploader,
                    action="added_alias",
                    note=f"Added the alias “{alias}”.",
                    details={
                        "fixture": True,
                        "alias_id": str(alias_record.id),
                        "alias": alias,
                    },
                )


def _ensure_demo_specific_code_tag(uploader: Account) -> Tag:
    """Keep one genuinely local exact-code term in the demo vocabulary."""

    release = SchemaRelease.objects.get(record_type="tag", version="0.1")
    published_at = timezone.now()
    tag, _created = Tag.objects.get_or_create(
        id=demo_id("tag/code/bivariate-bicycle-162"),
        defaults={
            "schema_release": release,
            "history": _demo_history("tag/code/bivariate-bicycle-162", "tag"),
            "namespace": Tag.Namespace.CODE,
            "slug": "bivariate-bicycle-162",
            "label": "Bivariate bicycle 162",
            "description": (
                "The 162-data-qubit member of a bivariate bicycle-code family. "
                "This member is not currently represented by an ECZ entry."
            ),
            "status": Tag.Status.OFFICIAL,
            "display_color": "#526e3d",
            "submitted_by": uploader,
            "curated_by": uploader,
            "curated_at": published_at,
        },
    )
    _ensure_demo_history_events((tag,))
    return tag


@transaction.atomic
def reconcile_demo_code_taxonomy() -> dict[str, int]:
    """Replace obsolete native demo code tags with exact ECZ memberships."""

    uploader = Account.objects.filter(id=DEMO_ACCOUNT_ID).first()
    if uploader is None:
        return {"retired_native_tags": 0, "ecz_memberships": 0}

    specific_tag = _ensure_demo_specific_code_tag(uploader)
    _ensure_demo_tag_aliases(uploader)
    legacy_ids = [demo_id(f"tag/code/{slug}") for slug in LEGACY_DEMO_CODE_TAG_SLUGS]
    retired = 0
    from registry.services.taxonomy import retire_tag

    for tag in Tag.objects.filter(
        id__in=legacy_ids,
        status__in=(Tag.Status.CUSTOM, Tag.Status.OFFICIAL),
    ).order_by("id"):
        retire_tag(tag.id, actor=uploader)
        retired += 1

    demo_circuit_ids = [demo_id(key) for key in DEMO_CIRCUIT_ECZ_CODES]
    CircuitRevisionCodeTag.objects.filter(
        circuit_revision_id__in=demo_circuit_ids,
        tag_id__in=legacy_ids,
    ).delete()

    current_terms = {
        term.ecz_code_id: term
        for term in EczTerm.objects.filter(
            ecz_code_id__in=set(DEMO_CIRCUIT_ECZ_CODES.values()),
            status=EczTerm.Status.CURRENT,
        )
    }
    memberships = 0
    for circuit_key, code_id in DEMO_CIRCUIT_ECZ_CODES.items():
        term = current_terms.get(code_id)
        if term is None:
            continue
        circuit_id = demo_id(circuit_key)
        if not CircuitRevision.objects.filter(id=circuit_id).exists():
            continue
        _membership, created = CircuitRevisionEczTerm.objects.get_or_create(
            circuit_revision_id=circuit_id,
            ecz_term=term,
        )
        memberships += int(created)

    bb_family = EczTerm.objects.filter(
        ecz_code_id="qcga",
        status=EczTerm.Status.CURRENT,
    ).first()
    if bb_family is not None:
        TagEczParent.objects.get_or_create(tag=specific_tag, ecz_term=bb_family)

    return {"retired_native_tags": retired, "ecz_memberships": memberships}


def demo_counts() -> dict[str, int]:
    return {
        "accounts": Account.objects.count(),
        "artifacts": Artifact.objects.count(),
        "benchmarks": BenchmarkRevision.objects.count(),
        "circuits": CircuitRevision.objects.count(),
        "decoders": DecoderVersion.objects.count(),
        "noise_models": NoiseModel.objects.count(),
        "results": Result.objects.count(),
        "scores": ResultScore.objects.count(),
        "tags": Tag.objects.count(),
    }


def _create_schema_releases(
    uploader: Account,
    frozen_at,
) -> dict[str, SchemaRelease]:
    releases = {}
    for record_type in [
        "decoder",
        "tag",
        "noise_model",
        "circuit",
        "machine",
        "evaluator",
        "result",
        "benchmark",
    ]:
        schema = _artifact(
            uploader,
            f"contracts/{record_type}-0.1.schema.json",
            f"{record_type}-0.1.schema.json",
            "application/schema+json",
            (
                '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
                f'"title":"Synthetic {record_type} 0.1 demo contract"}}\n'
            ).encode(),
        )
        definitions = _artifact(
            uploader,
            f"contracts/{record_type}-0.1.md",
            f"{record_type}-0.1.md",
            "text/markdown",
            (
                f"# Synthetic {record_type} 0.1 definitions\n\n"
                "Development fixture only.\n"
            ).encode(),
        )
        releases[record_type] = SchemaRelease.objects.create(
            id=demo_id(f"schema-release/{record_type}/0.1"),
            record_type=record_type,
            version="0.1",
            json_schema_artifact=schema,
            definitions_artifact=definitions,
            permanent_url=f"https://example.org/schemas/{record_type}/0.1",
            state="frozen",
            frozen_at=frozen_at,
        )
    return releases


def _artifact(
    uploader: Account,
    identity: str,
    filename: str,
    media_type: str,
    content: bytes,
) -> Artifact:
    artifact, _created = store_artifact_chunks(
        [content],
        artifact_id=demo_id(f"artifact/{identity}"),
        uploaded_by=uploader,
        media_type=media_type,
        original_filename=filename,
        max_bytes=max(len(content), 1),
    )
    return artifact
