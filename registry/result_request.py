"""Translate reusable result-filter URL controls into service arguments."""

from dataclasses import dataclass

from django.http import QueryDict

from registry.models import Machine
from registry.table_controls import parse_nonnegative_int


@dataclass(frozen=True)
class ResultFilterState:
    service_arguments: dict[str, object]
    raw_ranges: dict[str, str]
    parsed_ranges: dict[str, int | None]


def result_filter_state(parameters: QueryDict) -> ResultFilterState:
    algorithm_tags = _selected(parameters, "algorithm_tag")
    code_tags = _selected(parameters, "code_tag")
    experiment_tags = _selected(parameters, "experiment_tag")
    noise_models = _selected(parameters, "noise_model")
    machine_class = parameters.get("machine_class", "").strip()
    valid_machine_classes = {value for value, _label in Machine.MachineClass.choices}
    if machine_class not in {*valid_machine_classes, "unreported"}:
        machine_class = ""
    raw_ranges = {
        name: parameters.get(name, "")
        for name in (
            "code_d_min",
            "code_d_max",
            "circuit_d_min",
            "circuit_d_max",
            "detector_min",
            "detector_max",
            "error_min",
            "error_max",
        )
    }
    parsed_ranges = {
        name: parse_nonnegative_int(value) for name, value in raw_ranges.items()
    }
    return ResultFilterState(
        service_arguments={
            "query": parameters.get("q", "").strip(),
            "algorithm_tag_slugs": algorithm_tags,
            "algorithm_tag_match": _match(parameters, "algorithm_tag_match"),
            "skeleton_preparation": parameters.get("skeleton", "").strip(),
            "decoder_priors_preparation": parameters.get("decoder_priors", "").strip(),
            "probability_output": parameters.get("probability", "").strip(),
            "code_tag_slugs": code_tags,
            "code_tag_match": _match(parameters, "code_tag_match"),
            "experiment_tag_slugs": experiment_tags,
            "experiment_tag_match": _match(parameters, "experiment_tag_match"),
            "noise_model_slugs": noise_models,
            "randomises_priors": parameters.get("circuit_priors", "").strip(),
            "is_css": parameters.get("css", "").strip(),
            "code_distance_min": parsed_ranges["code_d_min"],
            "code_distance_max": parsed_ranges["code_d_max"],
            "circuit_distance_min": parsed_ranges["circuit_d_min"],
            "circuit_distance_max": parsed_ranges["circuit_d_max"],
            "detector_min": parsed_ranges["detector_min"],
            "detector_max": parsed_ranges["detector_max"],
            "error_min": parsed_ranges["error_min"],
            "error_max": parsed_ranges["error_max"],
            "machine_class": machine_class,
            "circuit_slug": parameters.get("scope_circuit", "").strip(),
            "decoder_slug": parameters.get("scope_decoder", "").strip(),
            "machine_slug": parameters.get("scope_machine", "").strip(),
            "benchmark_slug": parameters.get("scope_benchmark", "").strip(),
        },
        raw_ranges=raw_ranges,
        parsed_ranges=parsed_ranges,
    )


def _selected(parameters: QueryDict, name: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value.strip() for value in parameters.getlist(name) if value.strip()
        )
    )


def _match(parameters: QueryDict, name: str) -> str:
    value = parameters.get(name, "all").strip()
    return value if value in {"all", "any", "children"} else "all"
