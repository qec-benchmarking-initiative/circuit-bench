# Circuit Bench relational data model

Status: superseded by `docs/data-model-0.1.md`; retained as design history.
Newer entity contracts under `schemas/` and `definitions/` take precedence
where they differ.
Database: PostgreSQL  
Identifier policy: UUID primary keys; public URLs use immutable slugs plus UUIDs

This model implements the working plan's small scientific registry. It is not
an experiment-tracking system. PostgreSQL stores structured metadata and
queryable result summaries. Potentially large circuit files, manifests, raw
traces, and evaluator output files live in object storage; the `artifact`
table records their identity and integrity.

## Design rules

1. A published decoder version, circuit revision, benchmark revision, machine,
   evaluator release, or result is immutable. Corrections create a new row.
2. Family records (`decoder`, `circuit`, and `benchmark`) provide stable grouping
   and may have their display text edited. Their published revisions may not.
3. Every scientific file is content-addressed with SHA-256. A circuit revision's
   `manifest_sha256` is the identity of its complete scientific definition.
4. Results keep submitted facts (`shots`, `failures_any_logical`, timing inputs,
   and tuning flags) separately from evaluator-derived values. Frequently
   queried derived values are stored, but accepted only when reproduced by the
   named evaluator release.
5. A benchmark attempt is a grouping of existing circuit results. A result may
   therefore be reused by both a Core and a Full attempt.
6. Publication and withdrawal are explicit states. Rows are never hard-deleted
   once published.
7. `ON DELETE RESTRICT` is intentional for scientific records. Draft cleanup is
   an application operation, not cascading deletion.

## Relationship overview

```text
decoder ──< decoder_version ───────────────┐
                                            │
circuit ──< circuit_revision ──< result >── machine
                     │              │
                     │              └────── evaluator_release
                     │
benchmark ──< benchmark_revision
                     │
                     └──< benchmark_revision_item >── circuit_revision
                              │
benchmark_attempt ──< benchmark_attempt_result >────── result

artifact is referenced by revisions and results; account owns submissions.
```

## Table and key catalogue

| Table | Primary key | Important candidate/composite keys | Purpose |
|---|---|---|---|
| `account` | `id` | case-insensitive `email` | Submitter or moderator identity |
| `oauth_identity` | `id` | (`provider`, `provider_subject`) | GitHub/ORCID login attached to an account |
| `artifact` | `id` | (`storage_backend`, `object_key`); `sha256` | Content-addressed file metadata |
| `decoder` | `id` | `slug` | Stable decoder family |
| `decoder_version` | `id` | (`decoder_id`, `version`) | Immutable decoder release |
| `decoder_version_author` | (`decoder_version_id`, `position`) | — | Ordered author list |
| `decoder_version_link` | `id` | (`decoder_version_id`, `url`) | Paper/source/documentation links |
| `circuit` | `id` | `slug` | Stable circuit family |
| `circuit_revision` | `id` | (`circuit_id`, `revision_number`); `manifest_sha256` | Immutable scientific workload |
| `circuit_revision_artifact` | (`circuit_revision_id`, `role`, `position`) | (`circuit_revision_id`, `artifact_id`) | Circuit/DEM/manifest files |
| `circuit_revision_link` | `id` | (`circuit_revision_id`, `url`) | Circuit references |
| `machine` | `id` | `slug` | Reusable hardware description |
| `benchmark` | `id` | `slug` | Stable benchmark/gamut family |
| `benchmark_revision` | `id` | (`benchmark_id`, `version`) | Immutable Core/Full release |
| `benchmark_revision_item` | (`benchmark_revision_id`, `circuit_revision_id`) | (`benchmark_revision_id`, `position`) | Ordered workload membership |
| `evaluator_release` | `id` | `version` | Versioned calculation semantics |
| `result` | `id` | `evaluator_output_artifact_id`; `predecessor_id` | One circuit measurement |
| `result_artifact` | (`result_id`, `role`, `position`) | (`result_id`, `artifact_id`) | Optional raw/reproduction files |
| `result_link` | `id` | (`result_id`, `url`) | External supporting evidence |
| `benchmark_attempt` | `id` | (`id`, `benchmark_revision_id`, `decoder_version_id`, `machine_id`) | Complete gamut submission |
| `benchmark_attempt_result` | (`benchmark_attempt_id`, `circuit_revision_id`) | (`benchmark_attempt_id`, `result_id`) | Reusable constituent results |
| `submission_review` | `id` | exactly one non-null subject FK | Append-only moderation history |

