# Submission history and publication projections

Status: implemented 0.1 baseline; retained as the architectural rationale and
review document.

This document records the proposed redesign of Circuit Bench's submission,
review, publication, withdrawal, resubmission, and revision history. The aim is
to make the complete history of an item easy to understand and audit without
making ordinary catalogue, leaderboard, and plotting queries substantially
more complicated.

The proposed design is a hybrid event-led relational model:

- typed scientific records remain the authoritative source of scientific
  content;
- a lightweight history groups related exact records;
- an append-only event stream is the authoritative source of workflow history,
  actors, reasons, and policy decisions;
- frequently queried lifecycle fields remain stored as transactionally updated
  projections of that event stream.

This is deliberately not pure event sourcing. Reconstructing lifecycle state
from events for every catalogue row would make the existing query system less
transparent and harder to constrain. Instead, the event history explains how
the current state arose, while indexed projection fields keep normal relational
queries simple.

## 1. The objects in the model

The model distinguishes three things that must not be conflated.

### 1.1 Exact scientific record

An exact decoder version, circuit revision, result, machine record, noise model,
benchmark revision, or other typed record contains scientific content governed
by an exact schema release.

These continue to live in their existing typed tables, such as:

- `decoder_version`;
- `circuit_revision`;
- `result`;
- `machine`;
- `noise_model`;
- `benchmark_revision`.

No generic revision table replaces these tables. The typed record remains the
scientific object and retains ordinary foreign keys, database constraints, and
efficient type-specific queries.

### 1.2 Record history

A `record_history` is a lightweight provenance and workflow container. It says
that several otherwise independent exact records form one correction or
revision history.

It contains no scientific name, description, score, circuit parameter, or
other scientific content. It exists only to provide one stable scope for an
ordered history.

An illustrative table is:

| Column | Meaning |
| --- | --- |
| `id` | Stable UUID primary key for the history |
| `record_kind` | Decoder, circuit, result, machine, and so on |
| `created_at` | Time the history was created |

Each exact scientific record receives a non-null `history_id` foreign key.

For example:

```text
record_history H1

decoder_version A
    history_id = H1
    state = withdrawn

decoder_version B
    history_id = H1
    predecessor_id = A
    state = pending_reapproval

decoder_version C
    history_id = H1
    predecessor_id = B
    state = published
```

The history is operationally important, especially for withdrawal followed by
resubmission, but it is not presented as an additional scientific entity.

### 1.3 Record event

A `record_event` is an immutable statement that something happened within one
history, normally to one exact record.

An illustrative table is:

| Column | Meaning |
| --- | --- |
| `id` | Event UUID |
| `history_id` | History to which the event belongs |
| `sequence` | Strictly increasing position within that history |
| exact subject | The exact typed record affected by the event |
| `event_type` | Submitted, rejected, approved, published, and so on |
| `actor_type` | `account` or `system` |
| `actor_account_id` | Human actor when `actor_type=account` |
| `actor_system` | Stable system identifier when `actor_type=system` |
| `occurred_at` | Event timestamp |
| `event_schema_version` | Version governing the event details |
| `note` | Optional or required human-readable explanation, by event type |
| `details` | Versioned structured JSON for event-specific information |
| `payload_snapshot` | Optional canonical submitted-data snapshot |

The pair `(history_id, sequence)` is unique. Sequence, rather than timestamp,
is the authoritative order. Timestamps remain useful information but are not
relied upon to disambiguate several events written in one transaction.

The existing design's explicit typed subject foreign keys are preferable to a
Django generic foreign key. A database check should continue to require exactly
one exact subject where the event type requires one.

## 2. Actor representation

Every action must state whether it was performed by a human account or by an
automatic system process.

The actor constraint is:

```text
actor_type = account
    => actor_account_id is non-null
       and actor_system is null

actor_type = system
    => actor_account_id is null
       and actor_system is non-null
```

Examples of `actor_system` include `submission_policy` and
`publication_reconciler`. Policy version and the exact rule applied belong in
the event's structured details.

This is preferable to a fictional Account named “System”. A system process
cannot authenticate, receive scientific credit, own a submission, or link a
GitHub or ORCID identity.

An automatic approval event might contain:

```json
{
  "policy_version": "0.2",
  "approval_route": "immediate_publication",
  "reason": "Machine records do not require human review"
}
```

## 3. Event vocabulary

The initial event vocabulary should include at least:

