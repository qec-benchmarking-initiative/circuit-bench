# ResultRecord query contract 0.1

Status: implementation contract for the development site. Version 1 remains
reserved for collaborator review and public release.

## Purpose and standard

`ResultRecord` is a public, versioned projection. It is not the Django `Result`
model and does not expose PostgreSQL column names. Storage migrations may change
without changing this contract as long as the projection retains the same
meaning.

Circuit Bench implements a documented subset of the
[OData 4.01 URL conventions](https://docs.oasis-open.org/odata/odata/v4.01/os/part2-url-conventions/odata-v4.01-os-part2-url-conventions.html).
The supported system query options are:

- `$filter` with `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `and`, `or`, `not`,
  parentheses, and `contains`, `startswith`, and `endswith` on strings;
- `$orderby` with `asc` and `desc`;
- `$select`;
- `$top`, `$skip`, and `$count`.

Other OData options are rejected with `unsupported_option`; they are not
silently ignored. Query-option names are case-insensitive. Public field names
are case-sensitive.

## Scientific metric identity

A number is comparable only when its meaning is pinned. Each evaluator-derived
score field therefore fixes all of:

- the evaluator release version;
- the score-definition key and definition version;
- the primary stored value;
- its unit and ranking direction; and
- a permanent human-readable definition link.

For example,
`score_ler_upper_95_at_5pct_acceptance_v0_1` is not a generic “LER” column. It
is the stored primary value belonging to score key
`ler-upper-95-at-5pct-acceptance`, score-definition version `0.1`, under
evaluator release `0.1`. A changed formula or interpretation gets a new public
field; old results retain the old field and new records may contain null there.

`t_1000_ns` is a separately defined raw timing observation: finite-burst time
until the 1,000th correction returns, in nanoseconds. Lower is better. It is not
silently converted into throughput.

The executable field catalogue is `registry.result_query.RESULT_FIELDS`. The
JSON API publishes the same catalogue with every field's type, unit,
nullability, definition URL, and direction.

## Nulls and ordering

Nullable fields may be compared with `eq null` and `ne null`. Other comparisons
with null are invalid. Non-nullable fields reject null comparisons.

Nulls sort last in both ascending and descending order. Every ordering gains a
final ascending result UUID tie-breaker unless UUID is already explicit. A
request may specify at most five order fields.

## Limits and live-query semantics

- `$filter` is limited to 2,000 characters and 100 expression nodes.
- `$top` defaults to 100 and is limited to 1,000.
- `$skip` is non-negative.
- the public query contains published results only.

Ordinary API and browser queries are live: repeating a URL later may include
newly published matching results. The response includes its generation time,
canonical query, count, schema version, and exact ordered result UUIDs. That is
enough to record what was observed, but it is not a frozen scientific snapshot.
A future snapshot feature must mint an immutable artifact and identify it
explicitly; it must not overload the live URL.

## Errors

Invalid queries receive a stable machine-readable error object:

```json
{
  "error": {
    "code": "unknown_field",
    "message": "Unknown filterable field: made_up",
    "position": 0
  }
}
```

`position` is a zero-based character offset within `$filter` and is omitted
when the error concerns another query option. Raw text is parsed into a typed
syntax tree and compiled only through whitelisted Django ORM expressions. Query
text is never interpolated into SQL.

## Examples

```text
$filter=machine_class eq 'cpu' and shots_total ge 100000
&$orderby=score_ler_upper_95_at_5pct_acceptance_v0_1 asc,t_1000_ns asc
&$select=id,decoder_name,circuit_name,score_ler_upper_95_at_5pct_acceptance_v0_1,t_1000_ns
&$top=100
&$count=true
```

String literals use single quotes. A literal apostrophe is doubled, as in
`decoder_name eq 'Alice''s decoder'`.
