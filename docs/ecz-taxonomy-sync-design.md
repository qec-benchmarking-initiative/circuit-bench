# Error Correction Zoo taxonomy synchronisation

Status: draft for review

Version: 0.1

Research snapshot: 2026-09-02

## 1. Purpose

Circuit Bench should be able to use the Error Correction Zoo taxonomy to name
and contextualise codes without attempting to become another source of
truth for code definitions.

The integration is deliberately narrow. Circuit Bench imports only:

- the ECZ code identifier;
- the displayed code name;
- the canonical ECZ page URL; and
- direct parent-child relationships.

Circuit Bench does not import ECZ descriptions, references, features, cousin
relationships, or other scientific content. An ECZ term's Circuit Bench page is
a stub with a prominent link to the corresponding ECZ page. The ECZ remains the
authoritative scientific reference.

The imported data lives in separate read-only tables. In the interface, ECZ
terms behave sufficiently like Circuit Bench code tags to be searchable,
selectable, filterable, and usable in a combined taxonomy graph.

## 2. Decisions

The proposed initial design makes the following decisions.

1. Import every ECZ code and every direct parent relationship. The complete
   dataset is small enough that kingdom- or domain-level import filtering would
   add policy and lifecycle machinery without a practical benefit.
2. Treat every current ECZ code as selectable.
3. Import the exact ECZ data commit used by the latest successful production
   deployment, not the current tip of `main`.
4. Synchronise through one idempotent Django management command.
5. Run that command daily through a Render cron service.
6. Test the same command locally with small deterministic source fixtures; do
   not install or emulate a cron daemon locally.
7. Preserve terms that disappear upstream so existing Circuit Bench records
   never lose their meaning.
8. Never infer an ECZ identifier rename or merge automatically.
9. Represent a Circuit Bench-to-ECZ merge as a reversible, audited equivalence
   mapping. Do not rewrite or delete existing Circuit Bench memberships.
10. Permit Circuit Bench code tags to have ECZ terms as parents. Do not permit
    an ECZ term to have a Circuit Bench parent.
11. Render ECZ terms in blue with a dashed outline and a visible `(ECZ)` source
    suffix.
12. Replace the current all-options-in-the-DOM picker with a small server-backed
    search result, independently counted and paginated by source.

## 3. Source research

### 3.1 Structured-data source

The authoritative structured data repository is:

<https://github.com/errorcorrectionzoo/eczoo_data>

Its default branch is `main`. The repository describes itself as the ECZ
content in structured YAML form and stores one YAML file per code. The active
site generator is a separate repository:

<https://github.com/errorcorrectionzoo/eczoo_sitegen>

The site-generator architecture documents the following data flow:

1. load the `eczoo_data` YAML;
2. validate it against the ECZ schemas;
3. resolve relations and process FLM markup; and
4. generate the static public website.

Relevant sources:

- <https://github.com/errorcorrectionzoo/eczoo_data>
- <https://github.com/errorcorrectionzoo/eczoo_sitegen/blob/main/docs/architecture.md>
- <https://github.com/errorcorrectionzoo/eczoo_sitegen/blob/main/eczoodb/schemas/code.yml>

The ECZ code schema makes `code_id` its primary identifier. Direct parents are
stored under `relations.parents`; the reverse `parent_of` relationship is
generated. Cousins are a separate explicit relation. Circuit Bench will read
only the parent relationship.

### 3.2 Published-data source

The repository's production workflow is:

<https://github.com/errorcorrectionzoo/eczoo_data/blob/main/.github/workflows/build-and-deploy-site.yml>

As inspected on 2026-09-02, production deployment was manually triggered with
`workflow_dispatch`. The workflow's push-to-`main` trigger was commented out.
Consequently, `main` can be ahead of the public site.

The latest successful production deployment found during this research was:

- workflow run: <https://github.com/errorcorrectionzoo/eczoo_data/actions/runs/33214888722>
- data commit:
  <https://github.com/errorcorrectionzoo/eczoo_data/commit/f7d89f07a825686e1c23d5fb4cbeacd968d9b9d1>
