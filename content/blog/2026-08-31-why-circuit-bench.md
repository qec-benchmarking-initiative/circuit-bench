---
title: Why Circuit Bench starts from exact records
slug: why-exact-records
summary: Useful comparisons keep their circuits, decoders, evaluators, and definitions attached.
published: 2026-08-31
author: Circuit Bench editors
---

A leaderboard is compact, but its numbers are not self-explanatory. A result only becomes useful evidence when it names the exact circuit revision, decoder version, evaluator release, score definition, and relevant machine.

Circuit Bench therefore stores the exact result first and derives tables and plots from it. The table is a view of evidence, not a replacement for the evidence. Clicking a row should lead back to the outcome counts, eligibility denominators, timing observation, frozen files, and permanent definition links that produced the displayed cells.

This also lets the registry support two directions of discovery. Decoder authors can show performance across circuits. Circuit authors can show behavior under several decoders. Both views reuse the same result records and the same comparison contract.