## PostgreSQL definition

The following DDL is the normative v1 proposal. Django migrations may express
the same constraints rather than executing this file verbatim.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Human accounts and external login identities -----------------------------

CREATE TABLE account (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT NOT NULL,
    display_name        TEXT NOT NULL,
    password_hash       VARCHAR(128) NOT NULL DEFAULT '',
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    is_staff            BOOLEAN NOT NULL DEFAULT FALSE,
    is_superuser        BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified_at   TIMESTAMPTZ,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT account_email_nonempty CHECK (btrim(email) <> ''),
    CONSTRAINT account_display_name_nonempty CHECK (btrim(display_name) <> '')
);

CREATE UNIQUE INDEX account_email_ci_uq ON account (lower(email));

CREATE TABLE oauth_identity (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          UUID NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    provider            TEXT NOT NULL,
    provider_subject    TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT oauth_identity_provider_ck
        CHECK (provider IN ('github', 'orcid')),
    CONSTRAINT oauth_identity_provider_subject_uq
        UNIQUE (provider, provider_subject)
);

-- Durable files -------------------------------------------------------------

CREATE TABLE artifact (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_backend     TEXT NOT NULL,
    object_key          TEXT NOT NULL,
    sha256              CHAR(64) NOT NULL,
    byte_size           BIGINT NOT NULL,
    media_type          TEXT NOT NULL,
    original_filename   TEXT NOT NULL,
    uploaded_by_id      UUID REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT artifact_storage_backend_ck
        CHECK (storage_backend IN ('local', 'r2', 'external')),
    CONSTRAINT artifact_object_key_nonempty CHECK (btrim(object_key) <> ''),
    CONSTRAINT artifact_sha256_ck CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifact_byte_size_ck CHECK (byte_size >= 0),
    CONSTRAINT artifact_location_uq UNIQUE (storage_backend, object_key),
    CONSTRAINT artifact_content_uq UNIQUE (sha256)
);

-- Decoders ------------------------------------------------------------------