- run start: 2026-08-28 21:58:54 UTC;
- run completion: 2026-08-28 22:34:31 UTC.

At the time of inspection, the public surface-code page returned a
`Last-Modified` value of 2026-08-28 22:34:16 UTC, matching that deployment to
within seconds:

<https://errorcorrectionzoo.org/c/surface>

This is strong evidence, but still an inference, that the latest successful
production workflow's `head_sha` identifies the data visible on the public ECZ
site.

Circuit Bench should therefore distinguish:

- **structured-data authority:** the `eczoo_data` repository; and
- **published-data authority:** the commit used by the latest successful
  production deployment.

The production synchroniser should use the latter. It must not silently fall
back to `main`, because doing so could create links to ECZ pages that have not
yet been published.

### 3.3 Activity and change history

An API inspection of the previous year of `main` history found approximately:

- 1,239 commits;
- 216 active commit days;
- a median of three commits per active day;
- 124 merge commits;
- 100 successful production-deployment runs; and
- 17 failed production-deployment runs.

The exact counts are a dated research measurement, not an invariant on which
application behaviour should depend. They show that the repository is active
and that Circuit Bench should select only successful deployment runs.

Historical snapshot comparisons found:

| Snapshot | ECZ codes | Parent edges |
| --- | ---: | ---: |
| 2024-09-01 | 897 | 1,608 |
| 2025-09-01 | 1,001 | 1,845 |
| 2026-08-28 deployed commit | 1,142 | 2,098 |

Between the 2025 and 2026 samples, existing labels and hundreds of parent edges
changed. Two global code identifiers disappeared. One illustrative case was
`golden_code`, followed by a new `golden` identifier with the same displayed
name. This demonstrates that ECZ identifiers are highly stable but must not be
treated as permanently immutable.

The synchroniser therefore needs explicit retirement, diff reporting, and a
human review path for possible replacements.

### 3.4 Current projected size

The deployed commit `f7d89f07a825686e1c23d5fb4cbeacd968d9b9d1` was parsed
directly during this research.

| Imported dataset | Terms | Parent edges |
| --- | ---: | ---: |
| Entire ECZ taxonomy | 1,142 | 2,098 |

Additional measurements:

- compressed repository archive: 2,156,473 bytes;
- source YAML for code entries: 3,445,132 bytes;
- projected JSON containing IDs, names and parents: 112,289 bytes;
- gzip-compressed projection: 21,052 bytes;
- dangling parent references: zero;
- cycles: zero.

The complete projected taxonomy is tiny. PostgreSQL is sufficient for storage,
search and graph traversal. No search service or graph database is justified.

### 3.5 Licensing

The `eczoo_data` repository is licensed under Creative Commons
Attribution-ShareAlike 4.0:

<https://github.com/errorcorrectionzoo/eczoo_data/blob/main/LICENSE.txt>

The imported projection must therefore carry clear attribution, link to the
source commit and licence, identify Circuit Bench's transformation, and make
the derived ECZ projection available under compatible terms. This applies to
the imported taxonomy data; it does not require unrelated Circuit Bench source
code to be described as ECZ data.

The exact attribution language should be confirmed with the ECZ team before a
public release.

## 4. Import projection

Circuit Bench imports every code entry. It does not interpret ECZ domains,
kingdoms or lists to decide whether a code is useful enough to include. That
classification is ECZ's concern and is unnecessary for a dataset of this size.

The projection algorithm is:

1. Parse every code's ID, name and direct parents.
2. Validate every parent against the complete code-ID set.
3. Validate the complete parent graph.
4. Import every term and edge.

A term previously stored by Circuit Bench remains in the local identity table
if it later disappears from ECZ.

## 5. Relational model

ECZ records must not be placed in the existing `tag` table. They have a
different authority, lifecycle and edit policy.

### 5.1 `ecz_sync_run`

