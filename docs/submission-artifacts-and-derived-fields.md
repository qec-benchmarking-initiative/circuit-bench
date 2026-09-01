# Submission artifacts and derived scientific fields

Status: artifact upload implemented for the 0.1 submission form; derived-field
automation is an evaluator-framework plan.

## Artifact handling now

Artifact inputs are not placeholders. A submitter can either choose an existing
frozen artifact or upload a new file alongside the relevant field. Before the
preview is created, Circuit Bench:

1. streams the bytes through the existing size-limited artifact service;
2. computes SHA-256 and byte size;
3. stores the bytes under their content address;
4. reuses an existing artifact row when identical bytes already exist;
5. places the immutable artifact UUID in the canonical submission payload; and
6. records UUID, SHA-256, byte size, media type, and original filename in the
   submission-event snapshot.

The initial submission limit is 1 MiB per artifact. It is deliberately a
configuration/policy limit rather than a schema fact and can be raised for
larger circuits after realistic fixtures are measured. Production object
storage can replace the local storage backend without changing artifact UUIDs
or submission payloads.

Uploading happens before preview. Cancelling a preview can therefore leave an
unattached, content-addressed artifact. This is safe but consumes storage. A
later housekeeping command should remove artifacts which have had no database
reference and no live preview for a conservative grace period. It must never
delete an artifact referenced by a record, schema release, attachment, or
history snapshot.

## Derived quantities

Counts such as circuit detectors, errors, and observables are naturally derived
from the frozen circuit and detector-error-model artifacts. They remain
submitter-reported and semantically validated in schema 0.1 because Circuit
Bench does not yet have a frozen evaluator capable of deriving them.

They should not be implemented as PostgreSQL generated columns or model save
hooks: deriving them requires parsing versioned scientific formats and may
depend on a particular Stim/evaluator release. The boring, auditable design is:

1. freeze all source artifacts;
2. run a named, frozen evaluator release outside the request transaction;
3. store its canonical JSON report as an artifact;
4. record an immutable evaluator-run row containing evaluator release, exact
   input artifact UUIDs and hashes, output report artifact, status, and times;
5. transactionally copy frequently queried derived facts into the ordinary
   circuit columns as projections; and
6. retain the evaluator-run foreign key so every projected number has exact
   provenance.

During submission, the preview will eventually show reported and derived values
side by side. A mismatch blocks submission or requires an explicit documented
override. Once the evaluator is stable, the derived fields become read-only in
the structured form; the JSON contract may continue to accept asserted values
for reproducibility but must require equality with evaluator output.

This follows the same hybrid rule as publication history: immutable evidence is
authoritative, while common numerical fields remain indexed relational
projections for catalogues, queries, tables, and plots.
