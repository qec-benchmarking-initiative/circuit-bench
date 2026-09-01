"""Declarative, reusable presentation for structured submission forms."""

from __future__ import annotations

from registry.filter_grids import related_records_cell
from registry.record_pickers import (
    get_picker_spec,
    record_picker_context,
    serialize_picker_record,
)
from registry.submission_policy import SubmissionKind

REFERENCE_PICKERS = {
    "previous_version": "decoder-versions",
    "previous_revision": "circuit-revisions",
    "noise_model": "submission-noise-models",
    "decoder_version": "decoder-versions",
    "circuit_revision": "circuit-revisions",
    "evaluator_version": "evaluator-releases",
    "machine": "machines",
    "supersedes_result": "results",
    "supersedes_machine": "machines",
    "hyperparameter_schema_artifact": "artifacts",
    "sampling_circuit_artifact": "artifacts",
    "detector_error_model_artifact": "artifacts",
    "manifest_artifact": "artifacts",
    "hyperparameter_values_artifact": "artifacts",
}

TAG_FIELDS = {"algorithm_tags", "code_tags", "experiment_tags"}

ARTIFACT_FIELDS = {
    "hyperparameter_schema_artifact",
    "sampling_circuit_artifact",
    "detector_error_model_artifact",
    "manifest_artifact",
    "hyperparameter_values_artifact",
}

CIRCUIT_DEFINITION_LINKS = {
    "is_css": "/definitions/circuit/0.1/#css-and-detector-basis-classification",
    "dem_x_detectors_only": (
        "/definitions/circuit/0.1/#css-and-detector-basis-classification"
    ),
    "dem_z_detectors_only": (
        "/definitions/circuit/0.1/#css-and-detector-basis-classification"
    ),
}

LAYOUTS = {
    SubmissionKind.DECODER: (
        (
            "Identity",
            "Names and permanent URL identity for this exact version.",
            (("stack", ("slug", "name", "version")),),
        ),
        (
            "Revision lineage",
            "Choose the exact predecessor, if this is not the first version.",
            (("stack", ("previous_version",)),),
        ),
        (
            "Scientific description",
            "Describe the decoder and what changed in this exact version.",
            (("stack", ("description", "revision_description")),),
        ),
        (
            "Preparation and output capabilities",
            "These claims apply to the decoder version, not to one benchmark run.",
            (
                (
                    "inline",
                    (
                        "circuit_skeleton_preparation",
                        "circuit_priors_preparation",
                        "provides_failure_probability",
                    ),
                ),
            ),
        ),
        (
            "Algorithmic description",
            (
                "Tags are searchable shared vocabulary; hyperparameters remain "
                "exact prose."
            ),
            (("stack", ("algorithm_tags", "hyperparameter_definitions")),),
        ),
        (
            "Machine-readable hyperparameters",
            "Select an existing frozen schema or upload one now.",
            (("stack", ("hyperparameter_schema_artifact",)),),
        ),
    ),
    SubmissionKind.CIRCUIT: (
        (
            "Identity",
            "Names and permanent URL identity for this exact revision.",
            (("stack", ("slug", "name")),),
        ),
        (
            "Revision lineage and noise model",
            "Both references point to exact registry records.",
            (("stack", ("previous_revision", "noise_model")),),
        ),
        (
            "Scientific description",
            "Describe the circuit and the change represented by this revision.",
            (("stack", ("description", "revision_description")),),
        ),
        (
            "Code and experiment classification",
            "Use the shared coloured tag vocabulary.",
            (("stack", ("code_tags", "experiment_tags")),),
        ),
        (
            "Circuit quantities",
            (
                "Counts are reported in 0.1; a future evaluator will derive and "
                "verify them from frozen artifacts."
            ),
            (
                (
                    "inline",
                    (
                        "code_distance_upper_bound",
                        "circuit_distance_upper_bound",
                        "rounds",
                    ),
                ),
                (
                    "inline",
                    ("num_detectors", "num_errors", "num_observables"),
                ),
                (
                    "inline",
                    (
                        "is_css",
                        "dem_x_detectors_only",
                        "dem_z_detectors_only",
                    ),
                ),
            ),
        ),
        (
            "Stim detector-error-model generation",
            "Arguments passed to Stim to compile the detector error model.",
            (
                ("inline", ("stim_version", "dem_approximate_disjoint_errors")),
                (
                    "inline",
                    (
                        "dem_decompose_errors",
                        "dem_flatten_loops",
                        "dem_allow_gauge_detectors",
                        "dem_ignore_decomposition_failures",
                        "dem_block_decomposition_from_introducing_remnant_edges",
                    ),
                ),
            ),
        ),
        (
            "Frozen artifacts",
            (
                "Uploads are content-addressed immediately; preview and history "
                "retain their immutable UUID and SHA-256 identity."
            ),
            (
                (
                    "stack",
                    (
                        "sampling_circuit_artifact",
                        "detector_error_model_artifact",
                        "manifest_artifact",
                    ),
                ),
            ),
        ),
    ),
    SubmissionKind.RESULT: (
        (
            "Exact scientific references",
            "A result can only reference already-published records.",
            (
                (
                    "stack",
                    (
                        "decoder_version",
                        "circuit_revision",
                        "evaluator_version",
                        "machine",
                    ),
                ),
            ),
        ),
        (
            "Result lineage and status",
            "A successor is a new exact result; its predecessor remains immutable.",
            (("stack", ("supersedes_result", "reproduction_status")),),
        ),
        (
            "Description and hyperparameters",
            "Record free text and, when useful, a small machine-readable values file.",
            (
                (
                    "stack",
                    (
                        "description",
                        "hyperparameter_values",
                        "hyperparameter_values_artifact",
                    ),
                ),
            ),
        ),
        (
            "Shot accounting",
            "The outcome counts must add exactly to total shots.",
            (
                (
                    "inline",
                    ("shots_total", "successful_shots", "logical_failure_shots"),
                ),
                ("inline", ("timeout_shots", "decoder_error_shots")),
                ("inline", ("failure_probability_shots", "latency_shots")),
            ),
        ),
        (
            "Execution and preparation",
            "Timing and workload evidence for this exact run.",
            (
                (
                    "stack",
                    (
                        "t_1000_ns",
                        "preparation_duration_seconds",
                        "training_workload_description",
                        "software_environment",
                    ),
                ),
            ),
        ),
        (
            "Evaluator output",
            (
                "Evaluator scores remain JSON until the evaluator-driven entry UI "
                "is implemented."
            ),
            (("stack", ("scores_json",)),),
        ),
    ),
    SubmissionKind.MACHINE: (
        (
            "Machine identity",
            "Describe the exact hardware or execution environment.",
            (("stack", ("slug", "machine_class", "status", "description")),),
        ),
        (
            "Revision lineage",
            "Choose the exact machine record superseded by this one, if any.",
            (("stack", ("supersedes_machine",)),),
        ),
    ),
}