One row records every attempted synchronisation.

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | UUID PK | Exact run |
| `started_at` | timestamp | Attempt start |
| `finished_at` | nullable timestamp | Attempt completion |
| `status` | enum | `applied`, `no_change`, `rejected`, or `failed` |
| `source_repository` | text | Canonical ECZ data repository |
| `source_commit` | nullable 40-character text | Resolved immutable revision |
| `workflow_run_id` | nullable integer | Production workflow run |
| `workflow_run_url` | nullable URL | Provenance link |
| `archive_sha256` | nullable 64-character text | Exact downloaded archive |
| `previous_source_commit` | nullable text | Previous applied source |
| `terms_added` | integer | Diff summary |
| `terms_retired` | integer | Diff summary |
| `names_changed` | integer | Diff summary |
| `parent_edges_added` | integer | Diff summary |
| `parent_edges_removed` | integer | Diff summary |
| `terms_restored` | integer | Previously retired IDs present again |
| `diagnostics` | JSON | Structured warnings, errors and detailed diff |

`source_commit` should be unique among applied and no-change runs as
appropriate. Repeated daily observation of the same commit need not create an
unbounded number of duplicate success rows; `last_checked_at` can instead be
updated on the applied run or on a small singleton state record.

### 5.2 `ecz_term`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | UUID PK | Stable Circuit Bench identity |
| `ecz_code_id` | text, unique | ECZ primary identifier |
| `raw_name` | text | Exact FLM-bearing source value |
| `display_name` | text | Safe rendered or normalised display value |
| `status` | enum | `current` or `retired` |
| `first_seen_run_id` | FK | First imported occurrence |
| `last_seen_run_id` | FK | Most recent imported occurrence |
| `created_at` | timestamp | Local record creation |
| `updated_at` | timestamp | Current projection update |

The ECZ page URL is deterministically derived from `ecz_code_id`:

```text
https://errorcorrectionzoo.org/c/<ecz_code_id>
```

A derived URL is preferable to a mutable URL column unless ECZ later supplies
canonical URLs that do not follow this rule.

### 5.3 `ecz_parent`

| Field | Type | Purpose |
| --- | --- | --- |
| `child_id` | FK to `ecz_term` | More specific code |
| `parent_id` | FK to `ecz_term` | Direct ECZ parent |

The pair is the composite primary key or has an equivalent unique constraint.
Self-parent relationships are forbidden. This table represents the current
successfully imported ECZ graph.

Historical upstream states remain reconstructible from the recorded Git commit.
Circuit Bench does not need to duplicate the entire ECZ Git history in
PostgreSQL.

### 5.4 `circuit_revision_ecz_term`

This table allows a circuit revision to be assigned directly to an ECZ code.

| Field | Type |
| --- | --- |
| `circuit_revision_id` | FK |
| `ecz_term_id` | FK |

The pair is unique. New assignments require a current ECZ term.
An existing assignment remains valid if the term is later retired.

### 5.5 `tag_ecz_parent`

This table permits a native Circuit Bench code tag to specialise an ECZ term.

| Field | Type |
| --- | --- |
| `tag_id` | FK to `tag` |
| `ecz_term_id` | FK to `ecz_term` |

Only tags in the `code` namespace may appear here. For example, a Circuit Bench
tag describing a circuit-specific variation may use an ECZ code as its parent.

### 5.6 `tag_ecz_mapping`

This is the non-destructive merge/demerge mechanism.

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | UUID PK | Mapping episode |
| `tag_id` | FK | Circuit Bench code tag |
| `ecz_term_id` | FK | Equivalent ECZ term |
| `status` | enum | `active` or `revoked` |
| `mapped_by_id` | account FK | Curator who merged it |
| `mapped_at` | timestamp | Merge time |
| `mapping_note` | text | Rationale |
| `revoked_by_id` | nullable account FK | Curator who demerged it |
| `revoked_at` | nullable timestamp | Demerge time |
| `revocation_note` | nullable text | Correction rationale |

There may be at most one active ECZ mapping for a Circuit Bench tag. Historical
mapping episodes are retained.

An active mapping changes read-side canonicalisation only:

- existing circuit-to-Circuit-Bench-tag rows are preserved;
- the ECZ term appears as their canonical searchable identity;
- the native tag is normally hidden from new selection to prevent duplication;
- its stable page remains available and shows the mapping; and
- demerging restores native presentation without a data migration.

