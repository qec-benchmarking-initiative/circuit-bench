"""A larger synthetic development population for result plots and filters."""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from registry.demo import _artifact, _demo_history, demo_id, seed_demo_data
from registry.models import (
    CircuitRevision,
    CircuitRevisionCodeTag,
    CircuitRevisionExperimentTag,
    Credit,
    DecoderVersion,
    DecoderVersionAlgorithmTag,
    EvaluatorRelease,
    Machine,
    NoiseModel,
    Result,
    ResultScore,
    SchemaRelease,
    ScoreDefinition,
    Tag,
)

DECODER_SPECS = (
    {
        "key": "union-find-sprint",
        "slug": "union-find-sprint-0-1",
        "name": "Union-Find Sprint",
        "description": "Synthetic fast union-find decoder for interface development.",
        "tags": ("union-find",),
        "skeleton": "not_required",
        "priors": "not_required",
        "machine": "demo-eight-core-cpu",
        "ler_factor": Decimal("1.15"),
        "time_per_complexity": 2_000_000,
    },
    {
        "key": "sparse-bp-osd",
        "slug": "sparse-bp-osd-0-1",
        "name": "Sparse BP+OSD",
        "description": (
            "Synthetic accuracy-oriented BP+OSD decoder for interface development."
        ),
        "tags": ("belief-propagation", "ordered-statistics"),
        "skeleton": "not_required",
        "priors": "required",
        "machine": "demo-single-gpu",
        "ler_factor": Decimal("0.50"),
        "time_per_complexity": 9_000_000,
    },
    {
        "key": "neural-syndrome",
        "slug": "neural-syndrome-0-1",
        "name": "Neural Syndrome",
        "description": "Synthetic trained neural decoder for interface development.",
        "tags": ("neural-network",),
        "skeleton": "required",
        "priors": "required",
        "machine": "demo-single-gpu",
        "ler_factor": Decimal("0.38"),
        "time_per_complexity": 12_000_000,
    },
    {
        "key": "sweep-cellular",
        "slug": "sweep-cellular-0-1",
        "name": "Sweep Cellular",
        "description": (
            "Synthetic low-latency cellular-automaton decoder for interface "
            "development."
        ),
        "tags": ("cellular-automaton",),
        "skeleton": "not_required",
        "priors": "not_required",
        "machine": "demo-fpga-board",
        "ler_factor": Decimal("1.35"),
        "time_per_complexity": 1_200_000,
    },
    {
        "key": "tensor-trail",
        "slug": "tensor-trail-0-1",
        "name": "Tensor Trail",
        "description": (
            "Synthetic high-accuracy tensor-network decoder for interface development."
        ),
        "tags": ("tensor-network",),
        "skeleton": "required",
        "priors": "required",
        "machine": "demo-single-gpu",
        "ler_factor": Decimal("0.30"),
        "time_per_complexity": 18_000_000,
    },
    {
        "key": "streaming-cluster",
        "slug": "streaming-cluster-0-1",
        "name": "Streaming Cluster",
        "description": "Synthetic streaming cluster decoder for interface development.",
        "tags": ("clustering",),
        "skeleton": "not_required",
        "priors": "not_required",
        "machine": "demo-fpga-board",
        "ler_factor": Decimal("1.60"),
        "time_per_complexity": 750_000,
    },
)

