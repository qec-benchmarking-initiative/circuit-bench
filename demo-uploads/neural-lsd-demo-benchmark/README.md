# Synthetic results for Demo Benchmark 0.1

Decoder: **Neural Localised Statistics Decoding 1.0** (`5a08cbf2-2517-4b7b-ab2a-2c39289f6f7b`).
Benchmark: **Demo Benchmark 0.1**, revision 0.1 (`162be544-715e-4d33-9cf9-672ff44691cc`).
Machine: `demo-simulated-gpu` (a simulated demo machine).

All numbers, timing measurements and confidence bounds are fabricated. No decoder was run. Each result carries an explicit synthetic-data warning. The bounds are demonstration numbers, not calculated scientific confidence intervals.

## Upload

1. Open http://127.0.0.1:8000/submit/result/batch/ .
2. Choose `manifest.json` in **Manifest file** and **clear the prefilled pasted-manifest text** (provide only one).
3. Choose `results.zip` in **Result files**, or select all four JSON files in `results/`. Do not include the manifest among result files.
4. Validate and preview, then submit. Each result enters admin review, including when uploaded by an admin.
5. Approve the four results. They must be published before they can be selected for an attempt.
6. Open http://127.0.0.1:8000/submit/benchmark-attempt/. Choose the benchmark and decoder above, then select these four results and submit the attempt for review.

The manifest sets **public** visibility so the published demo results are easy to find and use in a public benchmark attempt. Change the defaults to private if desired. These UUIDs are for the current local database; they are not portable to unrelated databases. The manifest uses result schema 0.5 and must be regenerated if the active submission schema changes.

## Circuits

| Position | Circuit | Result file |
| --- | --- | --- |
| 1 | Planar stability experiment d=5, p=0.001 | `01-planar-stability-d5-p-0-001.json` |
| 2 | Triangular colour-code memory d=5, p=0.001 | `02-colour-memory-d5-p-0-001.json` |
| 3 | Bivariate bicycle 144 memory, p=0.001 | `03-bicycle-memory-144-p-0-001.json` |
| 4 | Surface-code logical CNOT d=3, p=0.001 | `04-surface-cnot-d3-p-0-001.json` |

Only result summaries are needed: the benchmark circuits and their Stim files already exist. No submission or benchmark attempt was created when generating this pack; validation used a rolled-back preview.
