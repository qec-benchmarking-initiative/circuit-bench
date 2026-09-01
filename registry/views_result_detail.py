"""Public presentation of one exact result record."""

import json

from django.shortcuts import get_object_or_404, render
from django.urls import NoReverseMatch, reverse

from registry.models import Artifact, Result, ResultScore
from registry.services.credits import (
    current_result_author_approval,
    is_exact_decoder_author,
)
from registry.services.result_detail import public_result_detail


def result_detail(request, result_id):
    result = get_object_or_404(public_result_detail(), id=result_id)
    viewer = getattr(request, "user", None)
    can_review_author_status = bool(
        getattr(viewer, "is_authenticated", False)
        and is_exact_decoder_author(viewer, result)
    )
    return render(
        request,
        "results/detail.html",
        {
            "result": result,
            "entity": _entity(result),
            "provenance": _provenance(result),
            "outcomes": _outcomes(result),
            "eligibility": _eligibility(result),
            "execution": _execution(result),
            "score_rows": [_score_row(score) for score in result.display_scores],
            "evaluator": _evaluator(result),
            "can_review_author_status": can_review_author_status,
            "current_author_approval": (
                current_result_author_approval(result, viewer)
                if can_review_author_status
                else None
            ),
            "hyperparameter_artifact_url": _artifact_download_url(
                result.hyperparameter_values_artifact
            ),
            "evaluator_bundle_url": _artifact_download_url(
                result.evaluator_version.source_bundle_artifact
            ),
            "outcome_sum": sum(
                (
                    result.successful_shots,
                    result.logical_failure_shots,
                    result.timeout_shots,
                    result.decoder_error_shots,
                )
            ),
        },
    )


def _entity(result: Result) -> dict[str, object]:
    return {
        "kind": "Exact result",
        "name": f"{result.decoder_version.name} on {result.circuit_revision.name}",
        "version": None,
        "status": result.state,
        "status_label": result.get_state_display(),
        "tags": [],
    }


def _provenance(result: Result) -> list[dict[str, object]]:
    decoder_url = _reverse_or_none("decoders:detail", slug=result.decoder_version.slug)
    circuit_url = _reverse_or_none("circuits:detail", slug=result.circuit_revision.slug)
    machine_url = (
        _reverse_or_none("machines:detail", slug=result.machine.slug)
        if result.machine
        else None
    )
    return [
        {
            "label": "Decoder version",
            "value": f"{result.decoder_version.name} {result.decoder_version.version}",
            "url": decoder_url,
        },
        {
            "label": "Decoder version UUID",
            "value": result.decoder_version_id,
        },
        {
            "label": "Circuit revision",
            "value": result.circuit_revision.name,
            "url": circuit_url,
        },
        {
            "label": "Circuit revision UUID",
            "value": result.circuit_revision_id,
        },
        {
            "label": "Noise model",
            "value": result.circuit_revision.noise_model.name,
            "url": _reverse_or_none(
                "noise-models:detail",
                slug=result.circuit_revision.noise_model.slug,
            ),
        },
        {
            "label": "Evaluator release",
            "value": result.evaluator_version.version,
        },
        {
            "label": "Evaluator release UUID",
            "value": result.evaluator_version_id,
        },
        {
            "label": "Machine",
            "value": result.machine.slug if result.machine else "Not reported",
            "url": machine_url,
        },
        {
            "label": "Machine UUID",
            "value": result.machine_id if result.machine else None,
        },
    ]


def _outcomes(result: Result) -> list[dict[str, object]]:
    return [
        {
            "label": "Successful shots",
            "value": result.successful_shots,
            "numeric": True,
            "number_profile": "count",
        },
        {
            "label": "Logical-failure shots",
            "value": result.logical_failure_shots,
            "numeric": True,
            "number_profile": "count",
        },
        {
            "label": "Timeout shots",
            "value": result.timeout_shots,
            "numeric": True,
            "number_profile": "count",
        },
        {
            "label": "Decoder-error shots",
            "value": result.decoder_error_shots,
            "numeric": True,
            "number_profile": "count",
        },
        {
            "label": "Total shots",
            "value": result.shots_total,
            "numeric": True,
            "number_profile": "count",
        },
    ]


def _eligibility(result: Result) -> list[dict[str, object]]:
    return [
        {
            "label": "Failure-probability eligible shots",
            "value": result.failure_probability_shots,
            "numeric": True,
            "number_profile": "count",
        },
        {
            "label": "Latency eligible shots",
            "value": result.latency_shots,
            "numeric": True,
            "number_profile": "count",
        },
    ]


def _execution(result: Result) -> list[dict[str, object]]:
    machine = result.machine
    return [
        {
            "label": "Preparation duration",
            "value": result.preparation_duration_seconds,
            "numeric": True,
            "number_profile": "duration",
            "unit": "s",
        },
        {
            "label": "t_1000",
            "value": result.t_1000_ns,
            "numeric": True,
            "number_profile": "duration",
            "unit": "ns",
        },
        {
            "label": "Machine class",
            "value": machine.get_machine_class_display() if machine else None,
        },
        {
            "label": "Machine evidence",
            "value": machine.get_status_display() if machine else None,
        },
        {
            "label": "Reproduction status",
            "value": result.get_reproduction_status_display(),
        },
    ]


def _score_row(score: ResultScore) -> dict[str, object]:
    definition = score.score_definition
    return {
        "key": definition.key,
        "name": definition.name,
        "version": definition.version,
        "description": definition.description,
        "definition_url": definition.definition_url,
        "unit": definition.unit,
        "direction": definition.get_direction_display(),
        "primary_value_kind": definition.get_primary_value_kind_display(),
        "provisional": definition.is_provisional,
        "value": score.value,
        "point_estimate": score.point_estimate,
        "lower_bound": score.lower_bound,
        "upper_bound": score.upper_bound,
        "confidence_level": score.confidence_level,
        "sample_count": score.sample_count,
        "event_count": score.event_count,
        "required_inputs": json.dumps(
            definition.required_inputs, sort_keys=True, indent=2
        ),
        "parameters": json.dumps(definition.parameters, sort_keys=True, indent=2),
        "details": json.dumps(score.details, sort_keys=True, indent=2),
    }


def _evaluator(result: Result) -> list[dict[str, object]]:
    evaluator = result.evaluator_version
    return [
        {"label": "Release version", "value": evaluator.version},
        {"label": "Source revision", "value": evaluator.source_revision},
        {"label": "Source", "value": evaluator.source_url, "url": evaluator.source_url},
        {
            "label": "Input contract",
            "value": evaluator.input_contract_url,
            "url": evaluator.input_contract_url,
        },
        {
            "label": "Summary contract",
            "value": evaluator.summary_contract_url,
            "url": evaluator.summary_contract_url,
        },
    ]


def _artifact_download_url(artifact: Artifact | None) -> str | None:
    if artifact is None:
        return None
    return _reverse_or_none("artifacts:download", artifact_id=artifact.id)


def _reverse_or_none(view_name: str, **kwargs: object) -> str | None:
    try:
        return reverse(view_name, kwargs=kwargs)
    except NoReverseMatch:
        return None
