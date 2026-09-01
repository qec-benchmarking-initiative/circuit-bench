# Circuit Bench development plan

Status: foundation, parallel waves A and B, the ResultRecord query integration,
and comparison-interface wave C are complete for the 0.1 prototype. Submission
and governance workflows remain deliberately deferred and were not part of
this implementation pass.

## Working rules

- PostgreSQL is used from the first migration onward; SQLite is not a supported
  development shortcut.
- Django migrations are the only executable database schema. Do not add a
  parallel handwritten SQL schema.
- The relational model in `docs/data-model-0.1.md` is the source for physical
  models. Checked-in schemas and definitions are the source for public
  scientific interchange and meaning.
- Shared project configuration, root URLs, base templates, dependency locks,
  and migration ordering have one integration owner. Parallel tasks do not edit
  them without an explicit handoff.
- Each task must include focused tests, a short verification command, and a
  visible browser page or machine-readable response where applicable.

## Foundation: complete serially before broad parallel work

### F0. Local PostgreSQL — complete

The official `postgres:17.11-bookworm` image runs from `compose.yaml`, binds
only to `127.0.0.1:5432`, and stores data in the named volume
`decoderbench_postgres_data`.

Verification:

```sh
docker compose up -d database
docker compose ps
docker compose exec -T database psql -U decoderbench -d decoderbench \
  -c 'select current_database(), current_user, version();'
```

### F1. Physical-model mapping audit — complete

Before generating migrations, write a short mapping note resolving:

- the Django custom user and `django-allauth` operational tables versus the
  public `account` and `external_identity` model;
- the fact that accounts have no usable local passwords and OAuth tokens are
  not retained;
- Django app boundaries and the single migration dependency graph;
- which rules are database constraints and which require publication-service
  validation;
- naming for stable public query fields, independent of storage column names.

Recommended boundary: a small `accounts` app and one `registry` app for the
highly interconnected scientific records. The registry's models can be split
into topic modules without splitting the migration graph.

User verification: read `docs/physical-model-mapping.md`, which contains the
resolved implementation choices.

### F2. Reproducible Django scaffold — complete

Create and pin the Python/Django environment, settings for development/tests/
production, PostgreSQL connection, a health endpoint, pytest, formatting and
linting, and a minimal CI job. Include `.env.example`; commit no secrets.

Verification:

```sh
uv sync --frozen
uv run python manage.py check
uv run pytest
uv run python manage.py runserver
```

The browser should show a plain project page, and `/health/` should confirm the
application can query PostgreSQL.

### F3. Executable `0.1` relational schema — complete

Implement the complete model as Django models and initial migrations. Keep the
scientific models in topic files under `registry/models/`, but generate and
review migrations centrally. Implement all ordinary checks, uniqueness rules,
partial indexes, and restrictive foreign keys that PostgreSQL can enforce.
Record cross-row publication rules as explicit pending service checks rather
than pretending a database constraint covers them.

Verification:

```sh
docker compose down
docker compose up -d database
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest tests/schema
```

The schema tests should inspect PostgreSQL constraints as well as Django model
metadata.

### F4. Deterministic demonstration data — complete

Add factories and an idempotent `seed_demo` management command containing a
small but relationally complete example: linked accounts, official/custom tags,
noise models, circuit revisions, decoder versions, machines, evaluator and
score definitions, results, and a benchmark attempt.

Verification:

```sh
uv run python manage.py seed_demo --reset
uv run python manage.py seed_demo --reset
```

Both runs should succeed and leave the documented row counts. The Django admin
should make the relationships inspectable.

### F5. Page and component foundation — complete

Create the global navigation, `base`, collection and entity-detail layouts,
CSS tokens, and a development-only component gallery. Use representative
fixture data to exercise long names, many tags, null fields, empty lists,
errors, and narrow screens. Establish named extension points so later agents do
not edit the base layouts.

User verification: inspect the component gallery at desktop and mobile widths
and approve the basic information hierarchy. This is structural, not the final
visual design workshop.

The development-only gallery is at `http://127.0.0.1:8000/dev/components/`.
Automated checks cover its production-only 404 guard; browser verification at
390 px and desktop width found no page-level overflow or console errors.

## Parallel wave A: independent vertical slices

These tasks may begin after F1–F5. Each owns its page templates, services, URLs
below its assigned prefix, and focused tests. Root integration files remain
owned by the integrator.

### A1. Provider-only accounts — complete

Implement GitHub/ORCID sign-in, linking and unlinking, prevent removal of the
last identity, and reject silent account merging. Use mocked providers in the
automated test suite; real credentials are only needed for a final smoke test.