CIRCUIT_SPECS = (
    {
        "key": "rotated-memory-d3",
        "slug": "rotated-memory-d3",
        "name": "Rotated surface-code memory d=3",
        "noise": "fixed-phenomenological",
        "code_tag": "rotated-surface-code",
        "experiment_tag": "memory",
        "is_css": True,
        "distance": 3,
        "rounds": 3,
        "detectors": 48,
        "errors": 170,
        "complexity": 3,
        "ler_base": Decimal("0.28"),
    },
    {
        "key": "rotated-memory-d7",
        "slug": "rotated-memory-d7",
        "name": "Rotated surface-code memory d=7",
        "noise": "randomised-phenomenological",
        "code_tag": "rotated-surface-code",
        "experiment_tag": "memory",
        "is_css": True,
        "distance": 7,
        "rounds": 7,
        "detectors": 336,
        "errors": 1_420,
        "complexity": 8,
        "ler_base": Decimal("0.12"),
    },
    {
        "key": "rotated-memory-d9",
        "slug": "rotated-memory-d9",
        "name": "Rotated surface-code memory d=9",
        "noise": "randomised-phenomenological",
        "code_tag": "rotated-surface-code",
        "experiment_tag": "memory",
        "is_css": True,
        "distance": 9,
        "rounds": 9,
        "detectors": 720,
        "errors": 3_120,
        "complexity": 12,
        "ler_base": Decimal("0.075"),
    },
    {
        "key": "planar-stability-d5",
        "slug": "planar-stability-d5",
        "name": "Planar stability experiment d=5",
        "noise": "fixed-phenomenological",
        "code_tag": "rotated-surface-code",
        "experiment_tag": "stability",
        "is_css": True,
        "distance": 5,
        "rounds": 12,
        "detectors": 260,
        "errors": 960,
        "complexity": 6,
        "ler_base": Decimal("0.16"),
    },
    {
        "key": "colour-memory-d5",
        "slug": "colour-memory-d5",
        "name": "Triangular colour-code memory d=5",
        "noise": "fixed-phenomenological",
        "code_tag": "colour-code",
        "experiment_tag": "memory",
        "is_css": True,
        "distance": 5,
        "rounds": 5,
        "detectors": 288,
        "errors": 1_180,
        "complexity": 9,
        "ler_base": Decimal("0.24"),
    },
    {
        "key": "bicycle-memory-144",
        "slug": "bicycle-memory-144",
        "name": "Bivariate bicycle 144 memory",
        "noise": "randomised-phenomenological",
        "code_tag": "bivariate-bicycle-144",
        "experiment_tag": "memory",
        "is_css": True,
        "distance": 12,
        "rounds": 12,
        "detectors": 1_728,
        "errors": 8_300,
        "complexity": 14,
        "ler_base": Decimal("0.19"),
    },
    {
        "key": "surface-cnot-d3",
        "slug": "surface-cnot-d3",
        "name": "Surface-code logical CNOT d=3",
        "noise": "fixed-phenomenological",
        "code_tag": "rotated-surface-code",
        "experiment_tag": "logical-operation",
        "is_css": True,
        "distance": 3,
        "rounds": 9,
        "detectors": 410,
        "errors": 2_100,
        "complexity": 11,
        "ler_base": Decimal("0.32"),
    },
)


@transaction.atomic
def seed_plot_demo_data() -> dict[str, int]:
    """Add an idempotent, explicitly synthetic matrix to the core demo data."""

    seed_demo_data()
    uploader = _account("account/uploader")
    contributor = _account("account/contributor")
    releases = {
        release.record_type: release
        for release in SchemaRelease.objects.filter(state="frozen")
    }
    fixed_noise = NoiseModel.objects.get(slug="fixed-phenomenological")
    random_noise = NoiseModel.objects.get(slug="randomised-phenomenological")
    noises = {fixed_noise.slug: fixed_noise, random_noise.slug: random_noise}
    evaluator = EvaluatorRelease.objects.get(version="0.1")
    brier = ScoreDefinition.objects.get(
        evaluator_release=evaluator,
        key="brier-loss-upper-95",
        version="0.1",
    )
    ler = ScoreDefinition.objects.get(
        evaluator_release=evaluator,
        key="ler-upper-95-at-5pct-acceptance",
        version="0.1",
    )
    published_at = evaluator.published_at

    tags = _seed_tags(releases["tag"], uploader, published_at)
    machines = _seed_machines(releases["machine"], uploader, published_at)
    decoders = _seed_decoders(releases["decoder"], uploader, published_at, tags)
    circuits = _seed_circuits(
        releases["circuit"], contributor, published_at, tags, noises
    )
    _seed_results(
        releases["result"],
        uploader,
        published_at,
        evaluator,
        brier,
        ler,
        machines,
        decoders,
        circuits,
    )
    return plot_demo_counts()


