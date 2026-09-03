# Development status — 3 September 2026

Circuit Bench is now a coherent 0.1 staging prototype rather than only a read-only catalogue. The relational scientific records, versioned definitions and schemas, discovery tables, common filtering/query system, plots, provider-only accounts, immutable files, moderation histories, attribution, taxonomy, and demonstration data are all in place.

## Completed in this pass

- Public/private visibility is available across scientific records, tags, benchmarks, machines, and circuit collections. Private records remain visible to their contributor and administrators; official-benchmark dependencies cannot be hidden or withdrawn.
- Contributor and administrator tables share previewed bulk actions for visibility, withdrawal, approval, and rejection. Collection pages separately distinguish collection-page visibility from actions on eligible circuits in the collection tree.
- Circuit collections are user-curated, nestable, acyclic containers with circuit/code classification, editable direct contents, descendant-aware result tables, and the standard filters, query, plot, JSON, and CSV views.
- Circuit batch intake accepts a manifest plus `.stim` files or ZIP files, derives Stim quantities, previews all proposed circuits/tags/collections, and commits independently reviewable circuit revisions.
- Personal, expiring API tokens expose the same validate/commit batch service to scripts and agents. The versioned OpenAPI document and batch JSON Schema are public.
- The API guide is available at `/about/api/` and is automatically listed with the other static reference pages.
- File access, revision lineage, review causation, server-derived result verification, benchmark manifests, and public contract validation have received an integration-hardening pass.
- The newer account, submission, taxonomy, collection, batch, token, and review interfaces now use the established compact forms, tables, pickers, notices, and action styles. Browser review caught and fixed missing CSRF tokens in the reusable bulk-action bars.

## Verification at handoff

- `pytest -q --reuse-db`: 460 passed.
- Ruff: clean.
- Django system check and migration drift check: clean.
- Eight JSON Schema/definition pairs validate.
- 139 record histories, 57 derived result-verification states, 42 tag-parent relationships, and the imported ECZ graph validate.
- Admin and contributor browser passes covered profile/settings, submission, batch upload, review, API tokens, collections, collection membership pickers, empty states, and bulk-action previews.

## Deliberate 0.1 limitations

- Request-changes, edit, reject, withdraw, and successor flows are less complete on the specialised noise-model and benchmark screens than on decoder, circuit, result, and machine screens.
- The HTTP API presently concentrates on circuit-batch validation and commit; it is not yet a general CRUD API.
- Circuit collections have a documented implementation contract but not yet their own frozen public JSON Schema/definition pair.
- Evaluator execution and evaluator-summary ingestion are not implemented. Result records store supplied aggregate evidence; the site does not run decoders or recompute scientific scores.
- Real GitHub/ORCID, Render, and R2 credentials still need an end-to-end staging smoke test, followed by a backup/restore rehearsal before the service carries valuable data.
- Credit-claim decisions still need a dedicated append-only audit log. Notifications and account recovery are also deferred.

## Sensible next work

1. Exercise the deployed staging system end to end: OAuth sign-in, private upload, R2 download authorization, review, publication, API token batch submission, withdrawal, database backup, and restore.
2. Bring specialised noise-model, benchmark-revision, and benchmark-attempt governance up to the common submission lifecycle.
3. Define evaluator/result ingestion precisely, including reproducible execution metadata and the boundary between uploaded aggregates and independently verified values.
4. Freeze a public circuit-collection contract and add read-only collection discovery endpoints to the API.
5. Only after those correctness tasks, revisit broader taxonomy exploration, notifications, and performance/load testing.
