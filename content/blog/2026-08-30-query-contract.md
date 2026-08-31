---
title: A single query contract for tables and scripts
slug: one-query-contract
summary: The browser and API should describe the same filtered, ordered collection.
published: 2026-08-30
author: Circuit Bench editors
---

Scientific comparisons should be repeatable without reverse-engineering browser state. The result explorer therefore uses the same public `ResultRecord` fields and OData-inspired query subset as machine-readable requests.

Clicking a heading can build an order; Shift-clicking can add secondary orders; and the raw query box can express more precise filters. Those controls should converge on one canonical URL. A script can submit that URL and obtain the same ordered records.

The development contract is explicitly version 0.1. Metric fields pin their evaluator and score-definition versions, so a future change in meaning creates a new field instead of silently changing old numbers. The complete syntax is on the [query reference page](/query-syntax/).
