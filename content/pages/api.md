---
title: Circuit Bench API
summary: This guide describes programmatic circuit and result batch submission.
---

Circuit Bench exposes the same versioned validation and submission rules to
the website and to programs. Public discovery, schemas, result queries, JSON,
and CSV do not require authentication. Uploading files and changing records
requires a personal API token.

Create a token in [Settings](/accounts/). The token is shown once. Send it in
the HTTP `Authorization` header and never place it in a URL or manifest.

```sh
curl \
  -H "Authorization: Bearer $CIRCUIT_BENCH_TOKEN" \
  -H "Idempotency-Key: family-upload-2026-09" \
  -F manifest=@manifest.json \
  -F files=@distance-3.stim \
  -F files=@distance-5.stim \
  https://circuitbench.org/api/0.1/circuit-batches/validate/
```

Successful validation returns a `batch_id`, a report, and a `commit_url`.
Nothing enters the review queue until that commit URL receives a second POST
with the same bearer token. Repeating an idempotency key returns the same batch.

The [OpenAPI 3.1 document](/api/0.1/openapi.json) describes the HTTP endpoints.
The [circuit-batch JSON Schema](/api/0.1/schemas/circuit-batch.json) describes
the machine-readable envelope. Circuit entries are keyed by exact uploaded
filenames. A manifest can declare new tags and circuit collections using local
references such as `new:surface-family`; the validation response reports those
creations before commit.

Validation errors use a stable JSON form:

```json
{
  "ok": false,
  "errors": [{"path": "circuits/distance-3.stim/noise_model", "message": "..."}]
}
```

Uploaded Stim files are parsed by Stim on the server. Circuit, detector, error,
and observable counts are derived rather than accepted from the manifest. The
detector error model and an ingest manifest containing the exact Stim version,
arguments, and file hashes are generated and frozen at commit.

Token permissions are deliberately narrow. Every circuit batch needs `circuits:submit`;
a manifest that creates collections or changes collection membership also needs
`collections:write`, and one that creates tags also needs `tags:write`. Tokens expire, can be revoked from
[Settings](/accounts/), and are never stored in plaintext by Circuit Bench.

## Result batches

[Upload a batch of results](/submit/result/batch/) using the same validate, preview and submit workflow. Supply individual `.json` result summaries or a zip containing them, plus a manifest. Do not upload per-shot data. Each summary uses the [single-result submission schema](/submit/result/schema.json); fetch the [result-batch schema](/api/0.1/schemas/result-batch.json) for the current required `schema_version`.

```json
{
  "schema": "result-batch/0.1",
  "schema_version": "0.5",
  "defaults": {"visibility": "private"},
  "results": {
    "distance-3.json": {},
    "distance-5.json": {}
  }
}
```

Each filename must match an uploaded JSON file exactly. Zip directories are flattened; duplicate basenames and traversal paths are rejected. The merge order is shared `defaults`, then file contents, then the per-file object in `results` (later values win). Shared decoder, evaluator and machine UUIDs can go in `defaults`; the circuit UUID and measured values normally go in each result file. Arrays such as `scores` are replaced, not concatenated. The effective payload must satisfy exactly the same rules as a single-result submission.

The batch is limited to 200 results, 1 MiB per JSON file or manifest, 16 MiB per uploaded archive and 32 MiB expanded file content. Circuits, decoder versions, evaluators and machines must already be published and accessible to the contributor. Hyperparameter JSON files can be referenced by their existing accessible file UUIDs. Result batches do not create scientific dependencies, tags or collections. Use the single-result revision workflow to supersede an existing result.

Use a token with the **Submit results** (`results:submit`) permission:

```sh
curl -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Idempotency-Key: my-result-batch-001" \
  -F 'manifest=@manifest.json' \
  -F 'files=@results.zip' \
  https://circuitbench.org/api/0.1/result-batches/validate/
```

Inspect the returned preview, then POST to its `commit_url` with the same token. Validation alone creates no result records. Submission revalidates every result and commits all of them or none. Successful results enter the normal approval queue, including submissions by admins. A repeated commit returns the same result IDs instead of duplicating them. An obsolete schema or a reference withdrawn since preview requires a corrected, revalidated batch. Existing tokens do not gain this permission automatically.
