"""Versioned, typed public query contract for exact result records.

This module is deliberately independent of HTTP and presentation.  The HTML
explorer, JSON/CSV endpoints, and plots all compile through the same field
catalogue and query functions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from django.db.models import (
    DecimalField,
    F,
    OrderBy,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.http import QueryDict
from django.utils.dateparse import parse_datetime

from registry.models import Result, ResultScore
from registry.services.results import public_result_catalogue

RESULT_RECORD_SCHEMA_VERSION = "result-record/0.1"
MAX_FILTER_LENGTH = 2_000
MAX_FILTER_NODES = 100
MAX_ORDER_FIELDS = 5
MAX_PAGE_SIZE = 1_000
DEFAULT_PAGE_SIZE = 100

FieldKind = Literal["string", "integer", "decimal", "boolean", "datetime", "uuid"]


@dataclass(frozen=True)
class ResultField:
    """One stable public field and its ORM projection."""

    name: str
    label: str
    kind: FieldKind
    orm_name: str
    unit: str | None = None
    definition: str | None = None
    nullable: bool = False
    sortable: bool = True
    filterable: bool = True
    selectable: bool = True
    direction: str = "not_ranked"
    score_key: str | None = None
    score_version: str | None = None
    evaluator_version: str | None = None

    @property
    def is_metric(self) -> bool:
        return self.score_key is not None


RESULT_FIELDS = (
    ResultField("id", "Result UUID", "uuid", "id"),
    ResultField("decoder_name", "Decoder", "string", "decoder_version__name"),
    ResultField("decoder_slug", "Decoder slug", "string", "decoder_version__slug"),
    ResultField(
        "decoder_version", "Decoder version", "string", "decoder_version__version"
    ),
    ResultField(
        "skeleton_preparation",
        "Circuit-skeleton preparation",
        "string",
        "decoder_version__circuit_skeleton_preparation",
    ),
    ResultField(
        "prior_preparation",
        "Circuit-prior preparation",
        "string",
        "decoder_version__circuit_priors_preparation",
    ),
    ResultField(
        "provides_failure_probability",
        "Failure-probability output",
        "boolean",
        "decoder_version__provides_failure_probability",
    ),
    ResultField("circuit_name", "Circuit", "string", "circuit_revision__name"),
    ResultField("circuit_slug", "Circuit slug", "string", "circuit_revision__slug"),
    ResultField(
        "noise_model",
        "Noise model",
        "string",
        "circuit_revision__noise_model__name",
    ),
    ResultField(
        "noise_model_slug",
        "Noise-model slug",
        "string",
        "circuit_revision__noise_model__slug",
    ),
    ResultField(
        "evaluator_version",
        "Evaluator version",
        "string",
        "evaluator_version__version",
    ),
    ResultField("machine_slug", "Machine", "string", "machine__slug", nullable=True),
    ResultField(
        "machine_class",
        "Machine type",
        "string",
        "machine__machine_class",
        nullable=True,
    ),
    ResultField("shots_total", "Shots", "integer", "shots_total", unit="shots"),
    ResultField(
        "successful_shots",
        "Successful shots",
        "integer",
        "successful_shots",
        unit="shots",
    ),
    ResultField(
        "logical_failure_shots",
        "Logical-failure shots",
        "integer",
        "logical_failure_shots",
        unit="shots",
    ),
    ResultField(
        "timeout_shots", "Timeout shots", "integer", "timeout_shots", unit="shots"
    ),
    ResultField(
        "decoder_error_shots",
        "Decoder-error shots",
        "integer",
        "decoder_error_shots",
        unit="shots",
    ),
    ResultField(
        "failure_probability_shots",
        "Probability-output shots",
        "integer",
        "failure_probability_shots",
        unit="shots",
    ),
    ResultField(
        "latency_shots", "Latency shots", "integer", "latency_shots", unit="shots"
    ),
    ResultField(
        "preparation_duration_seconds",
        "Preparation duration",
        "decimal",
        "preparation_duration_seconds",
        unit="s",
        nullable=True,
        definition="/definitions/result/0.1/#preparation-and-timing",
        direction="lower_is_better",
    ),
    ResultField(
        "t_1000_ns",
        "t₁₀₀₀",
        "integer",
        "t_1000_ns",
        unit="ns",
        nullable=True,
        definition="/definitions/result/0.1/#preparation-and-timing",
        direction="lower_is_better",
    ),
    ResultField(
        "score_brier_loss_upper_95_v0_1",
        "Brier loss upper 95%",
        "decimal",
        "metric_brier_loss_upper_95_v0_1",
        unit="probability",
        nullable=True,
        definition="/definitions/result/0.1/#stored-scores",
        direction="lower_is_better",
        score_key="brier-loss-upper-95",
        score_version="0.1",
        evaluator_version="0.1",
    ),
    ResultField(
        "score_ler_upper_95_at_5pct_acceptance_v0_1",
        "LER upper 95% @ 5% acceptance",
        "decimal",
        "metric_ler_upper_95_at_5pct_acceptance_v0_1",
        unit="probability",
        nullable=True,
        definition="/definitions/result/0.1/#stored-scores",
        direction="lower_is_better",
        score_key="ler-upper-95-at-5pct-acceptance",
        score_version="0.1",
        evaluator_version="0.1",
    ),
    ResultField("reproduction_status", "Reproduction", "string", "reproduction_status"),
    ResultField("published_at", "Published", "datetime", "published_at"),
)

FIELD_BY_NAME = {field.name: field for field in RESULT_FIELDS}
DEFAULT_SELECT = tuple(field.name for field in RESULT_FIELDS if field.selectable)
DEFAULT_ORDER = (("published_at", "desc"),)


class ResultQueryError(ValueError):
    """Stable, user-facing validation error for the public query surface."""

    def __init__(self, code: str, message: str, *, position: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.position = position

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.position is not None:
            error["position"] = self.position
        return error


@dataclass(frozen=True)
class LiteralNode:
    value: Any
    raw: str
    position: int


@dataclass(frozen=True)
class FieldNode:
    field: ResultField
    position: int


@dataclass(frozen=True)
class CompareNode:
    operator: str
    left: FieldNode
    right: LiteralNode


@dataclass(frozen=True)
class LogicNode:
    operator: str
    children: tuple[Any, ...]


@dataclass(frozen=True)
class NotNode:
    child: Any


@dataclass(frozen=True)
class FunctionNode:
    name: str
    field: FieldNode
    argument: LiteralNode


FilterNode = CompareNode | LogicNode | NotNode | FunctionNode


@dataclass(frozen=True)
class ResultQuery:
    filter: FilterNode | None
    order_by: tuple[tuple[str, str], ...]
    select: tuple[str, ...]
    top: int
    skip: int
    include_count: bool
    canonical: str


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    position: int


_TOKEN_RE = re.compile(
    r"\s+|(?P<string>'(?:[^']|'')*')|(?P<number>-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)|(?P<lparen>\()|(?P<rparen>\))|(?P<comma>,)|(?P<invalid>.)"
)


def parse_result_query(query: QueryDict | dict[str, Any]) -> ResultQuery:
    """Parse the supported OData 4.01 query-option subset.

    Supported options are ``$filter``, ``$orderby``, ``$select``, ``$top``,
    ``$skip`` and ``$count``.  Every unsupported system option is rejected.
    """

    values = _normalise_options(query)
    raw_filter = values.get("$filter", "").strip()
    if len(raw_filter) > MAX_FILTER_LENGTH:
        raise ResultQueryError(
            "filter_too_long",
            f"$filter is limited to {MAX_FILTER_LENGTH} characters.",
        )
    filter_node = _FilterParser(raw_filter).parse() if raw_filter else None
    order_by = _parse_orderby(values.get("$orderby", ""))
    select = _parse_select(values.get("$select", ""))
    top = _parse_bounded_integer(
        values.get("$top"), "$top", default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE
    )
    skip = _parse_bounded_integer(values.get("$skip"), "$skip", default=0)
    include_count = _parse_count(values.get("$count"))
    canonical = canonical_query(
        filter_node=filter_node,
        order_by=order_by,
        select=select,
        top=top,
        skip=skip,
        include_count=include_count,
    )
    return ResultQuery(
        filter=filter_node,
        order_by=order_by,
        select=select,
        top=top,
        skip=skip,
        include_count=include_count,
        canonical=canonical,
    )


def execute_result_query(
    query: ResultQuery, *, queryset: QuerySet[Result] | None = None
) -> QuerySet[Result]:
    """Compile a parsed query into safe, whitelisted Django ORM operations."""

    results = queryset if queryset is not None else public_result_catalogue()
    results = annotate_result_metrics(results)
    if query.filter is not None:
        results = results.filter(_compile_filter(query.filter))
    ordering = []
    for field_name, direction in query.order_by:
        field = FIELD_BY_NAME[field_name]
        ordering.append(
            OrderBy(
                F(field.orm_name),
                descending=direction == "desc",
                nulls_last=True,
            )
        )
    if not any(name == "id" for name, _direction in query.order_by):
        ordering.append("id")
    return results.order_by(*ordering)


def page_result_query(queryset: QuerySet[Result], query: ResultQuery) -> list[Result]:
    return list(queryset[query.skip : query.skip + query.top])


def annotate_result_metrics(queryset: QuerySet[Result]) -> QuerySet[Result]:
    annotations = {}
    for field in RESULT_FIELDS:
        if not field.is_metric:
            continue
        score = ResultScore.objects.filter(
            result_id=OuterRef("pk"),
            evaluator_version__version=field.evaluator_version,
            score_definition__key=field.score_key,
            score_definition__version=field.score_version,
        ).values("value")[:1]
        annotations[field.orm_name] = Subquery(
            score,
            output_field=DecimalField(max_digits=38, decimal_places=20),
        )
    return queryset.annotate(**annotations)


def result_record(result: Result, fields: tuple[str, ...]) -> dict[str, Any]:
    """Serialize one projected result using public names, never ORM names."""

    record: dict[str, Any] = {}
    for name in fields:
        field = FIELD_BY_NAME[name]
        value = _resolve_orm_value(result, field.orm_name)
        if isinstance(value, UUID):
            value = str(value)
        elif isinstance(value, Decimal):
            value = str(value)
        elif isinstance(value, datetime):
            value = value.isoformat()
        record[name] = value
    return record


def field_catalogue() -> list[dict[str, Any]]:
    return [
        {
            "name": field.name,
            "label": field.label,
            "type": field.kind,
            "unit": field.unit,
            "definition": field.definition,
            "nullable": field.nullable,
            "filterable": field.filterable,
            "sortable": field.sortable,
            "selectable": field.selectable,
            "direction": field.direction,
        }
        for field in RESULT_FIELDS
    ]


def canonical_query(
    *,
    filter_node: FilterNode | None,
    order_by: tuple[tuple[str, str], ...],
    select: tuple[str, ...],
    top: int,
    skip: int,
    include_count: bool,
) -> str:
    parts = []
    if filter_node is not None:
        parts.append(f"$filter={_render_filter(filter_node)}")
    parts.append(
        "$orderby=" + ",".join(f"{name} {direction}" for name, direction in order_by)
    )
    if select != DEFAULT_SELECT:
        parts.append("$select=" + ",".join(select))
    parts.append(f"$top={top}")
    if skip:
        parts.append(f"$skip={skip}")
    if include_count:
        parts.append("$count=true")
    return "&".join(parts)


def _normalise_options(query: QueryDict | dict[str, Any]) -> dict[str, str]:
    allowed = {"$filter", "$orderby", "$select", "$top", "$skip", "$count"}
    values: dict[str, str] = {}
    if isinstance(query, QueryDict):
        keys = query.keys()
        for key in keys:
            if not key.startswith("$"):
                continue
            canonical_key = key.lower()
            if canonical_key not in allowed:
                raise ResultQueryError(
                    "unsupported_option", f"System query option {key} is not supported."
                )
            option_values = query.getlist(key)
            if len(option_values) != 1 or canonical_key in values:
                raise ResultQueryError(
                    "duplicate_option", f"System query option {key} must appear once."
                )
            values[canonical_key] = option_values[0]
        return values

    for key, value in query.items():
        if not key.startswith("$"):
            continue
        canonical_key = key.lower()
        if canonical_key not in allowed:
            raise ResultQueryError(
                "unsupported_option", f"System query option {key} is not supported."
            )
        if canonical_key in values or isinstance(value, (list, tuple)):
            raise ResultQueryError(
                "duplicate_option", f"System query option {key} must appear once."
            )
        values[canonical_key] = str(value)
    return values


def _parse_orderby(raw: str) -> tuple[tuple[str, str], ...]:
    if not raw.strip():
        return DEFAULT_ORDER
    parsed = []
    seen = set()
    for item in raw.split(","):
        bits = item.strip().split()
        if len(bits) not in {1, 2}:
            raise ResultQueryError(
                "invalid_orderby", f"Invalid $orderby item: {item.strip()}"
            )
        name = bits[0]
        field = FIELD_BY_NAME.get(name)
        if field is None or not field.sortable:
            raise ResultQueryError("unknown_field", f"Unknown sortable field: {name}")
        direction = bits[1].lower() if len(bits) == 2 else "asc"
        if direction not in {"asc", "desc"}:
            raise ResultQueryError(
                "invalid_order_direction", f"Invalid direction for {name}: {direction}"
            )
        if name in seen:
            raise ResultQueryError(
                "duplicate_order_field", f"Duplicate sort field: {name}"
            )
        parsed.append((name, direction))
        seen.add(name)
    if len(parsed) > MAX_ORDER_FIELDS:
        raise ResultQueryError(
            "too_many_order_fields",
            f"At most {MAX_ORDER_FIELDS} sort fields are allowed.",
        )
    return tuple(parsed)


def _parse_select(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return DEFAULT_SELECT
    selected = []
    seen = set()
    for name in (item.strip() for item in raw.split(",")):
        field = FIELD_BY_NAME.get(name)
        if not name or field is None or not field.selectable:
            raise ResultQueryError("unknown_field", f"Unknown selectable field: {name}")
        if name not in seen:
            selected.append(name)
            seen.add(name)
    return tuple(selected)


def _parse_bounded_integer(
    raw: str | None, name: str, *, default: int, maximum: int | None = None
) -> int:
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ResultQueryError(
            "invalid_integer", f"{name} must be an integer."
        ) from exc
    if value < 0:
        raise ResultQueryError("invalid_integer", f"{name} cannot be negative.")
    if maximum is not None and value > maximum:
        raise ResultQueryError(
            "page_size_too_large", f"{name} cannot exceed {maximum}."
        )
    return value


def _parse_count(raw: str | None) -> bool:
    if raw is None or raw == "" or raw.lower() == "false":
        return False
    if raw.lower() == "true":
        return True
    raise ResultQueryError("invalid_count", "$count must be true or false.")


class _FilterParser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = self._tokenise(source)
        self.index = 0
        self.node_count = 0

    def parse(self) -> FilterNode:
        node = self._parse_or()
        token = self._peek()
        if token.kind != "eof":
            self._error("unexpected_token", f"Unexpected token {token.value!r}.", token)
        return node

    def _parse_or(self) -> FilterNode:
        children = [self._parse_and()]
        while self._accept_ident("or"):
            children.append(self._parse_and())
        return (
            children[0]
            if len(children) == 1
            else self._node(LogicNode("or", tuple(children)))
        )

    def _parse_and(self) -> FilterNode:
        children = [self._parse_not()]
        while self._accept_ident("and"):
            children.append(self._parse_not())
        return (
            children[0]
            if len(children) == 1
            else self._node(LogicNode("and", tuple(children)))
        )

    def _parse_not(self) -> FilterNode:
        if self._accept_ident("not"):
            return self._node(NotNode(self._parse_not()))
        return self._parse_primary()

    def _parse_primary(self) -> FilterNode:
        if self._accept("lparen"):
            node = self._parse_or()
            self._expect("rparen", "Expected ')' to close expression.")
            return node
        token = self._expect("ident", "Expected a field or function name.")
        if self._peek().kind == "lparen":
            return self._parse_function(token)
        field = self._field(token)
        operator = self._expect("ident", "Expected a comparison operator.")
        if operator.value.lower() not in {"eq", "ne", "gt", "ge", "lt", "le"}:
            self._error(
                "unsupported_operator",
                f"Unsupported comparison operator {operator.value!r}.",
                operator,
            )
        literal = self._literal(field.field)
        self._validate_comparison(operator.value.lower(), field, literal)
        return self._node(CompareNode(operator.value.lower(), field, literal))

    def _parse_function(self, token: _Token) -> FilterNode:
        name = token.value.lower()
        if name not in {"contains", "startswith", "endswith"}:
            self._error(
                "unsupported_function", f"Unsupported function {token.value!r}.", token
            )
        self._expect("lparen", "Expected '(' after function name.")
        field_token = self._expect("ident", "Expected a field as the first argument.")
        field = self._field(field_token)
        if field.field.kind != "string":
            self._error(
                "type_mismatch", f"{name} requires a string field.", field_token
            )
        self._expect("comma", "Expected ',' between function arguments.")
        argument = self._literal(field.field)
        if argument.value is None:
            self._error("type_mismatch", f"{name} does not accept null.", field_token)
        self._expect("rparen", "Expected ')' after function arguments.")
        return self._node(FunctionNode(name, field, argument))

    def _field(self, token: _Token) -> FieldNode:
        field = FIELD_BY_NAME.get(token.value)
        if field is None or not field.filterable:
            self._error(
                "unknown_field", f"Unknown filterable field: {token.value}", token
            )
        return FieldNode(field, token.position)

    def _literal(self, field: ResultField) -> LiteralNode:
        token = self._peek()
        if token.kind not in {"string", "number", "ident"}:
            self._error("expected_literal", "Expected a literal value.", token)
        self.index += 1
        lower = token.value.lower()
        if token.kind == "ident" and lower == "null":
            return LiteralNode(None, "null", token.position)
        try:
            value = _convert_literal(token, field.kind)
        except (InvalidOperation, ValueError) as exc:
            raise ResultQueryError(
                "type_mismatch",
                f"Value {token.value!r} is not valid for {field.name} ({field.kind}).",
                position=token.position,
            ) from exc
        return LiteralNode(value, token.value, token.position)

    def _validate_comparison(
        self, operator: str, field: FieldNode, literal: LiteralNode
    ) -> None:
        if literal.value is None:
            if operator not in {"eq", "ne"}:
                raise ResultQueryError(
                    "null_comparison",
                    "null can only be compared with eq or ne.",
                    position=literal.position,
                )
            if not field.field.nullable:
                raise ResultQueryError(
                    "nonnullable_field",
                    f"{field.field.name} is never null.",
                    position=field.position,
                )
        if field.field.kind in {"boolean", "uuid"} and operator not in {"eq", "ne"}:
            raise ResultQueryError(
                "unsupported_operator",
                f"{field.field.kind} fields support only eq and ne.",
                position=field.position,
            )

    def _tokenise(self, source: str) -> list[_Token]:
        tokens = []
        for match in _TOKEN_RE.finditer(source):
            if match.group(0).isspace():
                continue
            kind = match.lastgroup or "invalid"
            token = _Token(kind, match.group(0), match.start())
            if kind == "invalid":
                self._error(
                    "invalid_character", f"Invalid character {token.value!r}.", token
                )
            tokens.append(token)
        tokens.append(_Token("eof", "", len(source)))
        return tokens

    def _node(self, node: FilterNode) -> FilterNode:
        self.node_count += 1
        if self.node_count > MAX_FILTER_NODES:
            raise ResultQueryError(
                "filter_too_complex",
                f"$filter is limited to {MAX_FILTER_NODES} expression nodes.",
            )
        return node

    def _peek(self) -> _Token:
        return self.tokens[self.index]

    def _accept(self, kind: str) -> bool:
        if self._peek().kind == kind:
            self.index += 1
            return True
        return False

    def _accept_ident(self, value: str) -> bool:
        token = self._peek()
        if token.kind == "ident" and token.value.lower() == value:
            self.index += 1
            return True
        return False

    def _expect(self, kind: str, message: str) -> _Token:
        token = self._peek()
        if token.kind != kind:
            self._error("unexpected_token", message, token)
        self.index += 1
        return token

    def _error(self, code: str, message: str, token: _Token) -> None:
        raise ResultQueryError(code, message, position=token.position)


def _convert_literal(token: _Token, kind: FieldKind) -> Any:
    if kind == "string":
        if token.kind != "string":
            raise ValueError
        return token.value[1:-1].replace("''", "'")
    if kind == "integer":
        if token.kind != "number" or any(char in token.value for char in ".eE"):
            raise ValueError
        return int(token.value)
    if kind == "decimal":
        if token.kind != "number":
            raise ValueError
        return Decimal(token.value)
    if kind == "boolean":
        if token.kind != "ident" or token.value.lower() not in {"true", "false"}:
            raise ValueError
        return token.value.lower() == "true"
    if kind == "uuid":
        raw = token.value[1:-1] if token.kind == "string" else token.value
        return UUID(raw)
    if kind == "datetime":
        if token.kind != "string":
            raise ValueError
        parsed = parse_datetime(token.value[1:-1])
        if parsed is None:
            raise ValueError
        return parsed
    raise ValueError


def _compile_filter(node: FilterNode) -> Q:
    if isinstance(node, LogicNode):
        compiled = [_compile_filter(child) for child in node.children]
        result = compiled[0]
        for child in compiled[1:]:
            result = result & child if node.operator == "and" else result | child
        return result
    if isinstance(node, NotNode):
        return ~_compile_filter(node.child)
    if isinstance(node, FunctionNode):
        lookup = {
            "contains": "contains",
            "startswith": "startswith",
            "endswith": "endswith",
        }[node.name]
        return Q(**{f"{node.field.field.orm_name}__{lookup}": node.argument.value})
    lookup = {
        "eq": "exact",
        "ne": "exact",
        "gt": "gt",
        "ge": "gte",
        "lt": "lt",
        "le": "lte",
    }[node.operator]
    expression = Q(**{f"{node.left.field.orm_name}__{lookup}": node.right.value})
    return ~expression if node.operator == "ne" else expression


def _render_filter(node: FilterNode, parent_precedence: int = 0) -> str:
    if isinstance(node, CompareNode):
        literal = _render_literal(node.right.value)
        return f"{node.left.field.name} {node.operator} {literal}"
    if isinstance(node, FunctionNode):
        argument = _render_literal(node.argument.value)
        return f"{node.name}({node.field.field.name},{argument})"
    if isinstance(node, NotNode):
        rendered = f"not {_render_filter(node.child, 3)}"
        return f"({rendered})" if parent_precedence > 3 else rendered
    precedence = 1 if node.operator == "or" else 2
    rendered = f" {node.operator} ".join(
        _render_filter(child, precedence) for child in node.children
    )
    return f"({rendered})" if parent_precedence > precedence else rendered


def _render_literal(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, datetime):
        return "'" + value.isoformat() + "'"
    if isinstance(value, UUID):
        return "'" + str(value) + "'"
    return str(value)


def _resolve_orm_value(instance: Any, path: str) -> Any:
    value = instance
    for part in path.split("__"):
        value = getattr(value, part)
        if value is None:
            break
    return value