def plot_demo_counts() -> dict[str, int]:
    return {
        "circuits": CircuitRevision.objects.count(),
        "decoders": DecoderVersion.objects.count(),
        "machines": Machine.objects.count(),
        "results": Result.objects.count(),
        "scores": ResultScore.objects.count(),
        "tags": Tag.objects.count(),
    }


def _account(key):
    from accounts.models import Account

    return Account.objects.get(id=demo_id(key))


def _seed_tags(schema_release, uploader, published_at):
    specifications = (
        ("algorithm", "union-find", "Union find", "#567d46"),
        ("algorithm", "ordered-statistics", "Ordered statistics", "#7f5f9a"),
        ("algorithm", "neural-network", "Neural network", "#9a4f62"),
        ("algorithm", "cellular-automaton", "Cellular automaton", "#387c7a"),
        ("algorithm", "tensor-network", "Tensor network", "#80612e"),
        ("algorithm", "clustering", "Clustering", "#4e6695"),
        ("code", "colour-code", "Colour code", "#8d4771"),
        ("code", "bivariate-bicycle-144", "Bivariate bicycle 144", "#526e3d"),
        ("experiment", "stability", "Stability", "#93622f"),
        ("experiment", "logical-operation", "Logical operation", "#445f91"),
    )
    tags = {tag.slug: tag for tag in Tag.objects.all()}
    for namespace, slug, label, colour in specifications:
        tag, _ = Tag.objects.get_or_create(
            id=demo_id(f"tag/{namespace}/{slug}"),
            defaults={
                "schema_release": schema_release,
                "history": _demo_history(f"tag/{namespace}/{slug}", "tag"),
                "namespace": namespace,
                "slug": slug,
                "label": label,
                "description": f"Synthetic {label.lower()} tag for development data.",
                "status": "official",
                "display_color": colour,
                "submitted_by": uploader,
                "curated_by": uploader,
                "curated_at": published_at,
            },
        )
        tags[tag.slug] = tag
    return tags


def _seed_machines(schema_release, uploader, published_at):
    specifications = (
        (
            "demo-single-gpu",
            "gpu",
            "Synthetic single-GPU workstation for plotting demonstrations.",
            "simulated",
        ),
        (
            "demo-fpga-board",
            "fpga",
            "Synthetic FPGA decoding board for plotting demonstrations.",
            "estimated",
        ),
    )
    machines = {machine.slug: machine for machine in Machine.objects.all()}
    for slug, machine_class, description, status in specifications:
        machine, _ = Machine.objects.get_or_create(
            id=demo_id(f"machine/{slug}"),
            defaults={
                "schema_release": schema_release,
                "history": _demo_history(f"machine/{slug}", "machine"),
                "slug": slug,
                "machine_class": machine_class,
                "description": description,
                "status": status,
                "submitted_by": uploader,
                "state": "published",
                "published_at": published_at,
            },
        )
        machines[machine.slug] = machine
    return machines


def _seed_decoders(schema_release, uploader, published_at, tags):
    clear_matcher = DecoderVersion.objects.get(slug="clear-matcher-0-2")
    decoders = {
        "clear-matcher": {
            "record": clear_matcher,
            "machine": "demo-eight-core-cpu",
            "ler_factor": Decimal("0.75"),
            "time_per_complexity": 5_000_000,
        }
    }
    for spec in DECODER_SPECS:
        decoder, _ = DecoderVersion.objects.get_or_create(
            id=demo_id(f"decoder/{spec['key']}/0.1"),
            defaults={
                "schema_release": schema_release,
                "history": _demo_history(f"decoder/{spec['key']}", "decoder"),
                "slug": spec["slug"],
                "name": spec["name"],
                "version": "0.1",
                "description": spec["description"],
                "revision_description": "Synthetic first revision.",
                "circuit_skeleton_preparation": spec["skeleton"],
                "circuit_priors_preparation": spec["priors"],
                "provides_failure_probability": True,
                "hyperparameter_definitions": (
                    "Synthetic free-text hyperparameters for UI development."
                ),
                "submitted_by": uploader,
                "state": "published",
                "published_at": published_at,
            },
        )
        for tag_slug in spec["tags"]:
            DecoderVersionAlgorithmTag.objects.get_or_create(
                decoder_version=decoder,
                tag=tags[tag_slug],
            )
        Credit.objects.get_or_create(
            id=demo_id(f"credit/decoder/{spec['key']}"),
            defaults={
                "decoder_version": decoder,
                "position": 1,
                "display_name": "Synthetic Decoder Group",
            },
        )
        decoders[spec["key"]] = {
            "record": decoder,
            "machine": spec["machine"],
            "ler_factor": spec["ler_factor"],
            "time_per_complexity": spec["time_per_complexity"],
        }
    return decoders


