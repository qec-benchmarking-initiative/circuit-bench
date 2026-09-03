---
title: Circuit Bench API
summary: This guide describes programmatic circuit-batch validation and submission.
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

Token permissions are deliberately narrow. Every batch needs `circuits:submit`;
a manifest that creates collections or changes collection membership also needs
`collections:write`, and one that creates tags also needs `tags:write`. Tokens expire, can be revoked from
[Settings](/accounts/), and are never stored in plaintext by Circuit Bench.