- `submitted`;
- `edited`;
- `requested_changes`;
- `rejected`;
- `resubmitted`;
- `approved`;
- `published`;
- `withdrawn`;
- `restored` or `republished`, if administrative restoration is permitted;
- `revision_created`;
- existing curation actions such as `promoted_official`, `deprecated`, and
  `merged`;
- an administrative credit-claim override where appropriate.

Publication approval and publication are separate events. This permits the
history to distinguish the decision from the act which made the record public.

A `published` event should identify, directly or through a causation link, the
approval event that authorised it. Consequently “approved by” is derived from
the approval event relevant to that publication episode rather than from a
mutable column on the scientific record.

## 4. Revision relationships

Only one direction of a revision relationship is stored authoritatively.

For example:

```text
revision_created
    subject_revision = B
    predecessor_revision = A
```

The user interface may then display both:

- “B was revised from A”; and
- “A was revised to B”.

There must not be separately writable `revised_from` and `revised_to` facts,
because they could disagree.

The existing predecessor or supersession foreign keys should initially remain
on the typed scientific records:

- `predecessor_id`;
- `predecessor_id`;
- `predecessor_id`;
- `predecessor_id`;
- `predecessor_id`.

They are useful queryable projections of the `revision_created` event and
allow PostgreSQL to enforce referential and cardinality constraints. The write
service updates the event and relationship field in the same transaction. A
consistency validator verifies that they agree.

Once a record has been published, a scientific correction creates a new exact
record in the same history. The predecessor remains immutable.

Decoder and circuit successor submission has an explicit publication choice.
The normal choice leaves the predecessor published alongside the new candidate.
The replacement choice records withdrawal of the published predecessor and
creates its successor in `pending_reapproval` in the same database transaction.
In both cases the predecessor's scientific fields and permanent identity remain
unchanged.

Withdrawal followed by resubmission therefore behaves as follows:

1. exact record A receives a `withdrawn` event and remains withdrawn;
2. exact record B is created in the same history and linked to A;
3. B receives `revision_created` and `resubmitted` events;
4. B enters `pending_reapproval`;
5. approval and publication affect B, not A.

An exceptional restoration of an accidentally withdrawn record, with no
scientific change, may be represented by a `restored` or `republished` event on
the same exact record. This should be a distinct administrative operation, not
silently treated as a revision.

## 5. Submission snapshots

An event history is only a complete review history if it preserves what was
actually reviewed.

If pending records remain editable in place, every `submitted`, `edited`, or
`resubmitted` event must retain an immutable canonical payload snapshot or a
content-addressed reference to one.

For example:

```text
submitted       payload snapshot 1
rejected        review of snapshot 1
resubmitted     payload snapshot 2
approved        approval of snapshot 2
```

Without snapshots, the history could show that a reviewer rejected something
but only retain the later values which were eventually approved.

Snapshots should contain the canonical versioned submission representation,
including exact schema version and immutable artifact identifiers. Uploaded
files should not be copied into each event; their artifact UUIDs and SHA-256
identities are sufficient.

For small submission payloads, a versioned JSONB snapshot is likely the
simplest implementation. If snapshots become large, the same logical field can
point to a content-addressed artifact instead.

## 6. Lifecycle events and projections

The event stream is authoritative for lifecycle transitions, actors, reasons,
and policy decisions. Frequently queried values remain stored on exact records
as projections.

### 6.1 Stored projections

The following should remain ordinary indexed columns:

- `state`;
- `published_at`;
- `withdrawn_at`;
- `submitted_by_id`;
- `created_at`;
- predecessor or supersession foreign key.

This preserves simple queries such as:

```python
DecoderVersion.objects.filter(state="published")
Result.objects.filter(state="published").order_by("-published_at")
```

The catalogue, result-query language, leaderboards, plots, and publication
eligibility checks should not have to replay event histories.

### 6.2 Values derived from events

The following normally need not be stored independently:

- who reviewed the item;
- who approved its current publication;
- whether approval was human or automatic;
- which policy version authorised publication;
- rejection and requested-change reasons;
- submission and review cycle counts;
- who withdrew the item and why;
- the full public history timeline.

For a detail page, the complete history can be prefetched in one ordered query.
For a table which needs approver information on many rows, the queryset can use
a bounded prefetch or annotation rather than performing one query per row.

### 6.3 Transaction rule

Every transition service writes the event and projections atomically.

For publication:

```text
1. append the approved event, when required;
2. append the published event;
3. set record.state = published;
4. set record.published_at = published_event.occurred_at;
5. clear record.withdrawn_at where the transition permits it;
6. commit all changes together.
```

If any part fails, none of the changes commit.