CREATE TABLE decoder (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    created_by_id       UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT decoder_slug_ck CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT decoder_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE decoder_version (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decoder_id          UUID NOT NULL REFERENCES decoder(id) ON DELETE RESTRICT,
    version             TEXT NOT NULL,
    description         TEXT NOT NULL,
    release_date        DATE,
    predecessor_id UUID REFERENCES decoder_version(id) ON DELETE RESTRICT,
    state               TEXT NOT NULL DEFAULT 'draft',
    submitted_by_id     UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    withdrawn_at        TIMESTAMPTZ,
    CONSTRAINT decoder_version_version_nonempty CHECK (btrim(version) <> ''),
    CONSTRAINT decoder_version_state_ck
        CHECK (state IN ('draft', 'pending_review', 'published', 'withdrawn')),
    CONSTRAINT decoder_version_identity_uq UNIQUE (decoder_id, version),
    CONSTRAINT decoder_version_predecessor_not_self_ck CHECK (predecessor_id <> id),
    CONSTRAINT decoder_version_publication_ck CHECK (
        (state IN ('published', 'withdrawn') AND published_at IS NOT NULL)
        OR (state IN ('draft', 'pending_review') AND published_at IS NULL)
    ),
    CONSTRAINT decoder_version_withdrawal_ck CHECK (
        (state = 'withdrawn' AND withdrawn_at IS NOT NULL)
        OR (state <> 'withdrawn' AND withdrawn_at IS NULL)
    )
);

CREATE TABLE decoder_version_author (
    decoder_version_id  UUID NOT NULL REFERENCES decoder_version(id) ON DELETE RESTRICT,
    position            SMALLINT NOT NULL,
    display_name        TEXT NOT NULL,
    orcid               VARCHAR(19),
    affiliation         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (decoder_version_id, position),
    CONSTRAINT decoder_version_author_position_ck CHECK (position >= 1),
    CONSTRAINT decoder_version_author_name_nonempty CHECK (btrim(display_name) <> ''),
    CONSTRAINT decoder_version_author_orcid_ck CHECK (
        orcid IS NULL OR orcid ~ '^0000-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X]$'
    )
);

CREATE TABLE decoder_version_link (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decoder_version_id  UUID NOT NULL REFERENCES decoder_version(id) ON DELETE RESTRICT,
    kind                TEXT NOT NULL,
    url                 TEXT NOT NULL,
    label               TEXT NOT NULL DEFAULT '',
    position            SMALLINT NOT NULL DEFAULT 1,
    CONSTRAINT decoder_version_link_kind_ck
        CHECK (kind IN ('paper', 'source', 'documentation', 'artifact', 'other')),
    CONSTRAINT decoder_version_link_position_ck CHECK (position >= 1),
    CONSTRAINT decoder_version_link_uq UNIQUE (decoder_version_id, url)
);

-- Circuits and immutable revisions -----------------------------------------

CREATE TABLE circuit (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    summary             TEXT NOT NULL DEFAULT '',
    created_by_id       UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT circuit_slug_ck CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT circuit_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE circuit_revision (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    circuit_id          UUID NOT NULL REFERENCES circuit(id) ON DELETE RESTRICT,
    revision_number     INTEGER NOT NULL,
    manifest_sha256     CHAR(64) NOT NULL,
    description         TEXT NOT NULL,
    code_family         TEXT NOT NULL,
    experiment_type     TEXT NOT NULL,
    noise_model_name    TEXT NOT NULL,
    physical_error_rate NUMERIC(24, 18),
    rounds              INTEGER,
    logical_count       INTEGER NOT NULL,
    parameters          JSONB NOT NULL DEFAULT '{}'::jsonb,
    license_spdx        TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'draft',
    submitted_by_id     UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    withdrawn_at        TIMESTAMPTZ,
    CONSTRAINT circuit_revision_number_ck CHECK (revision_number >= 1),
    CONSTRAINT circuit_revision_manifest_sha256_ck
        CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT circuit_revision_manifest_sha256_uq UNIQUE (manifest_sha256),
    CONSTRAINT circuit_revision_identity_uq UNIQUE (circuit_id, revision_number),
    CONSTRAINT circuit_revision_physical_error_rate_ck CHECK (
        physical_error_rate IS NULL
        OR (physical_error_rate >= 0 AND physical_error_rate <= 1)
    ),
    CONSTRAINT circuit_revision_rounds_ck CHECK (rounds IS NULL OR rounds >= 1),
    CONSTRAINT circuit_revision_logical_count_ck CHECK (logical_count >= 1),
    CONSTRAINT circuit_revision_parameters_object_ck
        CHECK (jsonb_typeof(parameters) = 'object'),
    CONSTRAINT circuit_revision_state_ck
        CHECK (state IN ('draft', 'pending_review', 'published', 'withdrawn')),
    CONSTRAINT circuit_revision_publication_ck CHECK (
        (state IN ('published', 'withdrawn') AND published_at IS NOT NULL)
        OR (state IN ('draft', 'pending_review') AND published_at IS NULL)
    ),
    CONSTRAINT circuit_revision_withdrawal_ck CHECK (
        (state = 'withdrawn' AND withdrawn_at IS NOT NULL)
        OR (state <> 'withdrawn' AND withdrawn_at IS NULL)
    )
);

CREATE TABLE circuit_revision_artifact (
    circuit_revision_id UUID NOT NULL REFERENCES circuit_revision(id) ON DELETE RESTRICT,
    artifact_id         UUID NOT NULL REFERENCES artifact(id) ON DELETE RESTRICT,
    role                TEXT NOT NULL,
    position            SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (circuit_revision_id, role, position),
    CONSTRAINT circuit_revision_artifact_role_ck CHECK (
        role IN (
            'manifest', 'circuit', 'detector_error_model', 'priors',
            'observable_definition', 'sampling_instructions', 'other'
        )
    ),
    CONSTRAINT circuit_revision_artifact_position_ck CHECK (position >= 1),
    CONSTRAINT circuit_revision_artifact_row_uq UNIQUE (circuit_revision_id, artifact_id)
);

CREATE TABLE circuit_revision_link (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    circuit_revision_id UUID NOT NULL REFERENCES circuit_revision(id) ON DELETE RESTRICT,
    kind                TEXT NOT NULL,
    url                 TEXT NOT NULL,
    label               TEXT NOT NULL DEFAULT '',
    position            SMALLINT NOT NULL DEFAULT 1,
    CONSTRAINT circuit_revision_link_kind_ck
        CHECK (kind IN ('paper', 'source', 'documentation', 'other')),
    CONSTRAINT circuit_revision_link_position_ck CHECK (position >= 1),
    CONSTRAINT circuit_revision_link_uq UNIQUE (circuit_revision_id, url)
);

-- Reusable machine descriptions --------------------------------------------

CREATE TABLE machine (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                TEXT NOT NULL UNIQUE,
    class               TEXT NOT NULL,
    description         TEXT NOT NULL,
    status              TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'draft',
    submitted_by_id     UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    withdrawn_at        TIMESTAMPTZ,
    CONSTRAINT machine_slug_ck CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT machine_class_ck
        CHECK (class IN ('cpu', 'gpu', 'fpga', 'asic', 'hybrid')),
    CONSTRAINT machine_description_nonempty CHECK (btrim(description) <> ''),
    CONSTRAINT machine_status_ck
        CHECK (status IN ('physical', 'simulated', 'estimated')),
    CONSTRAINT machine_state_ck
        CHECK (state IN ('draft', 'pending_review', 'published', 'withdrawn')),
    CONSTRAINT machine_publication_ck CHECK (
        (state IN ('published', 'withdrawn') AND published_at IS NOT NULL)
        OR (state IN ('draft', 'pending_review') AND published_at IS NULL)
    ),
    CONSTRAINT machine_withdrawal_ck CHECK (
        (state = 'withdrawn' AND withdrawn_at IS NOT NULL)
        OR (state <> 'withdrawn' AND withdrawn_at IS NULL)
    )
);

-- Versioned benchmark gamuts ------------------------------------------------

CREATE TABLE benchmark (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    purpose             TEXT NOT NULL,
    created_by_id       UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT benchmark_slug_ck CHECK (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
    CONSTRAINT benchmark_name_nonempty CHECK (btrim(name) <> '')
);

CREATE TABLE benchmark_revision (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    benchmark_id        UUID NOT NULL REFERENCES benchmark(id) ON DELETE RESTRICT,
    version             TEXT NOT NULL,
    tier                TEXT NOT NULL,
    scope               TEXT NOT NULL,
    parent_revision_id  UUID REFERENCES benchmark_revision(id) ON DELETE RESTRICT,
    reference_core_hours NUMERIC(12, 2) NOT NULL,
    manifest_artifact_id UUID NOT NULL REFERENCES artifact(id) ON DELETE RESTRICT,
    specification_artifact_id UUID NOT NULL REFERENCES artifact(id) ON DELETE RESTRICT,
    state               TEXT NOT NULL DEFAULT 'draft',
    created_by_id       UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    withdrawn_at        TIMESTAMPTZ,
    CONSTRAINT benchmark_revision_version_nonempty CHECK (btrim(version) <> ''),
    CONSTRAINT benchmark_revision_identity_uq UNIQUE (benchmark_id, version),
    CONSTRAINT benchmark_revision_tier_ck CHECK (tier IN ('core', 'full', 'other')),
    CONSTRAINT benchmark_revision_scope_ck
        CHECK (scope IN ('general', 'matchable', 'non_matchable', 'specialist')),
    CONSTRAINT benchmark_revision_parent_not_self_ck CHECK (parent_revision_id <> id),
    CONSTRAINT benchmark_revision_reference_hours_ck CHECK (reference_core_hours > 0),
    CONSTRAINT benchmark_revision_state_ck
        CHECK (state IN ('draft', 'published', 'withdrawn')),
    CONSTRAINT benchmark_revision_publication_ck CHECK (
        (state IN ('published', 'withdrawn') AND published_at IS NOT NULL)
        OR (state = 'draft' AND published_at IS NULL)
    ),
    CONSTRAINT benchmark_revision_withdrawal_ck CHECK (
        (state = 'withdrawn' AND withdrawn_at IS NOT NULL)
        OR (state <> 'withdrawn' AND withdrawn_at IS NULL)
    )
);

CREATE TABLE benchmark_revision_item (
    benchmark_revision_id UUID NOT NULL REFERENCES benchmark_revision(id) ON DELETE RESTRICT,
    circuit_revision_id UUID NOT NULL REFERENCES circuit_revision(id) ON DELETE RESTRICT,
    position            INTEGER NOT NULL,
    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (benchmark_revision_id, circuit_revision_id),
    CONSTRAINT benchmark_revision_item_position_ck CHECK (position >= 1),
    CONSTRAINT benchmark_revision_item_position_uq UNIQUE (benchmark_revision_id, position)
);

-- Evaluator versions and individual results --------------------------------

CREATE TABLE evaluator_release (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version             TEXT NOT NULL UNIQUE,
    result_schema_version INTEGER NOT NULL,
    source_url          TEXT NOT NULL,
    executable_artifact_id UUID NOT NULL REFERENCES artifact(id) ON DELETE RESTRICT,
    released_at         TIMESTAMPTZ NOT NULL,
    CONSTRAINT evaluator_release_version_nonempty CHECK (btrim(version) <> ''),
    CONSTRAINT evaluator_release_schema_version_ck CHECK (result_schema_version >= 1)
);

CREATE TABLE result (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decoder_version_id  UUID NOT NULL REFERENCES decoder_version(id) ON DELETE RESTRICT,
    circuit_revision_id UUID NOT NULL REFERENCES circuit_revision(id) ON DELETE RESTRICT,
    machine_id          UUID NOT NULL REFERENCES machine(id) ON DELETE RESTRICT,
    evaluator_release_id UUID NOT NULL REFERENCES evaluator_release(id) ON DELETE RESTRICT,
    evaluator_output_artifact_id UUID NOT NULL UNIQUE
                            REFERENCES artifact(id) ON DELETE RESTRICT,
    submitted_by_id     UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    predecessor_id UUID REFERENCES result(id) ON DELETE RESTRICT,

    state               TEXT NOT NULL DEFAULT 'pending_review',
    measurement_scope   TEXT NOT NULL,
    stim_version        TEXT NOT NULL,
    input_sha256        CHAR(64) NOT NULL,
    tuned_global        BOOLEAN NOT NULL DEFAULT FALSE,
    tuned_circuit       BOOLEAN NOT NULL DEFAULT FALSE,
    tuned_noise         BOOLEAN NOT NULL DEFAULT FALSE,

    -- Submitted/evaluator-reconciled facts.
    shots               BIGINT NOT NULL,
    failures_any_logical BIGINT NOT NULL,
    latency_mean_ns     BIGINT,
    t_1000_ns           BIGINT,

    -- Derived values emitted by evaluator_release_id.
    logical_error_rate  NUMERIC GENERATED ALWAYS AS
                            (failures_any_logical::NUMERIC / shots::NUMERIC) STORED,
    logical_error_rate_ci95_low NUMERIC(30, 20),
    logical_error_rate_ci95_high NUMERIC(30, 20),
    latency_p50_ns      BIGINT,
    latency_p99_ns      BIGINT,
    throughput_1000_per_second NUMERIC GENERATED ALWAYS AS
                            (CASE WHEN t_1000_ns IS NULL THEN NULL
                                  ELSE 1000000000000::NUMERIC / t_1000_ns::NUMERIC
                             END) STORED,
    logical_error_per_logical_per_round NUMERIC(30, 20),
    soft_output_samples BIGINT,
    soft_output_calibration NUMERIC(30, 20),

    notes               TEXT NOT NULL DEFAULT '',
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    withdrawn_at        TIMESTAMPTZ,

    CONSTRAINT result_state_ck
        CHECK (state IN ('pending_review', 'published', 'withdrawn', 'rejected')),
    CONSTRAINT result_measurement_scope_ck
        CHECK (measurement_scope IN ('accuracy_only', 'accuracy_and_timing')),
    CONSTRAINT result_stim_version_nonempty CHECK (btrim(stim_version) <> ''),
    CONSTRAINT result_input_sha256_ck CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT result_shots_ck CHECK (shots > 0),
    CONSTRAINT result_failures_ck
        CHECK (failures_any_logical >= 0 AND failures_any_logical <= shots),
    CONSTRAINT result_timing_scope_ck CHECK (
        (measurement_scope = 'accuracy_only'
            AND latency_mean_ns IS NULL AND t_1000_ns IS NULL)
        OR
        (measurement_scope = 'accuracy_and_timing'
            AND latency_mean_ns > 0 AND t_1000_ns > 0)
    ),
    CONSTRAINT result_latency_p50_ck CHECK (latency_p50_ns IS NULL OR latency_p50_ns > 0),
    CONSTRAINT result_latency_p99_ck CHECK (latency_p99_ns IS NULL OR latency_p99_ns > 0),
    CONSTRAINT result_latency_order_ck CHECK (
        latency_p50_ns IS NULL OR latency_p99_ns IS NULL OR latency_p50_ns <= latency_p99_ns
    ),
    CONSTRAINT result_ci_pair_ck CHECK (
        (logical_error_rate_ci95_low IS NULL AND logical_error_rate_ci95_high IS NULL)
        OR
        (logical_error_rate_ci95_low BETWEEN 0 AND 1
         AND logical_error_rate_ci95_high BETWEEN 0 AND 1
         AND logical_error_rate_ci95_low <= logical_error_rate_ci95_high)
    ),
    CONSTRAINT result_soft_output_pair_ck CHECK (
        (soft_output_samples IS NULL AND soft_output_calibration IS NULL)
        OR
        (soft_output_samples > 0 AND soft_output_calibration IS NOT NULL)
    ),
    CONSTRAINT result_predecessor_not_self_ck CHECK (predecessor_id <> id),
    CONSTRAINT result_publication_ck CHECK (
        (state IN ('published', 'withdrawn') AND published_at IS NOT NULL)
        OR (state IN ('pending_review', 'rejected') AND published_at IS NULL)
    ),
    CONSTRAINT result_withdrawal_ck CHECK (
        (state = 'withdrawn' AND withdrawn_at IS NOT NULL)
        OR (state <> 'withdrawn' AND withdrawn_at IS NULL)
    ),

    -- These composite keys allow benchmark-attempt membership to be enforced
    -- with foreign keys rather than application-only checks.
    CONSTRAINT result_attempt_identity_uq
        UNIQUE (id, circuit_revision_id, decoder_version_id, machine_id)
);

CREATE UNIQUE INDEX result_supersedes_once_uq
    ON result (predecessor_id)
    WHERE predecessor_id IS NOT NULL;

CREATE INDEX result_circuit_leaderboard_idx
    ON result (circuit_revision_id, state, logical_error_rate);

CREATE INDEX result_decoder_idx
    ON result (decoder_version_id, state, submitted_at DESC);

CREATE INDEX result_timing_leaderboard_idx
    ON result (circuit_revision_id, machine_id, state, latency_mean_ns)
    WHERE measurement_scope = 'accuracy_and_timing';

CREATE TABLE result_artifact (
    result_id           UUID NOT NULL REFERENCES result(id) ON DELETE RESTRICT,
    artifact_id         UUID NOT NULL REFERENCES artifact(id) ON DELETE RESTRICT,
    role                TEXT NOT NULL,
    position            SMALLINT NOT NULL DEFAULT 1,
    PRIMARY KEY (result_id, role, position),
    CONSTRAINT result_artifact_role_ck CHECK (
        role IN ('raw_trace', 'configuration', 'reproduction_bundle', 'other')
    ),
    CONSTRAINT result_artifact_position_ck CHECK (position >= 1),
    CONSTRAINT result_artifact_row_uq UNIQUE (result_id, artifact_id)
);

CREATE TABLE result_link (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id           UUID NOT NULL REFERENCES result(id) ON DELETE RESTRICT,
    kind                TEXT NOT NULL,
    url                 TEXT NOT NULL,
    label               TEXT NOT NULL DEFAULT '',
    position            SMALLINT NOT NULL DEFAULT 1,
    CONSTRAINT result_link_kind_ck CHECK (
        kind IN ('paper', 'source', 'result_archive', 'configuration', 'raw_trace', 'other')
    ),
    CONSTRAINT result_link_position_ck CHECK (position >= 1),
    CONSTRAINT result_link_uq UNIQUE (result_id, url)
);

-- Complete benchmark attempts ----------------------------------------------

CREATE TABLE benchmark_attempt (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    benchmark_revision_id UUID NOT NULL REFERENCES benchmark_revision(id) ON DELETE RESTRICT,
    decoder_version_id  UUID NOT NULL REFERENCES decoder_version(id) ON DELETE RESTRICT,
    machine_id          UUID NOT NULL REFERENCES machine(id) ON DELETE RESTRICT,
    state               TEXT NOT NULL DEFAULT 'draft',
    submitted_by_id     UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    notes               TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at        TIMESTAMPTZ,
    withdrawn_at        TIMESTAMPTZ,
    CONSTRAINT benchmark_attempt_state_ck
        CHECK (state IN ('draft', 'pending_review', 'published', 'withdrawn', 'rejected')),
    CONSTRAINT benchmark_attempt_publication_ck CHECK (
        (state IN ('published', 'withdrawn') AND published_at IS NOT NULL)
        OR (state IN ('draft', 'pending_review', 'rejected') AND published_at IS NULL)
    ),
    CONSTRAINT benchmark_attempt_withdrawal_ck CHECK (
        (state = 'withdrawn' AND withdrawn_at IS NOT NULL)
        OR (state <> 'withdrawn' AND withdrawn_at IS NULL)
    ),
    CONSTRAINT benchmark_attempt_membership_uq
        UNIQUE (id, benchmark_revision_id, decoder_version_id, machine_id)
);

CREATE TABLE benchmark_attempt_result (
    benchmark_attempt_id UUID NOT NULL,
    benchmark_revision_id UUID NOT NULL,
    circuit_revision_id UUID NOT NULL,
    decoder_version_id  UUID NOT NULL,
    machine_id          UUID NOT NULL,
    result_id           UUID NOT NULL,
    PRIMARY KEY (benchmark_attempt_id, circuit_revision_id),
    CONSTRAINT benchmark_attempt_result_attempt_fk FOREIGN KEY
        (benchmark_attempt_id, benchmark_revision_id, decoder_version_id, machine_id)
        REFERENCES benchmark_attempt
        (id, benchmark_revision_id, decoder_version_id, machine_id)
        ON DELETE RESTRICT,
    CONSTRAINT benchmark_attempt_result_item_fk FOREIGN KEY
        (benchmark_revision_id, circuit_revision_id)
        REFERENCES benchmark_revision_item
        (benchmark_revision_id, circuit_revision_id)
        ON DELETE RESTRICT,
    CONSTRAINT benchmark_attempt_result_result_fk FOREIGN KEY
        (result_id, circuit_revision_id, decoder_version_id, machine_id)
        REFERENCES result
        (id, circuit_revision_id, decoder_version_id, machine_id)
        ON DELETE RESTRICT,
    CONSTRAINT benchmark_attempt_result_result_uq
        UNIQUE (benchmark_attempt_id, result_id)
);

CREATE INDEX benchmark_attempt_leaderboard_idx
    ON benchmark_attempt (benchmark_revision_id, machine_id, state, published_at);

-- Moderation history --------------------------------------------------------

CREATE TABLE submission_review (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reviewer_id         UUID NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    decoder_version_id  UUID REFERENCES decoder_version(id) ON DELETE RESTRICT,
    circuit_revision_id UUID REFERENCES circuit_revision(id) ON DELETE RESTRICT,
    machine_id          UUID REFERENCES machine(id) ON DELETE RESTRICT,
    result_id           UUID REFERENCES result(id) ON DELETE RESTRICT,
    benchmark_attempt_id UUID REFERENCES benchmark_attempt(id) ON DELETE RESTRICT,
    action              TEXT NOT NULL,
    note                TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT submission_review_one_subject_ck CHECK (
        num_nonnulls(
            decoder_version_id,
            circuit_revision_id,
            machine_id,
            result_id,
            benchmark_attempt_id
        ) = 1
    ),
    CONSTRAINT submission_review_action_ck CHECK (
        action IN ('submitted', 'requested_changes', 'approved', 'rejected', 'withdrawn')
    )
);
```

## Publication invariants enforced by the application

Some cross-row rules are clearer in one audited publication transaction than
in database triggers. Before moving a row to `published`, the application must
enforce all of the following:

- A `decoder_version` has at least one author.
- A `circuit_revision` has exactly one `manifest` artifact and at least one
  `circuit` artifact. Its manifest digest equals `manifest_sha256` and covers
  every scientifically relevant file and parameter.
- A `benchmark_revision` references only published circuit revisions, and its
  manifest exactly lists its `benchmark_revision_item` rows in position order.
- A result references published decoder, circuit, machine, and evaluator rows.
- The evaluator output file validates against the evaluator release's schema;
  its input digest and every promoted derived value reproduce exactly.
- A superseding result has the same decoder version and circuit revision as the
  result it corrects. Differences in machine or measurement scope must be
  highlighted during review.
- A benchmark attempt has exactly one published result for every required
  benchmark item. Each result's decoder version and machine are guaranteed by
  the composite foreign keys above.
- `parent_revision_id` is only used for genuine nesting (for example, Full
  containing Core); all required parent items must appear in the child revision.
- Published scientific rows reject edits except the explicit state transition
  from `published` to `withdrawn`. A database trigger can be added as defence in
  depth after the Django models stabilize.

## Deliberate non-fields

The schema intentionally does not contain preparation duration, training data,
hyperparameters, stopping rules, sampler seeds, detailed hardware inventories,
energy measurements, arbitrary timing boundaries, or online-adaptation state.
Those remain in papers, linked artifacts, or future versioned extensions.

Likewise, the database does not store an aggregate benchmark score yet. When a
formula is agreed, it should be attached to a new benchmark revision and derived
from its constituent results rather than silently added to historical attempts.

## Open scientific decisions that do not block the schema

The confidence-interval convention, primary latency statistic, soft-output
calibration scalar, and aggregate benchmark formula remain scientific decisions.
Their meanings are versioned by `evaluator_release` and `benchmark_revision`.
The nullable derived columns support the planned v1 outputs without allowing a
formula change to rewrite historical meaning.