Possible mappings based on names or aliases may be offered to administrators,
but must never be activated automatically.

## 6. Graph invariants

The effective taxonomy comprises:

- ECZ-to-ECZ parent edges;
- Circuit-Bench-to-Circuit-Bench parent edges;
- Circuit-Bench-to-ECZ parent edges; and
- active equivalence mappings used during canonicalisation.

The following rules apply:

1. ECZ terms are read-only and cannot acquire Circuit Bench parents.
2. Only Circuit Bench code tags may have ECZ parents.
3. Every imported ECZ source must be an acyclic graph.
4. The native Circuit Bench tag graph must remain acyclic.
5. Creating or editing a cross-parent edge must preserve effective acyclicity.
6. Activating an equivalence mapping must rerun acyclicity after substituting
   the mapped ECZ identity.

Without equivalence collapse, one-way Circuit-Bench-to-ECZ edges cannot make a
cycle across the boundary. A mapping can turn such an edge into an effective
ECZ-to-ECZ edge, so mapping validation remains necessary.

## 7. Synchronisation service

### 7.1 Public command

The application exposes one management command:

```bash
python manage.py sync_ecz_taxonomy
python manage.py sync_ecz_taxonomy --dry-run
python manage.py sync_ecz_taxonomy --ref <commit-sha>
python manage.py sync_ecz_taxonomy --source-dir <fixture-directory>
```

Suggested mutually exclusive source modes are:

- `deployed`, the production default;
- `--ref`, an explicitly pinned Git revision for research or staging; and
- `--source-dir`, a local ECZ-shaped fixture tree.

`--dry-run` performs resolution, fetching, parsing, validation and diffing but
does not mutate imported taxonomy tables.

### 7.2 Internal stages

The command should be a thin wrapper around independently testable services:

```text
resolve_source()
    -> SourceRevision

fetch_archive(SourceRevision)
    -> ArchiveBytes

parse_projection(ArchiveBytes | SourceDirectory)
    -> ECZProjection

validate_projection(ECZProjection)
    -> ValidatedProjection

diff_projection(ValidatedProjection, CurrentProjection)
    -> ProjectionDiff

apply_projection(ValidatedProjection, ProjectionDiff)
    -> AppliedRun
```

Network retrieval and parsing happen before opening the database write
transaction. The completely validated projection is applied atomically.

### 7.3 Deployed-source resolution

Until ECZ publishes a version manifest, resolve the source through the GitHub
Actions API by requesting the latest completed, successful run of:

```text
errorcorrectionzoo/eczoo_data/.github/workflows/build-and-deploy-site.yml
```

Capture at least:

- workflow run ID;
- workflow run URL;
- `head_sha`;
- start and completion timestamps; and
- conclusion.

Validate `head_sha` as a complete hexadecimal Git SHA before constructing the
archive URL. Fetch the archive from GitHub's immutable codeload endpoint.

GitHub API failure or rate limiting must result in a failed no-change run. It
must not cause a fallback to `main`. An optional narrowly scoped GitHub token
may be supplied for reliability, but no token is required for the normal public
archive download.

### 7.4 Parsing

Use Python's standard `urllib`, `tarfile`, `hashlib` and related libraries plus
PyYAML. Add PyYAML as an explicit application dependency rather than relying on
an incidental system installation.

Use a subclass of `yaml.SafeLoader` that rejects duplicate mapping keys.
Duplicate keys otherwise risk silently changing scientific identities or
relationships.

The archive reader must:

- accept only the fixed ECZ GitHub repository and a validated SHA;
- avoid extracting archive members to disk;
- read only expected YAML paths;
- cap compressed and expanded byte counts;
- cap member count and individual member size;
- reject duplicate `code_id` values;
- reject malformed relation structures; and
- calculate and record the archive SHA-256.

### 7.5 Validation

Before applying a source, verify:

- every code ID follows the upstream identifier pattern;
- every parent exists;
- no self-parent edge exists;
- the full parsed parent graph is acyclic;
- all source IDs and projected edges are unique; and
- configured size ceilings are respected.

The service should reject unexpectedly large structural diffs, initially
including:

- a cycle or dangling relation;
- a source that is implausibly small or large; or
- a change to more than approximately 10% of current terms in one run.

The precise percentage is an operational guardrail, not a scientific rule. A
rejected run remains visible to administrators and may later be deliberately
accepted after inspection through a separate privileged command or workflow.
The unattended cron must never pass an override flag.

### 7.6 Atomic application

The database apply phase should:

1. acquire a PostgreSQL advisory transaction lock dedicated to ECZ sync;
2. recheck the currently applied source SHA;
3. create or update current term projections by `ecz_code_id`;
4. mark missing terms retired rather than deleting them;
5. replace the current ECZ parent edge set;
6. preserve all Circuit Bench membership and mapping rows;
7. flag mappings and parent links whose ECZ target has retired for review;
8. store the diff and successful run metadata; and
9. commit all changes together.

Running the command repeatedly against one source is a fast no-op.

## 8. Upstream lifecycle handling

| Upstream event | Circuit Bench behaviour |
| --- | --- |
| New term | Create a current, selectable ECZ term |
| Retired ID returns | Restore the existing identity to current status |
| Same ID, changed name | Update current names; references remain stable |
| Parent change | Replace imported parent edges atomically |
| Term disappears globally | Mark retired; retain page and references |
| Possible ID rename | Create new term, retain old term, add curation suggestion |
| Active mapping target retires | Preserve mapping but flag it for admin review |
| Invalid or surprising source | Reject whole run; keep previous projection active |

Historical published Circuit Bench records must continue displaying the last
known name and ECZ identity even if the term is no longer current upstream.
Their pages should state that the term is absent from the current imported ECZ
snapshot.

## 9. Display and data pages

### 9.1 Shared presentation model

A read-side adapter should expose a common shape for native and ECZ terms rather
than making templates inspect unrelated Django models directly:

```text
TaxonomyTermDisplay
    key
    source              # circuit_bench | ecz
    label
    url
    selectable
    selected
    status
    colour
    border_style
```

Stable picker and query identities should be namespaced, for example:

```text
cb:<tag-uuid>
ecz:<ecz-code-id>
```

This avoids ambiguous primary keys and avoids a generic foreign-key design.

### 9.2 ECZ visual language

ECZ terms are presented as:

- blue in every theme, using theme-aware blue palette variables;
- a dashed outline;
- the displayed ECZ name; and
- a visible `(ECZ)` suffix, for example `Bivariate bicycle code (ECZ)`.

The colour and outline must not be the only indication of source. The suffix is
required for textual and accessible distinction.

### 9.3 Stub page

An ECZ term page contains:

- its rendered name;
- a prominent link to the canonical ECZ page;
- a concise statement that ECZ is the source of truth;
- immediate parents and children within the imported projection;
- Circuit Bench tags that use it as a parent;
- active or historical equivalence mappings;
- circuits tagged with it;
- current or retired status; and
- a collapsed provenance section containing source SHA, workflow run,
  synchronisation time, attribution and licence.

It does not reproduce the ECZ description.

## 10. Picker and search design

### 10.1 Why the current approach should change

The existing picker renders every possible Circuit Bench tag into the document
and filters the choices in JavaScript. Adding 1,142 ECZ terms to every instance
would still be computationally possible, but it would duplicate data across
forms and make the interface increasingly heavy.

The combined picker should use a small server-backed search endpoint. Ordinary
PostgreSQL comparisons are sufficient at this size.

### 10.2 Search response

The endpoint distinguishes sources and returns exact totals independently from
the displayed sample:

```json
{
  "query": "bivariate",
  "circuit_bench": {
    "shown": [],
    "total": 23,
    "remaining": 17,
    "next_cursor": "..."
  },
  "ecz": {
    "shown": [],
    "total": 999,
    "remaining": 993,
    "next_cursor": "..."
  },
  "unselected_parents": {
    "circuit_bench": {
      "shown": [],
      "total": 4,
      "remaining": 0
    },
    "ecz": {
      "shown": [],
      "total": 31,
      "remaining": 25
    }
  }
}
```