Lifecycle fields must not be modified directly by ordinary view or form code.
All transitions go through the central transition service.

## 7. Example complete history

Consider this sequence:

1. Alice submits an item;
2. Bob reviews and rejects it;
3. Alice revises and resubmits it;
4. a policy automatically approves and publishes it;
5. Alice withdraws it;
6. Alice submits a successor for reapproval;
7. Carol approves and publishes the successor.

The history contains:

| Sequence | Exact record | Event | Actor |
| ---: | --- | --- | --- |
| 1 | A | `submitted` with snapshot 1 | Alice |
| 2 | A | `rejected` with reason | Bob |
| 3 | A | `resubmitted` with snapshot 2 | Alice |
| 4 | A | `approved` with policy details | System |
| 5 | A | `published` | System |
| 6 | A | `withdrawn` with reason | Alice |
| 7 | B | `revision_created`, predecessor A | Alice |
| 8 | B | `resubmitted` with snapshot 3 | Alice |
| 9 | B | `approved` | Carol |
| 10 | B | `published` | Carol |

The exact A row ends in `withdrawn`. The exact B row ends in `published`. Both
refer to the same `record_history`. No event or scientific record is deleted.

## 8. Reusable record-history interface

Every scientific data page should include the same reusable record-history
component. It should work for decoders, circuits, results, machines, noise
models, benchmarks, and future record kinds without duplicating templates or
JavaScript.

The component is primarily a timeline, not a card deck. It should follow the
site's compact scientific-reference design:

- square-edged rows or grid cells;
- restrained rules and theme-derived colours;
- compact serif-led typography;
- no large decorative icons or excessive spacing;
- accessible text labels rather than colour-only meanings.

### 8.1 Default presentation

The header should state “Submission history” and provide show/hide behaviour.
It should be expanded by default on an exact data page unless later usability
testing suggests otherwise.

Each event row should show, in a consistent order:

1. date and time;
2. action;
3. human account or named system actor;
4. concise note or reason;
5. exact revision affected;
6. links to related earlier or later revisions where applicable.

System events should visibly say “System”, followed by the relevant policy or
component where useful. They should not masquerade as user actions.

### 8.2 Event details

Events with more information should have a compact expandable detail region
showing:

- complete review note;
- policy version and approval route;
- exact payload-snapshot link or comparison;
- causation and related event;
- source and successor revision links;
- whether a fact was migrated or inferred rather than observed live.

A payload comparison may later offer a human-readable field diff, but the
canonical snapshots remain the audit source. A diff is a derived view.

### 8.3 Revision navigation

The component should make lineage clear without presenting the history
container as a scientific object. On revision A it may say:

```text
Revised to B
```

and on revision B:

```text
Revised from A
```

Both labels are generated from the single authoritative revision relationship.

### 8.4 Permissions

The same component should support different event visibility levels:

- public events on public data pages;
- uploader-visible submission details and payload snapshots;
- administrator-only internal review notes where necessary.

Visibility should be an explicit event/detail policy, not an accidental result
of which template rendered the data.

The component itself is read-only. Edit, withdraw, resubmit, approve, or reject
controls may appear beside relevant events or in the page's action area, but
those controls invoke central transition services.

### 8.5 Reuse boundary

The reusable implementation should consist of:

- one history-query/presentation service returning a stable event-view model;
- one shared template component;
- small optional disclosure behaviour shared with the rest of the site;
- no record-kind-specific lifecycle logic in the template.

Record-specific label and URL functions may be injected by the presentation
service.

## 9. Query and performance consequences

The proposed hybrid does not require rewriting the existing scientific query
system. Public collections continue to filter stored lifecycle projections.

Additional costs are limited to pages which display history:

- one history query for an exact data page;
- bounded prefetches or annotations where a table displays event-derived data;
- no per-row history replay in leaderboards or plots.

Useful indexes include:

- unique `(history_id, sequence)`;
- `(history_id, occurred_at)`;
- event subject foreign keys;
- `(event_type, occurred_at)` for administration and recent-activity queries;
- `actor_account_id` where non-null;
- existing indexes on record `state` and `published_at`.

The event list may grow indefinitely, but expected Circuit Bench traffic and
submission volumes are modest. Pagination can be added to unusually long
histories without changing the model.

## 10. Consistency validation

A `validate_histories` management command should replay every history and check:

- event sequences are continuous and unique;
- actor constraints hold;
- event transitions are legal;
- stored `state` agrees with the event stream;
- `published_at` agrees with the applicable publication event;
- `withdrawn_at` agrees with the applicable withdrawal event;
- predecessor fields agree with `revision_created` events;
- all exact records in one history have the same record kind;
- approval and publication causation is resolvable;
- payload snapshots identify their exact submission schema;
- no published scientific record has been edited in place.