def _seed_circuits(schema_release, contributor, published_at, tags, noises):
    base = CircuitRevision.objects.get(slug="rotated-memory-d5")
    circuits = {
        "rotated-memory-d5": {
            "record": base,
            "complexity": 5,
            "ler_base": Decimal("0.20"),
        }
    }
    for spec in CIRCUIT_SPECS:
        circuit_id = demo_id(f"circuit/{spec['key']}")
        circuit = CircuitRevision.objects.filter(id=circuit_id).first()
        if circuit is None:
            stimulus = (
                f"# synthetic development circuit: {spec['slug']}\n"
                "R 0\nX_ERROR(0.001) 0\nM 0\nDETECTOR rec[-1]\n"
            ).encode()
            dem = (
                f"# synthetic development DEM: {spec['slug']}\nerror(0.001) D0 L0\n"
            ).encode()
            manifest = (
                f'{{"schema":"circuit/0.1","synthetic":true,"slug":"{spec["slug"]}"}}\n'
            ).encode()
            circuit_artifact = _artifact(
                contributor,
                f"circuit/{spec['slug']}.stim",
                f"{spec['slug']}.stim",
                "application/vnd.stim+circuit",
                stimulus,
            )
            dem_artifact = _artifact(
                contributor,
                f"circuit/{spec['slug']}.dem",
                f"{spec['slug']}.dem",
                "application/vnd.stim+dem",
                dem,
            )
            manifest_artifact = _artifact(
                contributor,
                f"circuit/{spec['slug']}-manifest.json",
                f"{spec['slug']}-manifest.json",
                "application/json",
                manifest,
            )
            circuit = CircuitRevision.objects.create(
                id=circuit_id,
                schema_release=schema_release,
                history=_demo_history(f"circuit/{spec['key']}", "circuit"),
                slug=spec["slug"],
                name=spec["name"],
                description=(
                    "Synthetic circuit used only to exercise Circuit Bench plots "
                    "and filters."
                ),
                revision_description="Synthetic first revision.",
                noise_model=noises[spec["noise"]],
                is_css=spec["is_css"],
                code_distance_upper_bound=spec["distance"],
                circuit_distance_upper_bound=spec["distance"],
                rounds=spec["rounds"],
                num_detectors=spec["detectors"],
                num_errors=spec["errors"],
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
                sampling_circuit_artifact=circuit_artifact,
                detector_error_model_artifact=dem_artifact,
                manifest_artifact=manifest_artifact,
                submitted_by=contributor,
                state="published",
                published_at=published_at,
            )
        CircuitRevisionCodeTag.objects.get_or_create(
            circuit_revision=circuit,
            tag=tags[spec["code_tag"]],
        )
        CircuitRevisionExperimentTag.objects.get_or_create(
            circuit_revision=circuit,
            tag=tags[spec["experiment_tag"]],
        )
        Credit.objects.get_or_create(
            id=demo_id(f"credit/circuit/{spec['key']}"),
            defaults={
                "circuit_revision": circuit,
                "position": 1,
                "display_name": "Synthetic Circuit Group",
            },
        )
        circuits[spec["key"]] = {
            "record": circuit,
            "complexity": spec["complexity"],
            "ler_base": spec["ler_base"],
        }
    return circuits


