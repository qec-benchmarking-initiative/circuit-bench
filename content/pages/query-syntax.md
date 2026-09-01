---
title: ResultRecord query syntax 0.1
summary: This page defines the OData-inspired query subset used by result tables and code.
---

Status: development contract 0.1. Version 1 is reserved for collaborator review and public release.

`ResultRecord` is the public, versioned projection used by the result explorer and data API. It is not the Django database model and it does not expose PostgreSQL column names. Storage migrations may change without changing the meaning of this contract.

The syntax is a documented subset of the [OData 4.01 URL conventions](https://docs.oasis-open.org/odata/odata/v4.01/os/part2-url-conventions/odata-v4.01-os-part2-url-conventions.html).

## System query options

- `$filter` accepts comparisons `eq`, `ne`, `gt`, `ge`, `lt`, and `le`; Boolean operators `and`, `or`, and `not`; parentheses; and the string functions `contains`, `startswith`, and `endswith`.
- `$orderby` accepts comma-separated public field names followed by `asc` or `desc`.
- `$select` chooses the fields returned by the machine-readable response.
- `$top` and `$skip` select a page.
- `$count=true` asks for the full matching count.

Other OData system options are rejected with the error code `unsupported_option`; they are not silently ignored. Query-option names are case-insensitive. Public field names are case-sensitive.

String literals use single quotes. An apostrophe inside a string is doubled: `decoder_name eq 'Alice''s decoder'`.

## Public fields in 0.1

Identity and provenance fields:

- `id`, `decoder_name`, `decoder_slug`, and `decoder_version`
- `skeleton_preparation`, `prior_preparation`, and `provides_failure_probability`
- `circuit_name`, `circuit_slug`, `noise_model`, and `noise_model_slug`
- `evaluator_version`, `machine_slug`, and `machine_class`
- `reproduction_status` and `published_at`

Raw counts and timings:

- `shots_total`, `successful_shots`, `logical_failure_shots`, `timeout_shots`, and `decoder_error_shots`
- `failure_probability_shots` and `latency_shots`
- `preparation_duration_seconds`, measured in seconds and lower-is-better
- `t_1000_ns`, the finite-burst time until the 1,000th correction returns, measured in nanoseconds and lower-is-better

Pinned evaluator metrics:

- `score_brier_loss_upper_95_v0_1` is the primary stored value for score definition `brier-loss-upper-95`, definition version 0.1, under evaluator release 0.1. Its unit is probability and lower is better.
- `score_ler_upper_95_at_5pct_acceptance_v0_1` is the primary stored value for score definition `ler-upper-95-at-5pct-acceptance`, definition version 0.1, under evaluator release 0.1. Its unit is probability and lower is better.

These are not generic “Brier loss” or “LER” fields. If a formula or interpretation changes, the new definition receives a new public field and old results retain the old field.

## Nulls, ordering, and limits

Nullable fields may be compared with `eq null` and `ne null`. Other comparisons with null are invalid, and non-nullable fields reject null comparisons.

Nulls sort last in ascending and descending order. Ordering is made deterministic with an ascending result UUID tie-breaker unless `id` is already explicit. At most five order fields may be supplied.

- `$filter` is limited to 2,000 characters and 100 expression nodes.
- `$top` defaults to 100 and is limited to 1,000.
- `$skip` must be non-negative.
- Public queries contain published results only.

## Examples

Filter and order the public result collection:

```text
$filter=machine_class eq 'cpu' and shots_total ge 100000&$orderby=score_ler_upper_95_at_5pct_acceptance_v0_1 asc,t_1000_ns asc
```

Select a compact response and request its count:

```text
$select=id,decoder_name,circuit_name,score_ler_upper_95_at_5pct_acceptance_v0_1,t_1000_ns&$top=100&$count=true
```

The browser query box accepts the same raw text. It reports either a successful query or a syntax error nearby; it is intentionally not an online IDE.

## Errors and reproducibility

Invalid queries return a stable machine-readable error with a code and message. Filter errors also include a zero-based character position. Query text is parsed into a typed syntax tree and compiled only through whitelisted Django ORM expressions; it is never interpolated into SQL.

Ordinary browser and API queries are live. Repeating a URL later may include newly published matching results. A response records its generation time, canonical query, schema version, count, and exact ordered result UUIDs, but that is not an immutable scientific snapshot. A future snapshot feature must create a frozen snapshot file explicitly.