This command should run in tests and deployment checks. It also provides a safe
way to detect mistakes introduced by migrations or administrative scripts.

## 11. Migration plan

The migration should be incremental so existing read queries continue to work
throughout.

### Phase 1: introduce history tables

Create `record_history` and `record_event`. Add nullable `history_id` foreign
keys to supported scientific record tables. Existing code continues using the
current lifecycle fields.

### Phase 2: backfill histories

- isolated records receive individual histories;
- existing predecessor and supersession chains share a history;
- branches, cycles, or inconsistent record kinds are reported rather than
  silently interpreted;
- after validation, `history_id` becomes non-null.

### Phase 3: migrate existing record events

Existing record events should retain their identities where practical and
gain history, sequence, exact actor type, and event schema information.

Human actor rows can be migrated directly. Existing automatic publications
incorrectly attributed to submitters must not be silently rewritten as known
system actions. Development fixtures may be regenerated; retained historical
rows should explicitly mark any inference in structured details.

### Phase 4: synthesise missing history

Where old records lack events, generate explicitly marked migration events from
existing `created_at`, `submitted_by_id`, `published_at`, `withdrawn_at`, and
predecessor fields. Inferred events remain distinguishable from events captured
at the time.

### Phase 5: replace direct state mutation

Submission, review, approval, publication, withdrawal, restoration, and
resubmission services begin appending events and updating projections in one
transaction. Direct state mutation outside those services is removed.

### Phase 6: integrate the interface

Add the shared record-history component to every exact public data page and
to the corresponding private submission view. Apply explicit public, uploader,
and administrator visibility rules.

### Phase 7: validate and enforce

Run the consistency command, add final non-null and uniqueness constraints, and
make event records immutable through the normal application interface.

## 12. Expected disruption

| Area | Expected change |
| --- | --- |
| Discovery queries | Very small; continue using projected state |
| Leaderboards and plots | Essentially none |
| Detail queries | Add one bounded history prefetch |
| Submission services | Significant but contained rewrite |
| Approval and withdrawal services | Significant and central to the redesign |
| Database models and migrations | Moderate |
| Data-page templates | Add one shared component include |
| Tests | Add transition, sequence, projection, migration, and visibility tests |
| Current development fixtures | Regenerate or deterministically backfill |
| Future production migration | More delicate; therefore preferable to do now |

## 13. Decisions and remaining questions

The current proposal makes these decisions:

1. Exact typed records remain the scientific objects.
2. A history is a lightweight provenance container, not a generic scientific
   record.
3. Events are authoritative for workflow, actor, reason, and policy.
4. Lifecycle fields and predecessor links remain queryable projections.
5. Human and system actors are represented explicitly.
6. Only one direction of revision linkage is authoritative.
7. Submission and resubmission snapshots preserve what was actually reviewed.
8. Every exact data page receives the same reusable record-history UI.

Questions to settle during implementation include:

- whether histories cover every publishable model immediately or initially only
  decoder, circuit, result, and machine;
- whether pending edits generate full snapshots on every edit or only on each
  formal submission/resubmission boundary;
- whether administrative restoration of an unchanged withdrawn record is
  allowed;
- which review notes and payload details are public, uploader-visible, or
  administrator-only;
- whether the existing `record_event` table is evolved in place or migrated
  into a newly named `record_event` table;
- how event payload schemas themselves are versioned and documented.

These questions do not alter the central architecture and can be resolved
incrementally.

### 13.1 Decisions made for the 0.1 implementation

- Histories cover decoder versions, circuit revisions, results, machines,
  noise models, benchmark revisions, tags, and evaluator releases immediately.
- Every formal submission, resubmission, and pending edit written by the new
  workflow receives a complete canonical JSON snapshot. Legacy events without
  recoverable payloads are explicitly marked as migration inferences.
- Restoration of an unchanged withdrawn record is not exposed to ordinary
  users in 0.1. A successor is the normal route back to publication.
- Public events are visible on public data pages. The data model also supports
  uploader-only and administrator-only event details, although the first
  submission paths currently write public notes.
- The existing `record_event` table was evolved in place and remains named
  `RecordEvent` in Django so existing provenance is preserved.
- Event payloads use the documented `0.1` envelope containing `schema`, `data`,
  and immutable artifact identities. Later event shapes require a new
  `event_schema_version`.
