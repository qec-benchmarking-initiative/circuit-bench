# History model cleanup

## Decision

Make the database vocabulary match the model we already use:

1. Rename `ModerationEvent` to `RecordEvent` and `moderation_event` to
   `record_event`.
2. Represent every revision lineage with the same nullable, unique
   self-reference: `predecessor_id`.

This is a clarification of the existing design, not a move to pure event
sourcing.

## Why

`ModerationEvent` now records submission, editing, publication, withdrawal,
revision creation, curation, and system actions. Moderation is only one part of
that job, so the current name is misleading.

Likewise, `previous_version`, `previous_revision`, and `supersedes_*` all now
perform the same structural job: they identify the immediately preceding exact
record in a shared `RecordHistory`. Different names and cardinalities obscure
that fact and currently allow some histories to branch accidentally.

## Resulting shape

```text
RecordHistory H1
    exact record A: predecessor_id = null
    exact record B: predecessor_id = A
    exact record C: predecessor_id = B

RecordEvent E1
    history_id = H1
    subject = exact record B
    action = revision_created
```

Every predecessor relationship must be:

- a self-FK to the same exact-record table;
- nullable only for the root;
- unique when non-null, so the history is linear;
- within the same `RecordHistory`;
- non-self and acyclic; and
- consistent with its `revision_created` event.

Human-facing language may remain domain-specific: “previous decoder version”,
“previous circuit revision”, or “superseded result”. Only the relational
mechanism is standardised.

## Enforcement

PostgreSQL should enforce referential integrity, non-self links, uniqueness,
and the controlled event vocabulary. Transactional write services should
enforce same-history links, valid event transitions, and atomic updates to
lifecycle projections. `validate_histories` should continue to verify the full
chain, event causation, and projection agreement.

The event action vocabulary remains unchanged during this rename. Renaming the
model/table and normalising predecessor fields should be performed with data
migrations that preserve every UUID, timestamp, event sequence, and foreign-key
relationship.
