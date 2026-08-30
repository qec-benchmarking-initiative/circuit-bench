# Physical Django model mapping

Status: foundation decision for implementing `docs/data-model-0.1.md`.

This note fixes implementation choices that are deliberately below the public
scientific contracts. Changing one of these choices requires a reviewed Django
migration; it does not by itself create a new scientific schema release.

## Runtime and applications

- Python 3.11 is the development baseline already present on the workstation.
- Django 5.2 LTS is pinned to its latest compatible patch by `uv.lock`.
- PostgreSQL is used in development and production. SQLite is not configured.
- `accounts` owns the custom Django user and application identity projection.
- `registry` owns all highly interconnected scientific, attribution, artifact,
  benchmark and governance tables. Its Python models are split into topic
  modules, but it has one Django migration graph.
- `pages` owns the shared shell, structural page layouts and development
  component gallery. It contains no scientific persistence.

Keeping scientific tables in one Django app avoids artificial circular
migration dependencies caused by credits, attachments, moderation subjects,
benchmark attempts and results all referencing one another. Topic modules and
service modules provide code boundaries without pretending the relational
graph is less connected than it is.

## Accounts and authentication

`accounts.Account` is the Django `AUTH_USER_MODEL` and maps to the `account`
table. Its public/application fields are exactly the fields in the relational
model.

Django's authentication interface requires a credential-state column and a
last-login hook. The physical model therefore inherits Django's `password` and
`last_login` operational columns. Local password login, signup, reset and
change views are disabled. Every account receives an unusable-password marker;
the database never contains a local password hash. `last_login` is operational
session metadata and is not exposed as scientific or public account data.

The account UUID is Django's internal `USERNAME_FIELD`; it is never presented
as a username or accepted by a login form. `is_staff` and all permission checks
are derived from `is_admin`. Administrators authenticate through GitHub or
ORCID like every other user. A later bootstrap command may promote an existing
account; there is no password-bearing superuser path.

`django-allauth` is configured with:

- social-account-only mode;
- GitHub and ORCID providers only;
- no username or email field on the application account;
- no email-based matching or automatic merging;
- no retained OAuth access/refresh tokens;
- POST initiation for provider login;
- application credentials supplied through environment variables, not rows in
  the database.

Allauth's `socialaccount_socialaccount` and related tables are private OAuth
protocol bookkeeping. They are not public identity records. A social adapter
updates the explicit `external_identity` application table after a successful
provider authentication. That table contains the stable provider subject,
provider-derived public identifier/profile URL and authentication timestamps
defined by the relational model. Linking and unlinking update both
representations atomically. A provider identity is never merged by name or
email, and the last linked identity cannot be removed.

The allauth application is configured not to create or persist token rows.
Should a future library release create an empty token table through its own
migrations, that table remains unused operational infrastructure rather than a
contradictory scientific record.

## Scientific and supporting tables

All UUID primary keys use `uuid.uuid4` in the Django application. PostgreSQL
types, exact decimals, timestamps, JSON and hashes follow the conventions in
the relational model. Scientific foreign keys and audit foreign keys use
`on_delete=PROTECT`, Django's representation of `ON DELETE RESTRICT` behaviour
for application operations.

The explicit nullable subject foreign keys in credits, attachments, links and
moderation events remain explicit columns. They are not replaced by Django's
generic foreign keys. `CheckConstraint` enforces exactly one subject where the
relational model requires it, and per-subject conditional `UniqueConstraint`
objects enforce visible ordering and uniqueness.

Enum-like values use `TextChoices` for application ergonomics plus database
check constraints. Text lengths, non-blank rules, arithmetic identities,
ranges, lifecycle timestamp consistency and straightforward uniqueness rules
are database constraints wherever PostgreSQL can express them reliably.

## Rules enforced at publication time

The following are intentionally not hidden in database triggers:

- schema-release record-type compatibility and frozen status;
- existence and recomputed digest of artifact bytes;
- linear-history acyclicity and lineage-wide version-label uniqueness;
- root descriptions and visible-credit minimums;
- tag namespace compatibility;
- JSON Schema and hyperparameter validation;
- Stim parsing, DEM regeneration and derived circuit facts;
- manifest equality;
- cross-record result capability checks and evaluator-summary validation;
- derived reproduction status;
- benchmark manifest and complete-attempt validation;
- immutability transitions for published scientific records.

These rules belong to explicit transactional publication services with focused
tests. Ordinary database constraints still protect every invariant they can
express without procedural traversal or external artifact inspection.

## Public query model

The future `ResultRecord` query surface is a versioned projection, not direct
exposure of Django or PostgreSQL field names. Its field catalogue will map
stable public names to typed ORM expressions and definition URLs. The browser,
JSON API and CSV export will use the same parser and projection. Storage
migrations may therefore occur without silently changing the public query
language.

## Migration ownership

Only the integration owner generates or edits migrations while parallel work
is active. Parallel agents may add services, tests and page code against the
frozen models, but may not independently alter model fields, shared settings,
root URLs or migration dependencies. Proposed schema changes return to the
integration owner as a small documented request.

