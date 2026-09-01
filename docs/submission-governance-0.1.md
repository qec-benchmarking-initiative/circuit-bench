# Submission and approval policy 0.1

Status: implemented development contract, 31 August 2026.

The canonical user-facing policy is
[`content/pages/submission-policy.md`](../content/pages/submission-policy.md).
This document records the corresponding implementation contract for Circuit
Bench. It does
not alter the frozen scientific record schemas. Submission input schemas are a
separate interface: they describe what a user supplies, while the application
assigns record UUIDs, the frozen scientific schema release, uploader, lifecycle
state, and timestamps.

## Policy decision

Every valid submission receives one explicit approval route before it is
stored. Policy 0.1 has two routes:

| Record kind | Route | Initial lifecycle state |
| --- | --- | --- |
| Decoder version | Admin review | `pending_review` |
| Circuit revision | Admin review | `pending_review` |
| Result | Admin review | `pending_review` |
| Machine | Immediate publication | `published` |

Admin status does not currently bypass review: a decoder, circuit, or result
submitted by an admin still enters `pending_review`. A machine submitted by any
active account publishes immediately after validation.

The decision is made by `registry/submission_policy.py`. Its interface accepts
both record kind and submitter even though policy 0.1 only varies by kind. This
leaves an explicit extension point for later trusted-uploader, uploader-owner,
or per-kind rules without embedding those rules in forms or views. Every
submission audit event records the policy version and chosen route.

## Entry and preview

Each supported kind has two entry surfaces:

1. a labelled structured form;
2. a raw JSON object with a linked Draft 2020-12 submission schema.

Both surfaces converge on the same semantic Django form validation before a
preview is created. The JSON path first applies its JSON Schema and then the
shared semantic validation. A preview is stored in the submitting user's
server-side session; it is not a scientific database record. “Back and edit”
restores the canonical payload. The final POST revalidates the payload inside
the creation transaction.

## Publication-sensitive references

A result can be submitted only when all four referenced records already exist
and are published:

- decoder version;
- circuit revision;
- evaluator release;
- machine.

The machine field is required by this submission interface even though the
underlying 0.1 result model permits a null machine. A pending decoder or circuit
therefore cannot be used to create a pending result. This avoids a dependency
graph inside the moderation queue.

The same reference checks run again when an admin approves a pending result.
If a referenced record has been withdrawn or otherwise ceased to be published,
approval fails and the result remains pending. Circuit approval likewise
rechecks its noise model and previous revision; decoder approval rechecks its
previous version.

## Transactions and audit

Final submission creates the scientific record, tag memberships, score rows,
and uploader credit (where the credit model supports that kind) in one database
transaction. It also creates a `submitted` moderation event.

Admin approval locks the pending record, revalidates it, sets `published_at`,
and creates `approved` and `published` moderation events in one transaction.
Immediate machine publication creates `submitted`, `approved`, and `published`
events in the creation transaction. The approval event is attributed to a
reserved inactive `System` account; manual approval is attributed to the exact
admin account. Machines have an uploader but no credit row because
the existing credit model does not define machine as a credit subject.

## Editing, succession, and withdrawal

`pending_review` and `pending_reapproval` are unpublished candidate states.
Their uploader or an admin can edit scientific fields in place while retaining
the candidate UUID; every stored edit creates an `edited` moderation event.

Published and withdrawn scientific records are immutable. Editing a published
record therefore creates a new record linked through its kind-specific lineage
field. Withdrawing a published record preserves its publication timestamp,
sets `withdrawn_at`, and writes a reasoned `withdrawn` event. A successor to a
withdrawn record enters `pending_reapproval`, even for machines that would
normally publish immediately, and the predecessor receives a `resubmitted`
event naming the successor UUID.

## Visibility and permissions

- Profile, submission, preview, and exact pending-record pages require sign-in.
- An exact pending record is visible only to its uploader and admins.
- The admin queue and approval POST require an active admin account.
- The admin page lists only records waiting for review and records withdrawn
  during the preceding seven days; it is not a duplicate public catalogue.
- Published records link to their ordinary public scientific data pages.
- The local prototype account switcher is present only with `DEBUG=True` and
  only permits the two deterministic demo account UUIDs.

## Deliberately deferred

Policy 0.1 does not yet implement rejection, requested changes, notification,
tag/noise-model/benchmark submission, credit claims, uploader-scoped
moderation, or evaluator-summary ingestion. Those can reuse the exact-record
view, queue table, moderation-event service, and policy boundary added by this
slice.