def submission_form_sections(form, kind: SubmissionKind | str):
    kind = SubmissionKind(kind)
    sections = []
    for section_index, (title, description, groups) in enumerate(LAYOUTS[kind]):
        rendered_groups = []
        for layout, names in groups:
            rendered_groups.append(
                {
                    "layout": layout,
                    "fields": [
                        _field_context(form, name, kind, section_index)
                        for name in names
                    ],
                }
            )
        sections.append(
            {
                "title": title,
                "description": description,
                "groups": rendered_groups,
            }
        )
    return sections


def _field_context(form, name, kind, section_index):
    bound = form[name]
    context = {
        "name": name,
        "bound": bound,
        "required": bound.field.required,
        "disabled": bound.field.disabled,
        "errors": bound.errors,
        "help_text": bound.help_text,
        "type": "standard",
        "definition_url": (
            CIRCUIT_DEFINITION_LINKS.get(name)
            if kind is SubmissionKind.CIRCUIT
            else None
        ),
    }
    if name in REFERENCE_PICKERS:
        values = _bound_values(bound.value())
        picker = record_picker_context(
            REFERENCE_PICKERS[name],
            values,
            input_name=bound.html_name,
        )
        selected = {item["identifier"] for item in picker["selected_records"]}
        missing_values = [value for value in values if value not in selected]
        if missing_values:
            spec = get_picker_spec(REFERENCE_PICKERS[name])
            records = {
                str(record.id): record
                for record in bound.field.queryset.filter(id__in=missing_values)
            }
            picker["selected_records"].extend(
                serialize_picker_record(spec, records[value])
                for value in missing_values
                if value in records
            )
        cell = related_records_cell(
            key=f"submission-{kind.value}-{name}",
            label=bound.label,
            picker_id=f"submission-{kind.value}-{section_index}-{name}",
            picker=picker,
        )
        cell.update(
            {
                "empty_label": "Choose…" if bound.field.required else "None",
                "maximum_selections": 1,
                "required": bound.field.required,
                "disabled": bound.field.disabled,
            }
        )
        if name in ARTIFACT_FIELDS:
            context.update(
                type="artifact",
                picker_cell=cell,
                upload_name=f"upload__{name}",
                upload_limit="1 MiB",
            )
        else:
            context.update(type="reference", picker_cell=cell)
    elif name in TAG_FIELDS:
        tags = list(bound.field.queryset)
        for tag in tags:
            tag.picker_key = str(tag.id)
        context.update(
            type="tags",
            tags=tags,
            selected_keys=tuple(_bound_values(bound.value())),
            picker_id=f"submission-{kind.value}-{section_index}-{name}",
        )
    elif getattr(bound.field.widget, "input_type", None) == "checkbox":
        context["type"] = "boolean"
    return context


def _bound_values(value):
    if value in (None, ""):
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if item not in (None, ""))
    return (str(value),)
