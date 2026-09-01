---
title: About Circuit Bench
summary: This page explains what the registry records and how it preserves the meaning of scientific quantities.
---

Circuit Bench is a compact public reference work for evidence about quantum error-correction circuits and decoders. It is meant to make two claims equally easy to inspect: “this decoder performs well on these circuits” and “this circuit performs well under these decoders.”

## What the registry records

- A decoder version states its preparation requirements, probability-output capability, algorithmic tags, and hyperparameter definitions.
- A circuit revision fixes its noise model, tags, structural counts, Stim detector-error-model construction parameters, and immutable circuit, DEM, and manifest files.
- A result connects one exact decoder version to one exact circuit revision, evaluator release, and, when reported, one exact machine record.
- A benchmark is a curated ordered set of required and optional circuit revisions. It does not erase the individual results from which an attempt is built.

## Meaning stays attached to the number

Scientific fields belong to a versioned record schema. Where interpretation is not self-evident, the schema points to a permanent human-readable definition. A changed definition receives a new identifier and a new schema version; old records and definitions remain available. A deterministic migration may populate a new field from old data, but it does not silently rewrite what an old field meant.

Evaluator scores follow the same rule. A leaderboard column identifies an evaluator release, score-definition key and version, unit, and ranking direction. “Logical error rate” without that context is not treated as a sufficiently precise comparison.

## Publication and curation

Draft and pending-review records are private. Published records appear in catalogues and comparisons. A withdrawn exact record remains visible as marked scientific history but is removed from current leaderboards.

Algorithm, code, and experiment tags can begin as community submissions. Administrators can promote recurring tags to official status and assign their display colours. Community benchmarks can likewise be approved without automatically becoming official reference benchmarks.

## Development status

The current contracts are version 0.1 development drafts. Version 1 is reserved for definitions reviewed with collaborators before public release. The site favours boring, inspectable technology and stable URLs over novelty.

For reproducible table requests, see the [ResultRecord query syntax](/query-syntax/).