User verification: `/accounts/login/` has two plain buttons; a test account can
show one linked provider, link the second, and is prevented from removing both.

### A2. Artifact and schema-release pipeline — complete

Implement local content-addressed storage, SHA-256/size verification,
deduplication, immutable bytes, and loading of checked-in schema/definition
files into draft `schema_release` records. Do not build scientific submission
forms yet.

User verification: upload the same small file twice, observe one artifact,
download identical bytes, and see a changed-on-disk object fail verification.

### A3. Decoder discovery and detail slice — complete

Implement `/decoders/` as a search-first discovery catalogue and
`/decoders/<slug>/` with inherited description, exact-version metadata,
credits, identities, algorithm tags, preparation capabilities and related
results placeholder. Read-only only.

User verification: find seeded decoders by exact name and tag, open a version,
follow its predecessor, and inspect the empty/populated related-results states.

### A4. Circuit and noise-model discovery/detail slice — complete

Implement `/circuits/`, `/circuits/<slug>/`, `/noise-models/`, and
`/noise-models/<slug>/`. Show code/experiment tags, exact artifact hashes,
distance upper bounds, DEM facts, and the derived randomised-priors property.

User verification: find a seeded circuit by code or experiment tag, download
its frozen artifacts, and follow its noise-model link to the reverse circuit
list.

## Serial explorer-interface foundation — complete

The design workshop is recorded in `docs/interface-design-plan.md`. Decoders,
Circuits and Noise models now share a desktop-first scientific explorer shell:
active persistent-navigation identity, compact query/status/filter rows, dense
full-width tables, sticky headers/first column, ordinary and Shift-click
multi-sort, and URL-backed column choices. Endpoint filters run on the server.

Algorithm, code and experiment tags use one modal picker. It searches the
official vocabulary plus custom tags used by public records, distinguishes
official/custom tags visually, and commits either AND or OR matching through
explicit action buttons. The same component boundary is reserved for later
data-entry mode and custom-tag creation.

The visible controls now use one declaration-driven square filter grid. Choice
cells telescope temporary dotted options over a frozen base layout; numeric
cells expose the database distribution with draggable minimum/maximum handles;
tag cells expand across grid tracks as their selected cards require. Algorithm,
circuit and machine grids are composed on decoder and circuit leaderboards and
on the implemented `/results/` explorer. All pages call the same published
result query service, and combined result URLs distinguish decoder preparation
(`decoder_priors`) from randomised circuit priors (`circuit_priors`).

The grid now retains explicit lower rules on every occupied cell and diagonal
hatching in unoccupied tracks. Choice placement minimises new rows and may
split options around its anchor; numeric reset immediately restores `0–∞` and
closes. The circuit grid's noise-model cell is the first use of a distinct
allow-listed related-record picker: it searches and paginates on the server,
orders official records first, displays a compact first-name-plus-count
summary, and serialises scalar `IN` selection as repeated `noise_model` URL
parameters. The same circuit grid therefore behaves identically on Circuits,
Results, and decoder record pages without loading the complete noise-model
table into their HTML.

All implemented filter forms share an Autoquery controller. Autoquery is on by
default, turns every committed filter edit into the same canonical GET that the
manual Apply button would send, and can be disabled when a user wants to batch
several edits. Its preference persists locally. Query navigation also restores
the page's scroll coordinate and per-grid disclosure state, so live filtering
does not jump to the document top or expand strips the user had collapsed.

This work deliberately does not define the scripted query language, JSON/CSV
formats, public null ordering or API field registry. The serial comparison
query-contract task below remains the prerequisite for those promises and for
the final comparison interface.

Verification:

```sh
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
```

Browser review covered all three explorers at the primary desktop width, the
tag-picker no-match/selection paths, AND/OR URL state, column selection and
ordinary/Shift-click sorting.

The second visual-review pass made this surface genuinely continuous: the
persistent header, page shell and edge-ruled table now share a near-full-width
frame, and endpoint filters are a compact wrapping instrument strip rather than
uneven panels. Official tags may carry an administrator-selected hexadecimal
presentation colour; custom tags always render neutral and glyph shape remains
the colour-independent status cue. Decoder, circuit and noise-model detail
views now use a shared flat reference-page layout with ruled sections, a narrow
exact-revision rail and dense relationship tables instead of card lists.

The circuit detail has since become the comparison-heavy record variant: a
compact dossier and collapsed exact-provenance disclosure lead into a dominant
circuit-scoped result explorer. Decoder method/capability controls are packaged
as a reusable native-disclosure `Algorithm filters` strip shared with decoder
discovery; execution hardware is a parallel reusable `Machine filters` strip.
The scoped table uses the ordinary shared sorting and URL-backed column
controls, and all strip predicates are applied on the server.