def _seed_results(
    schema_release,
    uploader,
    published_at,
    evaluator,
    brier_definition,
    ler_definition,
    machines,
    decoders,
    circuits,
):
    missing_timings = {
        ("neural-syndrome", "surface-cnot-d3"),
        ("streaming-cluster", "rotated-memory-d9"),
    }
    for decoder_index, (decoder_key, decoder) in enumerate(decoders.items()):
        for circuit_index, (circuit_key, circuit) in enumerate(circuits.items()):
            result_key = f"result/{decoder_key}/{circuit_key}"
            if decoder_key == "clear-matcher" and circuit_key == "rotated-memory-d5":
                result_id = demo_id("result/clear-matcher-rotated-memory")
                history_key = "result/clear-matcher-rotated-memory"
            else:
                result_id = demo_id(result_key)
                history_key = result_key
            ler_value = _quantise_probability(
                circuit["ler_base"] * decoder["ler_factor"]
            )
            point_estimate = _quantise_probability(ler_value * Decimal("0.80"))
            brier_value = _quantise_probability(
                Decimal("0.008") + ler_value * Decimal("0.10")
            )
            timing = decoder["time_per_complexity"] * circuit["complexity"]
            if (decoder_key, circuit_key) in missing_timings:
                timing = None
            shots_total = 100_000 + circuit_index * 10_000
            timeout_shots = 40 + decoder_index * 15
            decoder_error_shots = 10 + decoder_index * 5
            logical_failure_shots = max(1, int(point_estimate * Decimal("8000")))
            successful_shots = (
                shots_total
                - timeout_shots
                - decoder_error_shots
                - logical_failure_shots
            )
            result, created = Result.objects.get_or_create(
                id=result_id,
                defaults={
                    "schema_release": schema_release,
                    "history": _demo_history(history_key, "result"),
                    "decoder_version": decoder["record"],
                    "circuit_revision": circuit["record"],
                    "evaluator_version": evaluator,
                    "machine": machines[decoder["machine"]],
                    "description": (
                        "Synthetic result used only to exercise Circuit Bench "
                        "plots and filters."
                    ),
                    "hyperparameter_values": "synthetic_fixture=true",
                    "shots_total": shots_total,
                    "successful_shots": successful_shots,
                    "logical_failure_shots": logical_failure_shots,
                    "timeout_shots": timeout_shots,
                    "decoder_error_shots": decoder_error_shots,
                    "failure_probability_shots": (
                        successful_shots + logical_failure_shots
                    ),
                    "latency_shots": (
                        successful_shots + logical_failure_shots if timing else 0
                    ),
                    "preparation_duration_seconds": Decimal("0.250000000"),
                    "software_environment": "Synthetic plotting fixture",
                    "t_1000_ns": timing,
                    "reproduction_status": "decoder_author_verified",
                    "submitted_by": uploader,
                    "state": "published",
                    "published_at": published_at
                    + timedelta(minutes=decoder_index * len(circuits) + circuit_index),
                },
            )
            if not created:
                continue
            sample_count = max(1, shots_total // 20)
            ResultScore.objects.bulk_create(
                [
                    ResultScore(
                        result=result,
                        score_definition=brier_definition,
                        evaluator_version=evaluator,
                        value=brier_value,
                        point_estimate=_quantise_probability(
                            brier_value * Decimal("0.85")
                        ),
                        lower_bound=_quantise_probability(
                            brier_value * Decimal("0.70")
                        ),
                        upper_bound=brier_value,
                        confidence_level=Decimal("0.9500000"),
                        sample_count=successful_shots + logical_failure_shots,
                        event_count=logical_failure_shots,
                        details={"synthetic_plot_fixture": True},
                    ),
                    ResultScore(
                        result=result,
                        score_definition=ler_definition,
                        evaluator_version=evaluator,
                        value=ler_value,
                        point_estimate=point_estimate,
                        lower_bound=_quantise_probability(ler_value * Decimal("0.65")),
                        upper_bound=ler_value,
                        confidence_level=Decimal("0.9500000"),
                        sample_count=sample_count,
                        event_count=max(0, int(point_estimate * sample_count)),
                        details={
                            "acceptance": "0.05",
                            "synthetic_plot_fixture": True,
                        },
                    ),
                ]
            )


def _quantise_probability(value):
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