The example counts are illustrative. The implementation computes them from the
same query that produced the displayed choices.

### 10.3 Result behaviour

The picker initially renders only a small relevance-ranked sample. Beneath it,
independent controls show the remaining counts, for example:

```text
+ 999 Error Correction Zoo tags
+ 23 Circuit Bench tags
```

Activating one progressively fetches the next page from that source. It does
not insert hundreds of hidden elements into the document. The remaining count
decreases as pages are revealed.

Selected choices do not disappear from the principal available-results area.
They remain present, become slightly greyed, and replace their normal glyph
with a tick.

The basic relevance order is:

1. exact name or Circuit Bench alias;
2. exact ECZ code ID;
3. name or alias prefix;
4. substring match; and
5. stable alphabetical order.

Fuzzy search and a separate search engine are unnecessary for the first
version.

### 10.4 Unselected parent box

The parent box remains a light, subordinate box below the principal results. It
is labelled `Unselected parent tags` and disappears when empty.

It contains only direct parents of:

- selected terms; and
- matching terms actually included in the currently displayed sample.

It excludes:

- already selected parents;
- any term already displayed in the principal results; and
- parents of hidden, not-yet-fetched matches.

It uses the same ECZ styling, source-specific totals and progressive expansion
controls as the principal results. Thus a large parent result may independently
show controls such as `+ 25 Error Correction Zoo tags` and `+ 3 Circuit Bench
tags`.

## 11. Name rendering

The ECZ schema marks code names as standalone FLM content. Of the 1,142 terms in
the proposed deployed projection, 228 contained backslash-based FLM markup,
mostly inline mathematical notation such as code parameters. Raw YAML strings
cannot simply be escaped and displayed as ordinary text.

The preferred solution is a small ECZ-provided export containing a safely
rendered name. Without that cooperation, Circuit Bench must:

1. store the exact raw upstream value;
2. derive a safe display value through a deliberately limited renderer;
3. never render arbitrary upstream HTML unsanitised; and
4. retain the source value so rendering can be improved without resynchronising
   historical identity.

Running the complete ECZ site generator merely to obtain 1,142 names would add
Node, Yarn, Ruby and ECZ-specific build dependencies and is not appropriate for
the daily Circuit Bench job.

## 12. Render deployment

### 12.1 Cron service

Add a dedicated Render cron service to the staging Blueprint after the importer
is complete:

```yaml
- type: cron
  name: circuit-bench-ecz-sync-staging
  runtime: python
  branch: staging
  plan: 0.5c-512mb
  region: frankfurt
  schedule: "17 3 * * *"
  buildCommand: ./scripts/render-build.sh
  startCommand: python manage.py sync_ecz_taxonomy
  envVars:
    - key: DJANGO_SETTINGS_MODULE
      value: config.settings.production
    - key: DATABASE_URL
      fromDatabase:
        name: circuit-bench-staging-db
        property: connectionString
```

The exact build command may later be split so the cron installs dependencies
without unnecessarily collecting static files. Reusing the current build
script is acceptable initially because it does not apply migrations.

Render cron expressions use UTC. The non-round minute avoids concentrating work
at the top of the hour. A daily check places the public mirror at most roughly
24 hours behind a deployment, which is adequate for this use case.

Render documentation:

- <https://render.com/docs/cronjobs>
- <https://render.com/docs/blueprint-spec>

Render currently documents a minimum charge of USD 1 per month per cron
service, plus runtime-based usage. The expected runtime and data transfer for
this importer are negligible.

### 12.2 Migration ordering

The cron must not run database migrations. It should verify that the database
schema is current and abort clearly if required migrations have not yet been
applied. This avoids a race in which a new cron build runs before the web
service has completed deployment and migration.

### 12.3 Concurrency

Render guarantees at most one active run of a given cron service. The database
advisory lock remains necessary because:

- a developer or administrator may invoke the command manually;
- staging operations may overlap a scheduled run; and
- correctness should not depend exclusively on one hosting provider.

## 13. Local and automated testing

The cron schedule is not application logic. Local development tests the command
that Render will invoke.

### 13.1 Synthetic fixtures

Create small ECZ-shaped YAML trees under the tests directory:

- `snapshot_a`: a valid collection of codes and parent relationships;
- `snapshot_b`: an added term, a renamed term and changed parent edges;
- `snapshot_c`: a removed term and a previously retired term returning;
- `invalid_cycle`;
- `invalid_dangling_parent`;
- `invalid_duplicate_id`; and
- `invalid_duplicate_yaml_key`.

Synthetic fixtures keep ordinary tests deterministic and avoid copying a large
third-party dataset into the repository.

### 13.2 Local workflow

```bash
python manage.py sync_ecz_taxonomy \
  --source-dir tests/fixtures/eczoo/snapshot_a \
  --dry-run

python manage.py sync_ecz_taxonomy \
  --source-dir tests/fixtures/eczoo/snapshot_a

python manage.py sync_ecz_taxonomy \
  --source-dir tests/fixtures/eczoo/snapshot_a

python manage.py sync_ecz_taxonomy \
  --source-dir tests/fixtures/eczoo/snapshot_b
```

This demonstrates dry-run output, initial application, same-source idempotence,
and a visible A-to-B update without waiting for a clock.

An invalid fixture is then run to verify that the database remains byte-for-byte
equivalent at the projection level after rejection.

### 13.3 Test layers

Pure unit tests cover:

- strict YAML parsing;
- source-path and size-limit enforcement;
- complete graph construction;
- cycle detection;
- missing and dangling relationships;
- source diff construction; and
- name transformation and sanitisation.

PostgreSQL service tests cover:

- initial import;
- idempotent repeat;
- atomic additions, renames and edge changes;
- term retirement and preservation of memberships;
- rollback on every validation failure;
- advisory-lock behaviour;
- mapping and demerge history;
- equivalence-induced cycles; and
- publication records continuing to resolve retired terms.

HTTP and template tests cover:

- blue dashed ECZ rendering and textual `(ECZ)` marker;
- ECZ stub provenance and external link;
- picker source totals and pagination;
- selected choices remaining visible with a tick;
- parent-box exclusion and deduplication;
- parent-box source totals and expansion; and
- only current terms being available for new assignment.

One opt-in network integration test may fetch a pinned ECZ SHA. It must not run
in the ordinary test suite or make CI depend on GitHub availability.

### 13.4 Staging verification

After adding the Render service:

1. deploy the migrations and application code;
2. manually use Render's `Trigger Run` control;
3. inspect the run log and `ecz_sync_run` row;
4. inspect imported counts, several stub pages and picker searches;
5. trigger the job again and verify a no-op;
6. observe at least two or three successful manual runs; and
7. enable or retain the daily schedule.

There is no need to wait for the scheduled hour to verify the real deployed
path.

## 14. Administration and observability

Add an `ECZ synchronisation` section to the existing administrator area. It
shows:

- currently applied ECZ data SHA;
- linked production workflow run;
- last attempted and last successful synchronisation times;
- current and retired counts;
- the latest added, retired, renamed and reparented terms;
- rejected-run diagnostics;
- active mappings targeting retired terms; and
- suggested possible replacements or mappings awaiting review.

The public website must continue serving the last good projection if ECZ,
GitHub, parsing or validation fails. A failed synchronisation should be logged
and visible to administrators but must not make the main site unhealthy.

A warning should be raised when no successful check has occurred for a
configurable interval, initially seven days.

The first version should not expose a web button that performs a long network
synchronisation in the request process. Administrators can inspect status and
use the Render manual trigger or management command.

## 15. Minimal cooperation requested from the ECZ team

The integration is possible without intervention because the repository and
licence are public. Three small confirmations would materially improve its
reliability:

1. Confirm that the data SHA of the latest successful
   `build-and-deploy-site.yml` run identifies the taxonomy currently intended
   for the public site.
