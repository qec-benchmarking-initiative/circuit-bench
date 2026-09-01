"""Presentation metadata and JSON Schemas for the write-side workflow."""

from dataclasses import dataclass
from typing import Any

from registry.submission_policy import SubmissionKind


@dataclass(frozen=True)
class SubmissionSpec:
    kind: SubmissionKind
    label: str
    plural_label: str
    summary: str


SUBMISSION_SPECS = {
    SubmissionKind.DECODER: SubmissionSpec(
        SubmissionKind.DECODER,
        "decoder version",
        "decoder versions",
        "This form records one versioned decoding algorithm.",
    ),
    SubmissionKind.CIRCUIT: SubmissionSpec(
        SubmissionKind.CIRCUIT,
        "circuit revision",
        "circuit revisions",
        "This form records one circuit revision, its DEM, and its manifest.",
    ),
    SubmissionKind.RESULT: SubmissionSpec(
        SubmissionKind.RESULT,
        "result",
        "results",
        "This form records one decoder–circuit evaluation.",
    ),
    SubmissionKind.MACHINE: SubmissionSpec(
        SubmissionKind.MACHINE,
        "machine",
        "machines",
        "This form records an execution environment used by results.",
    ),
}


UUID = {"type": "string", "format": "uuid"}
NULLABLE_UUID = {"type": ["string", "null"], "format": "uuid"}
NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_NONNEGATIVE = {"type": ["integer", "null"], "minimum": 0}
NULLABLE_POSITIVE = {"type": ["integer", "null"], "minimum": 1}


def _base_schema(kind: SubmissionKind, properties, required) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:circuit-bench:submission:{kind.value}:0.1",
        "title": f"Circuit Bench {SUBMISSION_SPECS[kind].label} submission 0.1",
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": required,
    }


