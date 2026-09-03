"""Deterministic pending and immediate-publication records for workflow demos."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from accounts.models import Account
from pages.models import DailyQuoteSchedule
from registry.demo import DEMO_ACCOUNT_ID, _demo_history, demo_id, seed_demo_data
from registry.models import (
    BenchmarkAttempt,
    BenchmarkRevision,
    CircuitRevision,
    Credit,
    CreditClaim,
    DecoderVersion,
    Machine,
    NoiseModel,
    RecordEvent,
    Result,
    ResultScore,
    SchemaRelease,
    ScoreDefinition,
    Tag,
)
from registry.services.benchmark_submissions import (
    create_benchmark_attempt,
    create_benchmark_submission,
)
from registry.services.credits import submit_credit_claim
from registry.services.histories import append_history_event, submission_snapshot
from registry.services.taxonomy import submit_noise_model


@transaction.atomic
def seed_submission_demo_data() -> dict[str, int]:
    seed_demo_data()
    DailyQuoteSchedule.objects.get_or_create(pk=1)
    admin = Account.objects.get(id=DEMO_ACCOUNT_ID)
    contributor = Account.objects.get(id=demo_id("account/contributor"))
    releases = {
        item.record_type: item
        for item in SchemaRelease.objects.filter(version="0.1", state="frozen")
    }
    published_at = timezone.now()

    matching = Tag.objects.get(id=demo_id("tag/algorithm/matching"))
    memory = Tag.objects.get(id=demo_id("tag/experiment/memory"))
    base_decoder = DecoderVersion.objects.get(id=demo_id("decoder/clear-matcher/0.2"))
    base_circuit = CircuitRevision.objects.get(id=demo_id("circuit/rotated-memory-d5"))
    base_result = Result.objects.get(id=demo_id("result/clear-matcher-rotated-memory"))

    pending_decoder, created = DecoderVersion.objects.get_or_create(
        id=demo_id("submission/decoder/window-cluster/0.1"),
        defaults={
            "schema_release": releases["decoder"],
            "history": _demo_history("submission/decoder/window-cluster", "decoder"),
            "slug": "window-cluster-0-1",
            "name": "Window Cluster",
            "version": "0.1",
            "description": "Synthetic pending decoder submission for workflow testing.",
            "revision_description": "First submitted version.",
            "circuit_skeleton_preparation": "required",
            "circuit_priors_preparation": "not_required",
            "provides_failure_probability": True,
            "hyperparameter_definitions": "window: positive integer",
            "submitted_by": contributor,
            "state": "pending_review",
        },
    )
    if created:
        pending_decoder.algorithm_tags.add(matching)
        Credit.objects.create(
            id=demo_id("submission/credit/decoder"),
            decoder_version=pending_decoder,
            position=1,
            account=contributor,
        )
        _submitted_event("decoder", pending_decoder, contributor)

    pending_circuit, created = CircuitRevision.objects.get_or_create(
        id=demo_id("submission/circuit/rotated-memory-d7"),
        defaults={
            "schema_release": releases["circuit"],
            "history": _demo_history("submission/circuit/rotated-memory-d7", "circuit"),
            "slug": "rotated-memory-d7-submission",
            "name": "Rotated surface-code memory d=7",
            "description": "Synthetic pending circuit submission for workflow testing.",
            "revision_description": "First submitted revision.",
            "noise_model": base_circuit.noise_model,
            "is_css": True,
            "code_distance_upper_bound": 7,
            "circuit_distance_upper_bound": 7,
            "rounds": 7,
            "num_detectors": 672,
            "num_errors": 2400,
            "num_observables": 1,
            "dem_x_detectors_only": False,
            "dem_z_detectors_only": False,
            "stim_version": base_circuit.stim_version,
            "dem_generation_method": base_circuit.dem_generation_method,
            "dem_decompose_errors": base_circuit.dem_decompose_errors,
            "dem_flatten_loops": base_circuit.dem_flatten_loops,
            "dem_allow_gauge_detectors": base_circuit.dem_allow_gauge_detectors,
            "dem_approximate_disjoint_errors": (
                base_circuit.dem_approximate_disjoint_errors
            ),
            "dem_ignore_decomposition_failures": (
                base_circuit.dem_ignore_decomposition_failures
            ),
            "dem_block_decomposition_from_introducing_remnant_edges": (
                base_circuit.dem_block_decomposition_from_introducing_remnant_edges
            ),
            "sampling_circuit_artifact": base_circuit.sampling_circuit_artifact,
            "detector_error_model_artifact": (
                base_circuit.detector_error_model_artifact
            ),
            "manifest_artifact": base_circuit.manifest_artifact,
            "submitted_by": admin,
            "state": "pending_review",
        },
    )
    if created:
        pending_circuit.ecz_terms.set(base_circuit.ecz_terms.all())
        pending_circuit.experiment_tags.add(memory)
        Credit.objects.create(
            id=demo_id("submission/credit/circuit"),
            circuit_revision=pending_circuit,
            position=1,
            account=admin,
        )
        _submitted_event("circuit", pending_circuit, admin)

    pending_result, created = Result.objects.get_or_create(
        id=demo_id("submission/result/independent-reproduction"),
        defaults={
            "schema_release": releases["result"],
            "history": _demo_history(
                "submission/result/independent-reproduction", "result"
            ),
            "decoder_version": base_decoder,
            "circuit_revision": base_circuit,
            "evaluator_version": base_result.evaluator_version,
            "machine": base_result.machine,
            "description": "Synthetic pending independent reproduction.",
            "shots_total": 10_000,
            "successful_shots": 9_900,
            "logical_failure_shots": 100,
            "timeout_shots": 0,
            "decoder_error_shots": 0,
            "failure_probability_shots": 10_000,
            "latency_shots": 10_000,
            "preparation_duration_seconds": Decimal("0.4"),
            "software_environment": "Synthetic submission fixture",
            "t_1000_ns": 30_000_000,
            "reproduction_status": "independent_reproduction",
            "submitted_by": contributor,
            "state": "pending_review",
        },
    )
    if created:
        definition = ScoreDefinition.objects.get(
            id=demo_id("score/ler-upper-95-at-5pct-acceptance")
        )
        ResultScore.objects.create(
            result=pending_result,
            score_definition=definition,
            evaluator_version=base_result.evaluator_version,
            value=Decimal("0.11"),
            point_estimate=Decimal("0.09"),
            lower_bound=Decimal("0.07"),
            upper_bound=Decimal("0.11"),
            confidence_level=Decimal("0.95"),
            sample_count=500,
            event_count=45,
            details={"fixture": True, "workflow": "pending"},
        )
        Credit.objects.create(
            id=demo_id("submission/credit/result"),
            result=pending_result,
            position=1,
            account=contributor,
        )
        _submitted_event("result", pending_result, contributor)

    machine, created = Machine.objects.get_or_create(
        id=demo_id("submission/machine/simulated-gpu"),
        defaults={
            "schema_release": releases["machine"],
            "history": _demo_history("submission/machine/simulated-gpu", "machine"),
            "slug": "demo-simulated-gpu",
            "machine_class": "gpu",
            "description": "Synthetic immediately-published machine registration.",
            "status": "simulated",
            "submitted_by": contributor,
            "state": "published",
            "published_at": published_at,
        },
    )
    if created:
        submitted = _submitted_event("machine", machine, contributor, immediate=True)
        details = {
            "fixture": True,
            "policy_version": "0.1",
            "approval_route": "immediate_publication",
            "approved_by": "system",
        }
        approved = append_history_event(
            kind="machine",
            record=machine,
            actor_system="submission_policy",
            action=RecordEvent.Action.APPROVED,
            note="Approved automatically under submission policy 0.1.",
            details=details,
            caused_by=submitted,
        )
        published = append_history_event(
            kind="machine",
            record=machine,
            actor_system="submission_policy",
            action=RecordEvent.Action.PUBLISHED,
            note="Published immediately under submission policy 0.1.",
            details=details,
            caused_by=approved,
        )
        Machine.objects.filter(id=machine.id).update(published_at=published.occurred_at)

    if not NoiseModel.objects.filter(slug="community-biased-noise-review").exists():
        submit_noise_model(
            submitter=contributor,
            slug="community-biased-noise-review",
            name="Community biased noise",
            short_description="Synthetic noise-model submission awaiting review.",
            paper_url="https://example.org/papers/community-biased-noise",
            randomises_priors=True,
        )

    if not BenchmarkRevision.objects.filter(
        slug="community-memory-review-0-1"
    ).exists():
        create_benchmark_submission(
            {
                "slug": "community-memory-review-0-1",
                "name": "Community memory review",
                "version": "0.1",
                "previous_revision": None,
                "description": "Synthetic benchmark revision awaiting review.",
                "revision_description": "First submitted revision.",
                "items": [
                    {
                        "circuit_revision": str(base_circuit.id),
                        "required": True,
                    }
                ],
            },
            submitter=contributor,
        )

    published_benchmark = BenchmarkRevision.objects.get(
        id=demo_id("benchmark/memory-smoke-test/0.1")
    )
    attempt_description = "Synthetic benchmark attempt awaiting review."
    if not BenchmarkAttempt.objects.filter(
        benchmark_revision=published_benchmark,
        decoder_version=base_decoder,
        submitted_by=contributor,
        description=attempt_description,
    ).exists():
        create_benchmark_attempt(
            benchmark=published_benchmark,
            decoder=base_decoder,
            result_ids_by_circuit={str(base_circuit.id): str(base_result.id)},
            submitter=contributor,
            description=attempt_description,
        )

    name_credit = Credit.objects.get(id=demo_id("credit/decoder/name"))
    if not CreditClaim.objects.filter(
        name_credit=name_credit,
        claimant_account=contributor,
    ).exists():
        submit_credit_claim(
            name_credit.id,
            claimant=contributor,
            retain_name_credit=True,
        )
    return submission_demo_counts()


def submission_demo_counts() -> dict[str, int]:
    return {
        "pending_decoders": DecoderVersion.objects.filter(
            id=demo_id("submission/decoder/window-cluster/0.1"),
            state="pending_review",
        ).count(),
        "pending_circuits": CircuitRevision.objects.filter(
            id=demo_id("submission/circuit/rotated-memory-d7"),
            state="pending_review",
        ).count(),
        "pending_results": Result.objects.filter(
            id=demo_id("submission/result/independent-reproduction"),
            state="pending_review",
        ).count(),
        "published_machines": Machine.objects.filter(
            id=demo_id("submission/machine/simulated-gpu"),
            state="published",
        ).count(),
        "pending_noise_models": NoiseModel.objects.filter(
            slug="community-biased-noise-review",
            state="pending_review",
        ).count(),
        "pending_benchmarks": BenchmarkRevision.objects.filter(
            slug="community-memory-review-0-1",
            state="pending_review",
        ).count(),
        "pending_benchmark_attempts": BenchmarkAttempt.objects.filter(
            description="Synthetic benchmark attempt awaiting review.",
            state="pending_review",
        ).count(),
        "pending_credit_claims": CreditClaim.objects.filter(
            name_credit_id=demo_id("credit/decoder/name"),
            claimant_account_id=demo_id("account/contributor"),
            state=CreditClaim.State.PENDING,
        ).count(),
    }


def _submitted_event(kind, record, actor, *, immediate=False):
    return append_history_event(
        kind=kind,
        record=record,
        actor=actor,
        action="submitted",
        note="Deterministic workflow demonstration submission.",
        details={
            "fixture": True,
            "policy_version": "0.1",
            "approval_route": (
                "immediate_publication" if immediate else "admin_review"
            ),
            "projected_state": record.state,
        },
        payload_snapshot=submission_snapshot(
            kind,
            {
                "fixture": True,
                "record_id": str(record.id),
            },
        ),
    )