2. Confirm preferred attribution wording for the derived Circuit Bench
   projection.
3. Confirm that `code_id` is the correct stable external identity, while
   acknowledging that occasional replacements may occur.

The most valuable minimal technical addition would be a stable public file such
as:

```json
{
  "schema_version": 1,
  "data_repository": "errorcorrectionzoo/eczoo_data",
  "data_commit": "f7d89f07a825686e1c23d5fb4cbeacd968d9b9d1",
  "deployed_at": "2026-08-28T22:34:31Z"
}
```

served as, for example:

```text
https://errorcorrectionzoo.org/data-version.json
```

That would remove ambiguity and avoid dependence on GitHub Actions API rate
limits.

An even more useful but still small export would be
`taxonomy-v1.json`, generated from ECZ's already validated in-memory database:

```json
{
  "schema_version": 1,
  "data_commit": "f7d89f07a825686e1c23d5fb4cbeacd968d9b9d1",
  "terms": [
    {
      "code_id": "surface",
      "name_html": "Kitaev's surface code",
      "parent_ids": ["qubits_into_qubits"],
      "url": "https://errorcorrectionzoo.org/c/surface"
    }
  ]
}
```

Circuit Bench would still validate and sanitise this input. The export would
solve both deployed-version discovery and faithful FLM name rendering. A
deployment webhook is unnecessary for the first version; daily polling is
sufficient.

## 16. Delivery sequence

### Phase 1: importer foundation

- Add ECZ models and migration.
- Add strict YAML source parser and graph projection.
- Add synthetic fixtures and pure tests.
- Add atomic synchronisation service and management command.
- Add dry-run and pinned-ref modes.

### Phase 2: taxonomy integration

- Add circuit-to-ECZ memberships.
- Add Circuit-Bench-to-ECZ parent relationships.
- Add reversible equivalence mappings and curation tests.
- Extend taxonomy validation across the combined graph.
- Add the shared read-side taxonomy adapter.

### Phase 3: interface

- Add ECZ stub pages.
- Add blue dashed tag presentation.
- Replace picker option embedding with the paginated search endpoint.
- Add independent Circuit Bench and ECZ totals and expansion controls.
- Apply identical source limiting to the unselected-parent box.
- Add administrative mapping and sync-status views.

### Phase 4: staging synchronisation

- Add the Render cron service.
- Trigger it manually on staging.
- Verify idempotence, failure isolation, provenance and UI behaviour.
- Leave it on a daily UTC schedule.

### Phase 5: ECZ cooperation

- Send the authority, attribution and stable-ID questions to ECZ.
- Prefer their deployed-version manifest if supplied.
- Prefer their compact rendered taxonomy export if supplied.
- Keep the GitHub pinned-archive importer as a documented fallback.

## 17. Acceptance criteria

The first version is complete when:

1. A pinned deployed ECZ snapshot imports locally and on staging.
2. The same source is idempotent.
3. Invalid or surprisingly large changes cannot alter the active projection.
4. The complete imported ECZ graph contains no dangling or cyclic edges.
5. Existing Circuit Bench records survive upstream removal.
6. ECZ terms are visibly distinguishable in every relevant picker and tag list.
7. Picker HTML does not contain the entire ECZ taxonomy by default.
8. Principal and parent results show correct per-source hidden counts.
9. Circuit Bench tags can use ECZ parents without weakening cycle validation.
10. Merge and demerge preserve original memberships and leave an audit trail.
11. Every ECZ stub links prominently to ECZ and exposes exact provenance and
    licence attribution.
12. A failed daily run leaves the website and last good taxonomy unaffected.

## 18. Estimated effort and operating cost

A reasonable implementation estimate for one developer is approximately one
focused week:

- one to two days for models, parser, graph and command;
- two to three days for the combined picker, search endpoint and stub pages;
- one to two days for mapping curation, deployment and hardening.

The projected data is far below any meaningful PostgreSQL or network cost
threshold. The new recurring infrastructure charge should be the Render cron
minimum, currently approximately USD 1 per month, plus negligible execution
time.
