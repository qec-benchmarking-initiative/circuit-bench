"""Declarative filter-grid definitions for public registry pages.

The structures in this module describe controls and their current state. They do
not apply predicates; views and read services remain the source of truth for
query behaviour.
"""

from collections.abc import Iterable, Sequence
from typing import Any

from registry.formatting import format_scientific_value

Choice = tuple[str, str]


def choice_cell(
    *,
    key: str,
    label: str,
    name: str,
    value: str,
    choices: Sequence[Choice],
) -> dict[str, Any]:
    normalized_choices = [
        {"value": str(choice_value), "label": str(choice_label)}
        for choice_value, choice_label in choices
    ]
    labels = {choice["value"]: choice["label"] for choice in normalized_choices}
    return {
        "type": "choice",
        "key": key,
        "label": label,
        "name": name,
        "value": value,
        "display_value": labels.get(value, labels.get("", "Any")),
        "filtered": bool(value),
        "choices": normalized_choices,
    }


def range_cell(
    *,
    key: str,
    label: str,
    minimum_name: str,
    maximum_name: str,
    minimum_value: str,
    maximum_value: str,
    values: Iterable[int | None],
    histogram_label: str,
) -> dict[str, Any]:
    minimum_value = str(minimum_value or "")
    maximum_value = str(maximum_value or "")
    minimum_number = _nonnegative_int(minimum_value)
    filtered = (minimum_number is not None and minimum_number > 0) or bool(
        maximum_value
    )
    histogram = _histogram(values)
    return {
        "type": "range",
        "key": key,
        "label": label,
        "minimum_name": minimum_name,
        "maximum_name": maximum_name,
        "minimum_value": minimum_value,
        "maximum_value": maximum_value,
        "display_minimum": (
            format_scientific_value(minimum_number)
            if minimum_number is not None
            else "0"
        ),
        "display_maximum": (
            format_scientific_value(maximum_value) if maximum_value else "∞"
        ),
        "filtered": filtered,
        "histogram_label": histogram_label,
        "histogram": histogram,
    }


def tag_cell(
    *,
    key: str,
    label: str,
    picker_id: str,
    input_name: str,
    tags: Iterable[Any],
    selected_keys: Sequence[str],
    match_name: str,
    match_value: str,
) -> dict[str, Any]:
    selected_keys = tuple(selected_keys)
    return {
        "type": "tags",
        "key": key,
        "label": label,
        "picker_id": picker_id,
        "input_name": input_name,
        "tags": tags,
        "selected_keys": selected_keys,
        "match_name": match_name,
        "match_value": match_value,
        "match_label": "any of" if match_value == "any" else "all of",
        "filtered": bool(selected_keys),
    }


def related_records_cell(
    *,
    key: str,
    label: str,
    picker_id: str,
    picker: dict[str, Any],
) -> dict[str, Any]:
    selected_records = list(picker["selected_records"])
    if selected_records:
        display_value = selected_records[0]["label"]
        if len(selected_records) > 1:
            display_value = f"{display_value} +{len(selected_records) - 1}"
    else:
        display_value = "Any"
    return {
        "type": "related_records",
        "key": key,
        "label": label,
        "picker_id": picker_id,
        "input_name": picker["input_name"],
        "search_url": picker["search_url"],
        "singular_label": picker["singular_label"],
        "plural_label": picker["plural_label"],
        "selected_records": selected_records,
        "display_value": display_value,
        "selection_label": ", ".join(
            record["label"] for record in selected_records
        )
        or "Any",
        "filtered": bool(selected_records),
    }