SUBMISSION_SCHEMAS: dict[SubmissionKind, dict[str, Any]] = {
    SubmissionKind.DECODER: _base_schema(
        SubmissionKind.DECODER,
        {
            "slug": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$"},
            "name": {"type": "string", "minLength": 1},
            "version": {"type": "string", "minLength": 1},
            "previous_version": NULLABLE_UUID,
            "description": NULLABLE_STRING,
            "revision_description": {"type": "string", "minLength": 1},
            "circuit_skeleton_preparation": {"enum": ["required", "not_required"]},
            "circuit_priors_preparation": {"enum": ["required", "not_required"]},
            "provides_failure_probability": {"type": "boolean"},
            "hyperparameter_definitions": NULLABLE_STRING,
            "hyperparameter_schema_artifact": NULLABLE_UUID,
            "algorithm_tags": {"type": "array", "items": UUID, "uniqueItems": True},
        },
        [
            "slug",
            "name",
            "version",
            "previous_version",
            "description",
            "revision_description",
            "circuit_skeleton_preparation",
            "circuit_priors_preparation",
            "provides_failure_probability",
            "hyperparameter_definitions",
            "hyperparameter_schema_artifact",
            "algorithm_tags",
        ],
    ),
    SubmissionKind.CIRCUIT: _base_schema(
        SubmissionKind.CIRCUIT,
        {
            "slug": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$"},
            "name": {"type": "string", "minLength": 1},
            "previous_revision": NULLABLE_UUID,
            "description": NULLABLE_STRING,
            "revision_description": {"type": "string", "minLength": 1},
            "noise_model": UUID,
            "is_css": {"type": "boolean"},
            "code_distance_upper_bound": NULLABLE_POSITIVE,
            "circuit_distance_upper_bound": NULLABLE_POSITIVE,
            "rounds": NULLABLE_POSITIVE,
            "num_detectors": {"type": "integer", "minimum": 0},
            "num_errors": {"type": "integer", "minimum": 0},
            "num_observables": {"type": "integer", "minimum": 1},
            "dem_x_detectors_only": {"type": "boolean"},
            "dem_z_detectors_only": {"type": "boolean"},
            "stim_version": {"type": "string", "minLength": 1},
            "dem_decompose_errors": {"type": "boolean"},
            "dem_flatten_loops": {"type": "boolean"},
            "dem_allow_gauge_detectors": {"type": "boolean"},
            "dem_approximate_disjoint_errors": {"type": "boolean"},
            "dem_ignore_decomposition_failures": {"type": "boolean"},
            "dem_block_decomposition_from_introducing_remnant_edges": {
                "type": "boolean"
            },
            "sampling_circuit_artifact": UUID,
            "detector_error_model_artifact": UUID,
            "manifest_artifact": UUID,
            "code_tags": {
                "type": "array",
                "items": UUID,
                "minItems": 1,
                "uniqueItems": True,
            },
            "experiment_tags": {
                "type": "array",
                "items": UUID,
                "minItems": 1,
                "uniqueItems": True,
            },
        },
        [
            "slug",
            "name",
            "previous_revision",
            "description",
            "revision_description",
            "noise_model",
            "is_css",
            "code_distance_upper_bound",
            "circuit_distance_upper_bound",
            "rounds",
            "num_detectors",
            "num_errors",
            "num_observables",
            "dem_x_detectors_only",
            "dem_z_detectors_only",
            "stim_version",
            "dem_decompose_errors",
            "dem_flatten_loops",
            "dem_allow_gauge_detectors",
            "dem_approximate_disjoint_errors",
            "dem_ignore_decomposition_failures",
            "dem_block_decomposition_from_introducing_remnant_edges",
            "sampling_circuit_artifact",
            "detector_error_model_artifact",
            "manifest_artifact",
            "code_tags",
            "experiment_tags",
        ],
    ),
    SubmissionKind.RESULT: _base_schema(
        SubmissionKind.RESULT,
        {
            "decoder_version": UUID,
            "circuit_revision": UUID,
            "evaluator_version": UUID,
            "machine": UUID,
            "description": NULLABLE_STRING,
            "hyperparameter_values": NULLABLE_STRING,
            "hyperparameter_values_artifact": NULLABLE_UUID,
            "shots_total": {"type": "integer", "minimum": 1},
            "successful_shots": {"type": "integer", "minimum": 0},
            "logical_failure_shots": {"type": "integer", "minimum": 0},
            "timeout_shots": {"type": "integer", "minimum": 0},
            "decoder_error_shots": {"type": "integer", "minimum": 0},
            "failure_probability_shots": {"type": "integer", "minimum": 0},
            "latency_shots": {"type": "integer", "minimum": 0},
            "preparation_duration_seconds": {
                "oneOf": [
                    {"type": "number", "minimum": 0},
                    {"type": "string", "pattern": "^(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?$"},
                    {"type": "null"},
                ]
            },
            "training_workload_description": NULLABLE_STRING,
            "software_environment": NULLABLE_STRING,
            "t_1000_ns": NULLABLE_POSITIVE,
            "supersedes_result": NULLABLE_UUID,
            "scores": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "score_definition": UUID,
                        "value": {"type": ["number", "string"]},
                        "point_estimate": {"type": ["number", "string", "null"]},
                        "lower_bound": {"type": ["number", "string", "null"]},
                        "upper_bound": {"type": ["number", "string", "null"]},
                        "confidence_level": {"type": ["number", "string", "null"]},
                        "sample_count": NULLABLE_NONNEGATIVE,
                        "event_count": NULLABLE_NONNEGATIVE,
                        "details": {"type": "object"},
                    },
                    "required": ["score_definition", "value"],
                },
            },
        },
        [
            "decoder_version",
            "circuit_revision",
            "evaluator_version",
            "machine",
            "description",
            "hyperparameter_values",
            "hyperparameter_values_artifact",
            "shots_total",
            "successful_shots",
            "logical_failure_shots",
            "timeout_shots",
            "decoder_error_shots",
            "failure_probability_shots",
            "latency_shots",
            "preparation_duration_seconds",
            "training_workload_description",
            "software_environment",
            "t_1000_ns",
            "supersedes_result",
            "scores",
        ],
    ),
    SubmissionKind.MACHINE: _base_schema(
        SubmissionKind.MACHINE,
        {
            "slug": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$"},
            "machine_class": {"enum": ["cpu", "gpu", "fpga", "asic", "hybrid"]},
            "description": {"type": "string", "minLength": 1},
            "status": {"enum": ["physical", "simulated", "estimated"]},
            "supersedes_machine": NULLABLE_UUID,
        },
        ["slug", "machine_class", "description", "status", "supersedes_machine"],
    ),
}


def get_submission_spec(kind: SubmissionKind | str) -> SubmissionSpec:
    return SUBMISSION_SPECS[SubmissionKind(kind)]


def get_submission_schema(kind: SubmissionKind | str) -> dict[str, Any]:
    return SUBMISSION_SCHEMAS[SubmissionKind(kind)]