Machine slugs in result tables now link to an exact machine record page. That
page renders the immutable machine metadata and a reverse shared result table;
all public evaluator-score displays use a single significant-precision
formatter and switch to compact scientific notation for suitably small or
large values.

## Parallel wave B: remaining read views and contract coverage — complete

### B1. Result detail

Render exact decoder/circuit/evaluator/machine provenance, raw aggregate counts,
score definitions and bounds without recomputing or pooling results.

User verification: every displayed score links to its immutable definition and
all four outcome counts visibly add to `shots_total`.

### B2. Benchmark detail

Render ordered required/optional circuit membership and attempts without
inventing an aggregate benchmark score.

User verification: item order matches the manifest fixture and an attempt links
to exactly one result per required circuit.

### B3. Static information pages and blog

Render version-controlled Markdown About pages through the shared shell and add
the smallest suitable blog implementation. Include the future query-language
reference route, initially as a clearly marked draft.

User verification: navigation, Markdown headings/links, post index/detail and
RSS (if included) render without administrator-only tooling.

### B4. Missing public contracts

Create and validate the missing `0.1` JSON Schemas and definition documents for
tag, noise model, circuit, machine, evaluator, result and benchmark. This is a
contract task, not a database-migration task.

User verification: one command validates every JSON Schema and checks that each
required record type has both schema and definition files.

## Serial integration: comparison query contract — complete

Before parallel table/API/plot work, define one stable public `ResultRecord`
query model and the supported OData subset. Specify field names, types, units,
definitions, null behaviour, operators, deterministic tie-breaking, limits,
error format and live-query versus frozen-snapshot semantics.

Implement one typed parser/compiler that produces a safe Django query. It must
whitelist fields and operators and must never pass raw query text to SQL.

Verification: contract tests show that equivalent manual filter state and raw
OData text produce the same ordered result IDs; invalid/expensive queries fail
with stable errors.

## Parallel wave C: comparison interfaces — complete

### C1. Machine-readable results API

Expose the query model as versioned JSON and CSV, including canonical query,
schema version, generation time, count and stable identifiers.

User verification: run a documented `curl` command and compare its ordered IDs
with the browser table.

### C2. Interactive comparison table

Implement click-to-sort, click-again reversal, shift-click secondary sorting,
the structured filter/sort dialog, raw text query box, adjacent status bar and
link to the syntax page. Invalid text leaves the last valid table visible.

User verification: build a two-column sort using clicks, copy the URL into a
new browser, and reproduce the same ordering; then enter an invalid field and
observe a useful positional error.

### C3. Dynamic plots

Render plots from the exact same parsed query and result IDs as the table. Keep
plot configuration explicit and scientific units visible.

User verification: changing a filter updates the table and plot together, and
the displayed population/count agrees in both.

### C4. Discovery curation policy hook

Implement the catalogue's default `featured` ordering behind a named policy
interface, initially using an obviously provisional deterministic policy. Do
not label it “best” and do not mix it with scientific leaderboard ordering.

User verification: an unfiltered overview shows labelled featured entries;
searching replaces them with relevance-ranked matches.

## Submission and governance waves — editing/withdrawal slice complete

The first write-side slice is implemented and specified in
`docs/submission-governance-0.1.md`: decoder, circuit, result and machine entry
through either a structured form or strict JSON; session-bound preview/back;
searchable and paginated profile tables; a staff-only review work queue; private
exact candidate-record views; transactional publication and moderation events;
and deterministic workflow fixtures. Pending candidates can be edited in place.
Published edits create immutable successors, withdrawal requires confirmation,
and successors to withdrawn records enter `pending_reapproval`. The admin page
contains only items waiting for review plus records withdrawn in the preceding
seven days. Approval attribution names the reviewing account or the reserved
`System` actor for policy-driven publication. Policy 0.1 sends
decoder/circuit/result records to admin review even when an admin submits them,
while ordinary machines publish immediately after validation. Result references
must already be published at submission and are rechecked at approval.

Later slices remain separate: rejection/requested changes, credit claims,
author approvals, tag and noise-model curation, benchmark
approval, evaluator-summary ingestion, notification and account recovery. They
modify immutable scientific state and should retain focused service boundaries
and audit-event tests.

## Integration discipline for parallel agents

Every task handoff names:

1. files/directories the agent owns;
2. interfaces it may call but not change;
3. acceptance commands and browser URLs;
4. required fixtures;
5. prohibited scope, especially migrations and shared configuration;
6. a small commit suitable for independent review.

An integration pass runs the complete suite, applies migrations to a fresh
PostgreSQL volume, loads demonstration data, and manually checks the declared
URLs before the next wave begins.
