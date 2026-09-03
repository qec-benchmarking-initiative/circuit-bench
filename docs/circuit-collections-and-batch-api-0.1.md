# Circuit collections, batch ingestion, API access, and visibility 0.1

Status: implementation contract for the development prototype.

## Domain distinctions

A circuit tag is a classification selected by the circuit submitter. A circuit
collection is an editorial container curated by the collection owner. Adding a
circuit to a collection does not mutate the circuit, assert endorsement by its
submitter, or confer authority over it.

A collection contains exact circuit revisions and may contain child
collections. A child may occur in several containing collections. Containment
must be acyclic. Only the owner of the containing collection, or an
administrator, can alter its direct circuit and child-collection memberships;
including a child never grants authority over the child's contents.

Collections have a name, slug, brief description, public/private visibility,
owner, lifecycle timestamps, code classification and experiment tags. Code
classification may use Circuit Bench tags and ECZ terms. These tags describe
the collection and are not inherited by its members. Collections have no
scientific parameter, scoring, or sweep schema.

## Collection visibility and result scope

A collection page lists its direct child collections and direct circuit
members. It embeds the standard result comparison surface scoped to results
whose exact circuit is a member. `include_descendants=true`, selected by
default, includes circuits reachable through any descendant collection and
deduplicates circuits and results reached by several paths.

The same scope is used by HTML, JSON, and CSV endpoints. Stable collection IDs
and slugs are accepted by documented discovery endpoints.

## Batch intake

A circuit batch is an import and review envelope, not a scientific record. One
batch may create collections and tags and submit many independently reviewable
circuit revisions. Invalid members do not become records. Review decisions are
per circuit, although the shared bulk-action component may approve or reject a
validated selection.

The canonical API flow is:

1. upload content-addressed files;
2. submit a Draft 2020-12 circuit-batch manifest for validation;
3. resolve existing and proposed tags and collections in a preview;
4. preview every proposed creation; and
5. commit the unchanged validated manifest using its digest and an idempotency
   key.

The browser accepts a manifest plus multiple `.stim` files or ZIP files
containing `.stim` files. File count, uploaded and expanded sizes, normalized
paths, and duplicate leaf names are checked before parsing. Browser and API
entry call the same domain service.

The manifest keys circuit objects by exact uploaded filename and uses stable
client references.
It may contain shared defaults, existing references, proposed custom tags,
proposed collections, collection-contained circuit references, and circuit
submission payloads. Exact database references are never selected by fuzzy
matching. Suggestions are advisory and unresolved or ambiguous references
block commit.

Preview creates no circuit, tag, or collection records. It reports missing and
unused files, normalized values, derived Stim values, proposed creations, and
the canonical manifest digest. Uploaded content-addressed bytes may remain
unattached until normal garbage collection if a preview is abandoned.

## Stim ingestion

The ingestion service parses each frozen `.stim` circuit with a pinned Stim
release, generates its detector error model using every explicitly recorded
argument, derives detector/error/observable counts, and stores a canonical
per-circuit manifest. Generated files and reports are immutable artifacts. The
batch manifest is an import instruction and never substitutes for a circuit's
scientific manifest.

## Personal API tokens

Accounts continue to sign in only through GitHub or ORCID. An authenticated
session may create a named, expiring personal API token with independently
selectable scopes. Version 0.1 requires `circuits:submit` for every batch;
`collections:write` is additionally required when its manifest creates
collections or changes collection membership, and `tags:write` when it creates
tags.
The full bearer token is shown once. The database stores a public lookup ID and
SHA-256 digest of a 256-bit random secret, never the secret itself.

Clients send `Authorization: Bearer <token>` over HTTPS. Tokens are revocable,
expire, record throttled last-use time, inherit account activation, and never
authorize administrator review or identity changes. API actions retain the
ordinary account actor.

Public schemas, examples, discovery, results, and stateless manifest checks do
not require authentication. Uploads, persistent previews, private status, and
writes require either a browser session with CSRF protection or a bearer token.

Every general, single-circuit, and batch submission page visibly links the API
guide, schemas, and token settings under the label `Agent-friendly API`.

## Public and private records

Contributor-created records carry explicit `public` or `private` visibility.
Approval and visibility are independent: administrators can review private
records, and approval leaves them private. Private records and their files are
visible only to their submitter and administrators. Submission pages warn that
administrators can inspect private candidates.

Visibility changes are audited metadata changes and do not create scientific
revisions. A record whose public presentation depends on a private record is
not effectively public, without mutating the dependent record's own visibility
choice. This prevents a private circuit from leaking through a public result.

A record required by a published official benchmark, including its dependency
closure, cannot be made private or withdrawn. Official promotion checks the
same invariant transactionally.

## Reusable bulk actions

Shared record tables may opt into checkbox selection of displayed records, an
action chooser, and an exact confirmation preview. Contributor actions are
`make public`, `make private`, and `withdraw`.
Administrator review actions are `approve` and `reject`; rejection requires a
review note.

Selecting a collection as a group target may include descendants, but expands
only to records the actor is independently authorized to change. The preview
lists the exact target set. An invalid, foreign-owned, benchmark-locked, or
stale target prevents the whole operation. Commit revalidates the exact target
set, and every changed record gets its normal append-only event.

Changing the collection record alone and applying an action to its contents are
separate, explicitly labelled choices.