def filter_grid(
    *,
    grid_id: str,
    title: str,
    cells: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    applied_count = sum(bool(cell["filtered"]) for cell in cells)
    return {
        "id": grid_id,
        "title": title,
        "cells": cells,
        "filtered": applied_count > 0,
        "applied_count": applied_count,
    }


def algorithm_grid(
    *,
    grid_id: str,
    picker_id: str,
    tags: Iterable[Any],
    selected_tags: Sequence[str],
    tag_match: str,
    skeleton: str,
    priors: str,
    probability: str,
    result_minimum: str = "",
    result_maximum: str = "",
    result_values: Iterable[int | None] | None = None,
    tag_name: str = "tag",
    tag_match_name: str = "tag_match",
    skeleton_name: str = "skeleton",
    priors_name: str = "priors",
    probability_name: str = "probability",
) -> dict[str, Any]:
    cells = [
        tag_cell(
            key="algorithm_tags",
            label="Algorithm tags",
            picker_id=picker_id,
            input_name=tag_name,
            tags=tags,
            selected_keys=selected_tags,
            match_name=tag_match_name,
            match_value=tag_match,
        ),
        choice_cell(
            key="skeleton",
            label="Skeleton preparation",
            name=skeleton_name,
            value=skeleton,
            choices=(
                ("", "Any"),
                ("not_required", "Not required"),
                ("required", "Required"),
            ),
        ),
        choice_cell(
            key="priors",
            label="Prior preparation",
            name=priors_name,
            value=priors,
            choices=(
                ("", "Any"),
                ("not_required", "Not required"),
                ("required", "Required"),
            ),
        ),
        choice_cell(
            key="probability",
            label="Failure probability",
            name=probability_name,
            value=probability,
            choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
        ),
    ]
    if result_values is not None:
        cells.append(
            range_cell(
                key="result_count",
                label="Published results",
                minimum_name="result_min",
                maximum_name="result_max",
                minimum_value=result_minimum,
                maximum_value=result_maximum,
                values=result_values,
                histogram_label="Published results per decoder version",
            )
        )
    return filter_grid(
        grid_id=grid_id,
        title="Decoding algorithm filters",
        cells=cells,
    )


def machine_grid(
    *,
    grid_id: str,
    machine_classes: Sequence[Choice],
    selected_machine_class: str,
    machine_class_name: str = "machine_class",
) -> dict[str, Any]:
    choices = [("", "Any"), *machine_classes, ("unreported", "Unreported")]
    return filter_grid(
        grid_id=grid_id,
        title="Machine filters",
        cells=[
            choice_cell(
                key="machine_class",
                label="Machine class",
                name=machine_class_name,
                value=selected_machine_class,
                choices=choices,
            )
        ],
    )


def circuit_grid(
    *,
    grid_id: str,
    code_tags: Iterable[Any],
    selected_code_tags: Sequence[str],
    code_tag_match: str,
    experiment_tags: Iterable[Any],
    selected_experiment_tags: Sequence[str],
    experiment_tag_match: str,
    noise_model_picker: dict[str, Any],
    randomises_priors: str,
    is_css: str,
    raw_values: dict[str, str],
    distributions: dict[str, Iterable[int | None]],
    priors_name: str = "priors",
) -> dict[str, Any]:
    cells = [
        tag_cell(
            key="code_tags",
            label="Code tags",
            picker_id=f"{grid_id}-code-tags",
            input_name="code_tag",
            tags=code_tags,
            selected_keys=selected_code_tags,
            match_name="code_tag_match",
            match_value=code_tag_match,
        ),
        tag_cell(
            key="experiment_tags",
            label="Experiment tags",
            picker_id=f"{grid_id}-experiment-tags",
            input_name="experiment_tag",
            tags=experiment_tags,
            selected_keys=selected_experiment_tags,
            match_name="experiment_tag_match",
            match_value=experiment_tag_match,
        ),
        related_records_cell(
            key="noise_model",
            label="Noise model",
            picker_id=f"{grid_id}-noise-models",
            picker=noise_model_picker,
        ),
        choice_cell(
            key="randomised_priors",
            label="Randomised priors",
            name=priors_name,
            value=randomises_priors,
            choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
        ),
        choice_cell(
            key="css",
            label="CSS",
            name="css",
            value=is_css,
            choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
        ),
    ]
    for key, label, minimum_name, maximum_name, histogram_label in (
        (
            "code_distance",
            "Code distance upper bound",
            "code_d_min",
            "code_d_max",
            "Code-distance upper bounds",
        ),
        (
            "circuit_distance",
            "Circuit distance upper bound",
            "circuit_d_min",
            "circuit_d_max",
            "Circuit-distance upper bounds",
        ),
        (
            "detectors",
            "Detector count",
            "detector_min",
            "detector_max",
            "Detector counts",
        ),
        (
            "errors",
            "Error count",
            "error_min",
            "error_max",
            "Error counts",
        ),
    ):
        cells.append(
            range_cell(
                key=key,
                label=label,
                minimum_name=minimum_name,
                maximum_name=maximum_name,
                minimum_value=raw_values.get(minimum_name, ""),
                maximum_value=raw_values.get(maximum_name, ""),
                values=distributions.get(key, ()),
                histogram_label=histogram_label,
            )
        )
    return filter_grid(grid_id=grid_id, title="Circuit filters", cells=cells)


def noise_model_grid(
    *,
    grid_id: str,
    status: str,
    priors: str,
    circuit_minimum: str,
    circuit_maximum: str,
    circuit_values: Iterable[int | None],
) -> dict[str, Any]:
    return filter_grid(
        grid_id=grid_id,
        title="Noise-model filters",
        cells=[
            choice_cell(
                key="curation",
                label="Curation",
                name="status",
                value=status,
                choices=(
                    ("", "Any"),
                    ("official", "Official"),
                    ("community", "Community"),
                    ("deprecated", "Deprecated"),
                ),
            ),
            choice_cell(
                key="randomised_priors",
                label="Randomised priors",
                name="priors",
                value=priors,
                choices=(("", "Any"), ("yes", "Yes"), ("no", "No")),
            ),
            range_cell(
                key="circuit_count",
                label="Published circuits",
                minimum_name="circuit_min",
                maximum_name="circuit_max",
                minimum_value=circuit_minimum,
                maximum_value=circuit_maximum,
                values=circuit_values,
                histogram_label="Published circuits per noise model",
            ),
        ],
    )


def _histogram(
    values: Iterable[int | None], *, maximum_bins: int = 18
) -> dict[str, Any]:
    clean_values = [int(value) for value in values if value is not None and value >= 0]
    domain_max = max(clean_values, default=1)
    domain_max = max(domain_max, 1)
    bin_count = min(maximum_bins, max(2, domain_max + 1))
    counts = [0] * bin_count
    for value in clean_values:
        index = min(bin_count - 1, int((value / domain_max) * bin_count))
        counts[index] += 1
    return {
        "domain_min": 0,
        "domain_max": domain_max,
        "counts": counts,
    }


def _nonnegative_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
