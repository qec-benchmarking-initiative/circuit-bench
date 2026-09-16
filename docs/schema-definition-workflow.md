# Versioned submission definitions

Definitions are edited in Git, not through database forms. The database stores
immutable archived copies and connects each scientific record to its release.

## Files

- `schemas/current.json` selects the release required for each kind of new submission.
- `schemas/<kind>/<version>.schema.json` is an immutable release. Its
  `x-submission-schema` is the write-side JSON Schema; `x-definitions` identifies
  the YAML path, version and SHA-256. `x-form-definitions` maps form fields to entries.
- `definitions/<kind>/<version>.yaml` contains `is_guidance`, `summary`, and
  `expanded` (Markdown or null) for each entry. Summaries are visible beside fields;
  expanded text appears in an initially collapsed panel with its definitions version.

A new schema may reference an existing definitions YAML unchanged. Schema and
definitions version numbers need not match. The current decoder 0.2 and 0.3 examples
deliberately differ only in provisional description guidance.

## Release procedure

1. Copy the definitions YAML to a new version and edit the necessary entries.
2. Copy the JSON Schema to a new version. Update its identity, record schema
   constant, submission `schema_version` constant, definition references and hash.
   Obtain the hash with `shasum -a 256 definitions/decoder/0.4.yaml`, for example.
3. Archive the pair using
   `python manage.py install_schema_contracts decoder/0.4 --uploader ACCOUNT_UUID`.
   Reinstalling identical contents is safe; changing an installed version fails.
4. Change the decoder entry in `schemas/current.json` to `0.4`. Deploy the files and
   install the release before switching the running application's current selector.

The older `load_schema_releases` command is for legacy Markdown/draft releases;
use `install_schema_contracts` for the new YAML contracts. Never rewrite an old
release to correct its definitions: publish a new version.

## Submission and approval

Forms carry a hidden version token, and JSON submissions carry `schema_version`.
These detect stale forms; they do not authorize use of an old schema. Validation
and final submission require the currently selected version. If the selector
changes during editing or preview, the user must refresh and review the new definitions.

An accepted submission stores a foreign key to its immutable release. Its history
snapshot records the release UUID, schema version and both content hashes. Editing
a pending submission uses the current release and adds a new snapshot; earlier
snapshots remain available.

Approval validates against the submission's recorded release, not today's selector.
The review table and submission detail show an older-schema warning but do not
block approval on that basis. File checks, reference availability and ordinary
publication rules still apply. Definitions pages read the archived copy once it
exists, even if working-tree files subsequently change or disappear.

## Provisional coverage and examples

Decoder, circuit, result and machine submissions use the new archived write
contracts. Other record kinds retain their existing 0.1 contracts. All submission
visibility choices use the shared radio-button styling.

The historic 0.1 seed releases contained placeholder documents rather than a
complete archived write contract. Their compatibility validator remains the old
Python specification; this limitation is not retroactively disguised. New
releases archive the actual contract.

On a development database, `python manage.py seed_schema_demo` installs the sample
releases and creates two pending decoder 0.2 submissions plus one current 0.3
submission (the latest example uses schema 0.5 with definitions 0.3). It also adds noise parameters to existing circuit names and slugs,
preserving old page URLs through redirects. It is idempotent and refuses to run
with DEBUG disabled.
