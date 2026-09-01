# Scientific number rendering

Circuit Bench stores, accepts, queries, and exports exact machine-readable
numbers. It applies typographic formatting only when a number is displayed to a
person.

## Source of truth

`registry/formatting.py` defines the profiles and returns a structured
`NumberDisplay`. `static/js/scientific-format.js` implements the same contract
for values that change without a page load. Both implementations are checked
against `tests/fixtures/scientific_numbers.json`.

The named 0.1 profiles are:

- `default`: four significant figures; scientific notation at exponents at or
  below -2 and at or above 4;
- `count`: grouped ordinary integers below one million, then four-significant-
  figure scientific notation;
- `probability`: three significant figures;
- `duration`: four significant figures;
- `score`: four significant figures.

Scientific HTML is semantic rather than LaTeX-driven: for example,
`2.3 · 10<sup>-3</sup>`. It retains the exact source in `data-raw` and supplies an
accessible spoken label. SVG ticks use `tspan` for the exponent. Text-only SVG
readouts and histogram labels use the equivalent Unicode form, `2.3 · 10⁻³`.

## Deliberate exclusions

Numeric form inputs, query strings, JSON, CSV, data attributes used for
calculation, and downloaded source data retain ordinary machine-readable
numbers. Identifiers, dates, years, and version strings are not scientific
quantities and do not use the renderer.

The renderer rounds only the display. It must never be used before a database
write, comparison, sort, filter, plot-position calculation, or export.
