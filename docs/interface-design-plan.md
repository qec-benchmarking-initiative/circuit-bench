# DecoderBench interface design plan

Status: design proposal for review. This document records a direction; it does
not authorize implementation. The discovery/explorer page is specified in
detail. The record-detail page is intentionally left at the level of a design
hypothesis until a separate workshop.

## 1. Design position

DecoderBench should look like a maintained scientific reference work, not a
generic technology-company product.

The desired character is:

- desktop-first, compact, serious and information-dense;
- led by serif typography, ordinary links, fine rules and explicit labels;
- mostly flat, with colour used sparingly for navigation, selection and state;
- comfortable with large tables and technical notation;
- conventional enough that a researcher can understand it without learning a
  bespoke interface;
- slightly idiosyncratic and human, but not decorative for its own sake.

The following are explicit anti-goals:

- large hero headings, oversized marketing copy or generous empty bands;
- a generic sans-serif SaaS/dashboard appearance;
- rows presented as separate floating cards or white “islands”;
- shadows, glass effects, gradients, large radii or pill-shaped controls as the
  default visual language;
- hiding the principal scientific controls behind “advanced” drawers;
- designing the desktop interface around phone-sized touch targets;
- state that exists only in browser JavaScript and cannot be reproduced by a
  URL or a programmatic request.

Mobile access should remain functional, but it is a fallback. It should not
determine desktop density or force useful controls into menus.

## 2. Lessons from the reference sites

These are sources of principles, not templates to copy.

### Error Correction Zoo

Useful qualities:

- high information density and an obvious identity as a specialist reference;
- restrained use of a strong blue;
- compact navigation with many direct links;
- entry pages divided by small headings and fine horizontal rules;
- visible relationships between records rather than generic promotional copy.

Do not copy its large blue masthead or use its exact typography. DecoderBench
needs a smaller persistent header and a table-dominated explorer.

References: [home page](https://errorcorrectionzoo.org/) and
[representative entry](https://errorcorrectionzoo.org/c/single_subsystem).

### OEIS

Useful qualities:

- a single search field is plainly the main route into the database;
- serif typography, conventional blue links and normal form controls make the
  site feel like a reference rather than a product;
- very little visual decoration stands between the user and the data;
- human browsing and programmatic lookup are treated as equally legitimate.

Do not copy its absence of hierarchy or its legacy layout literally. We still
need clear grouping, accessible states and a powerful table.

References: [OEIS](https://oeis.org/) and its
[lookup demonstration](https://oeis.org/demoa.html).

### Wikipedia and MediaWiki

Useful qualities:

- a serif document title paired with compact utility text;
- familiar blue links, restrained borders and section rules;
- visual styling justified by structure and usability rather than branding;
- established table sorting, including Shift-click for secondary and further
  sort keys.

Wikipedia's prose-width limit is appropriate for articles but not for a
scientific explorer. DecoderBench prose should have a readable measure, while
explorer tables should use almost the whole desktop viewport. Wide tables need
their own horizontal overflow region rather than narrowing the whole page.

References:

- [Vector 2022 design documentation](https://www.mediawiki.org/wiki/Skin%3AVector/2022/Design_documentation)
- [MediaWiki sortable-table behaviour](https://www.mediawiki.org/wiki/Help%3ASortable_tables)

## 3. One visual system, centrally controlled

All colour must eventually come from one small semantic palette. Components
must not introduce arbitrary colour literals. Changing this palette should
change the character of the entire site without changing component CSS.

Proposed default palette for the first workshop:

| Token | Proposed value | Purpose |
|---|---:|---|
| canvas | `#f8f7f2` | warm page background |
| paper | `#fffef9` | table and document background |
| ink | `#1d1c19` | primary text |
| muted ink | `#67635b` | secondary labels and notes |
| rule | `#c9c5bb` | ordinary grid and section rules |
| strong rule | `#77736a` | header and selected boundaries |
| link/accent | `#244f86` | links, active controls and sort marks |
| accent wash | `#e8eef5` | selected row or active-filter background |
| success | `#27643a` | valid query and verified states |
| warning | `#8a5a00` | provisional/custom states |
| danger | `#922f32` | errors, withdrawal and failed integrity |
| focus | `#b35c00` | keyboard focus outline |

These exact colours are candidates, not a final brand palette. The important
decision is the semantic token structure. Later alternate palettes should
replace these tokens, not override individual components.

Other visual defaults:

- no shadows by default;
- square corners or a nearly imperceptible radius of at most 2 px;
- 1 px rules for most grouping and a 2 px rule only for strong state;
- underlined links in prose and table cells; navigation links may omit the
  underline when their active state is otherwise explicit;
- colour never acts as the only indication of state.

## 4. Typography and density

Typography should be serif-led without requiring a hosted web font.

Proposed roles:

- reference/body serif: Georgia followed by the platform serif fallback;
- compact interface sans: Arial/Helvetica/system sans for controls, table
  headings and small metadata labels;
- technical monospace: the platform monospace stack for queries, UUIDs,
  hashes, field names and machine-readable values;
- tabular numerals for numeric table columns.

Proposed desktop scale:

| Role | Initial size | Notes |
|---|---:|---|
| ordinary prose | 15 px | approximately 1.4 line height |
| table body | 13.5–14 px | compact but not miniature |
| labels and metadata | 12–13 px | usually sans-serif |
| section heading | 16–18 px | medium weight, often above a rule |
| explorer page title | 19–22 px | never a hero heading |
| persistent site name | 17–19 px | compact and stable |

Use normal and semibold weights; avoid making every heading heavy. Technical
tables may be dense, but explanatory prose should retain a readable line
length of roughly 65–80 characters.

## 5. Page families

The site has two primary dynamic page families.

### Explorer pages

Examples: Decoders, Circuits, Benchmarks, Noise models and Latest results.

Their job is to help a person locate records and make precise comparisons.
They use nearly the whole desktop width and terminate in a reusable scientific
table. This page family is specified below.

### Record-detail pages

Examples: a decoder version, exact circuit revision, noise model, result or
benchmark revision.

The provisional direction is a compact reference article: a small contextual
heading, conventional sections separated by rules, a concise exact-record
metadata block and one or more instances of the same scientific table used by
explorers. It should not be a dashboard of cards.

The record-detail composition, especially the relationship between narrative
definition, provenance and comparison table, remains open for the next design
workshop. Existing detail pages are not accepted as the visual default merely
because they exist.

## 6. Explorer page anatomy

The default desktop composition is:

```text
┌──────────────────────────────── persistent site header ────────────────────────────────┐
│ DecoderBench   Decoders  Benchmarks  Circuits  Noise models  Results        account   │
├──────────────────────────────── contextual page bar ───────────────────────────────────┤
│ Decoders   Exact decoder versions, capabilities and submitted evidence                 │
├──────────────────────────────── query row ──────────────────────────────────────────────┤
│ Search by name or enter a query __________________________________  Run  Clear  Syntax │
├──────────────────────────────── query status ───────────────────────────────────────────┤
│ Valid query · 42 records · 18 ms · canonical/reproducible URL                           │
├────────────────────────────── visible filter matrix ────────────────────────────────────┤
│ Algorithm tags  □ Matching □ BP ...   Preparation  skeleton [any] priors [any]         │
│ Soft output [any]     Results [min ___ max ___]       [Apply filters] [Reset]           │
├──────────────────────────────── table toolbar ──────────────────────────────────────────┤
│ 42 records   Sort: Name ↑, Results ↓      Table view options (8/19)   CSV   JSON        │
├──────────────────────────────── scientific table ───────────────────────────────────────┤
│ Decoder  Version  Skeleton prep  Prior prep  Probability  Tags  Results  Last updated   │
│──────── ──────── ─────────────── ────────── ─────────── ───── ─────── ──────────────│
│ ...                                                                                     │
│ ...                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

This is one continuous work surface. The query area, filters, toolbar and table
may be separated by rules or subtle background changes, but they should not be
individual floating boxes.

### 6.1 Persistent site header

- Approximately 36–42 px high on desktop.
- Small site name, direct section links and account state.
- No large logo lock-up, slogan or decorative banner.
- Remains visually subordinate to the data.

### 6.2 Contextual page bar

- Comparable in height to the persistent header.
- Contains the page title, such as “Decoders”, at 19–22 px.
- May contain one short descriptive sentence on the same line or immediately
  beneath it.
- Does not repeat an eyebrow, marketing label or large block of introduction.

### 6.3 Query row

- One long, monospace-capable input occupies most of the width.
- A user may enter a plain name/search phrase or an explicit scripted query.
- “Run”, “Clear” and “Query syntax” remain visible; no online-IDE treatment.
- Enter submits. Input is not executed on every keystroke.
- The exact query language and public field names remain the responsibility of
  the later query-contract task, not this visual plan.

Proposed unambiguous mode rule:

- text not beginning with `$` is a convenience name/text search;
- text beginning with a supported `$` parameter is parsed as the standard
  scripted query form;
- after any successful structured-filter change, the field may be normalised
  to the complete canonical query so the exact operation is visible and
  copyable.

The last point should be tested with users. If canonicalisation feels too
surprising, the status row may show the canonical query separately while the
input retains the convenience text.

### 6.4 Query status row

The status row is always allocated, so success and errors do not move the
table. It reports one of:

- idle/help: which input mode will be used;
- running: a plain textual progress state;
- success: parsed mode, match count and elapsed server time;
- error: useful message plus line/column or character offset.

An invalid query must leave the last valid table and filters visible. It must
not replace the data with an error page or silently fall back to name search.

### 6.5 Visible filter matrix

Principal filters are present on the page, not hidden in a generic “advanced
filters” dialog.

- Tags use compact checkboxes, grouped by namespace and ordered official first.
- A large tag group may have its own small tag-name search, but selected tags
  and the full official set remain visible.
- Numeric values use paired minimum/maximum fields with the unit in the label.
- Boolean scientific properties use `Any / Yes / No`, not a single checkbox,
  because filtering for false is meaningful.
- Enum fields use compact select controls or short radio groups.
- “Apply filters” and “Reset” are explicit.
- All predicates are combined with the query into one canonical server-side
  query state; controls must never filter only the rows currently loaded in
  the browser.

The initial filter groups should be endpoint-specific:

| Explorer | Principal visible filters |
|---|---|
| Decoders | algorithm tags; skeleton preparation; prior preparation; soft probability output; result-count range |
| Circuits | code tags; experiment tags; noise model; randomised priors; CSS; code/circuit distance bounds; detector/error ranges |
| Noise models | curation status; randomises priors; circuit-count range |
| Benchmarks | curation status; official-recognition state; required/optional circuit counts |
| Results | decoder; circuit; benchmark membership; evaluator; reproduction status; machine class; score/rate/timing ranges |

This list describes interface groups, not final query fields or scientific
definitions.

### 6.6 Table toolbar

The toolbar is one compact line above the table and contains:

- result count;
- a textual summary of active sort keys;
- a visible `Table view options` button, including the visible/available column
  count;
- `Reset sort` when a non-default sort is active;
- links for equivalent CSV and JSON results once those formats exist.

Do not hide column selection behind an icon with no text.

## 7. Scientific table component

The table is the principal reusable interaction component for both explorer
and record-detail pages.

### Visual behaviour

- It occupies the full explorer width.
- Rows are continuous table rows, not cards.
- Header and row boundaries use fine rules.
- Default row height is approximately 28–32 px when cells contain one line.
- Numeric cells are right-aligned and use tabular numerals.
- Units are in headings or explicit adjacent labels, never implied.
- Missing values render as a consistent em dash and sort according to the
  public query contract.
- The table header remains visible while scrolling a long result set.
- The record-name/identifier column should be tested as a sticky first column.
- A wide table scrolls horizontally inside its own region. The entire page
  should not acquire horizontal scrolling.
- Default columns are chosen to compare records; long descriptions are not a
  default table column.
- Hover and selected-row states use a very light accent wash, not elevation.

The initial default decoder columns are proposed as:

1. Decoder name
2. Version
3. Circuit-skeleton preparation
4. Circuit-prior preparation
5. Per-shot failure probability
6. Algorithm tags
7. Published result count
8. Publication/update date

Additional scientific and provenance columns remain available through table
view options.

### Column registry

Every explorer supplies a declarative column registry. A column definition
must contain, as appropriate:

- stable public field name;
- human label and short help text;
- data type and null behaviour;
- scientific unit and definition link;
- cell renderer and alignment;
- whether it is sortable and filterable;
- default sort direction;
- default visibility and display order;
- CSV/JSON representation.

This registry should drive the browser table, structured filters and API
metadata. Labels, types and units must not be independently redefined in each
template.

### Table view options

`Table view options` opens a conventional accessible dialog containing:

- one checkbox per available column, grouped sensibly;
- Move up / Move down controls for column order;
- `Restore defaults`;
- optional `Keep first column visible`;
- `Apply` and `Cancel`.

Column choice and order are encoded in the URL, probably through the standard
query projection parameter chosen by the query contract. Initially they do not
need account-level persistence or a complex saved-view system.

## 8. Exact sorting interaction

Sorting is server-side and applies to the complete matching population, never
only the current page of rows. Each sorted heading displays its priority and
direction, for example `1 ↑`, `2 ↓`.

### Ordinary click

| Current state of clicked column | Result |
|---|---|
| not the primary sort | remove every existing sort key; make this the sole primary key in its default direction |
| primary ascending | keep it as the sole key and reverse to descending |
| primary descending | keep it as the sole key and reverse to ascending |

An ordinary click therefore always clears secondary sorts. There is no hidden
third “unsorted” click state; `Reset sort` restores the page default.

### Shift-click

| Current state of clicked column | Result |
|---|---|
| unsorted | append it as the next sort priority in its default direction |
| already sorted ascending | preserve all priorities and reverse it to descending |
| already sorted descending | preserve all priorities and reverse it to ascending |

Shift-clicking the primary column changes its direction without deleting its
secondary keys. Shift-clicking a secondary column changes that key in place;
it does not move it to the end.

### Accessibility and explicit state

- Heading labels are real buttons inside semantic table headings.
- Enter/Space performs an ordinary click.
- Shift+Enter/Shift+Space performs the additive action where browser support is
  reliable; an accessible sort control in table options provides the same
  operation without requiring a modifier key.
- Direction arrows, priority numbers and screen-reader text all communicate
  the state; colour alone does not.
- The canonical URL updates after every accepted sort operation.

This interaction deliberately resembles MediaWiki's familiar Shift-click
secondary sorting, while making the reset and priority rules explicit.

## 9. Query, URL and programmatic equivalence

The explorer is one view of a server query, not a separate client-side data
tool.

The following must always describe the same result population and order:

- the query input;
- visible filter controls;
- table sort markers;
- selected columns;
- the browser URL;
- the corresponding JSON or CSV request.

The exact standard syntax, supported OData subset, limits, null ordering and
tie-breaking remain to be fixed in the planned query-contract task. The design
requires these invariants now:

1. The URL is sufficient to reproduce the view in another browser.
2. A bot can request the same query without executing browser JavaScript.
3. The server returns stable validation errors with positions and codes.
4. Invalid input leaves the last valid result set on screen.
5. Every sort gains a deterministic final identifier tie-breaker, whether or
   not that tie-breaker is displayed.
6. Pagination, CSV and JSON operate on the same parsed query.

## 10. Reusable composition

The eventual implementation should compose one explorer from the following
responsibilities:

- `ExplorerPage`: page-level composition and endpoint identity;
- `ContextHeader`: small page title and single-sentence description;
- `QueryBar`: name/query input and explicit actions;
- `QueryStatus`: validation and execution result;
- `FilterMatrix`: endpoint-provided visible structured controls;
- `ExplorerToolbar`: count, sort summary, view options and formats;
- `ScientificTable`: semantic table, sorting and horizontal viewport;
- `ColumnChooser`: visible columns and ordering.

Names may change during implementation. The important boundary is that one
scientific table and one query-state model are reused everywhere. Endpoint
templates supply column/filter declarations and row links; they do not copy
sorting JavaScript or table markup.

On a record-detail page the same table can receive a locked scope—for example,
“results for this exact decoder version”—while retaining query, sort, column
and export behaviour.

## 11. Desktop-first fallback behaviour

Primary review widths should be 1280, 1440 and 1920 px. The explorer should
remain useful at 1024 px.

Below that:

- the site and contextual headers may wrap rather than transform into a
  prominent mobile navigation system;
- filter groups may stack;
- the scientific table remains a horizontally scrollable table rather than
  converting rows into cards;
- all functions remain keyboard accessible;
- no scientific column is silently discarded merely to fit a narrow screen.

This is graceful fallback, not a mobile-first redesign.

## 12. Workshop and acceptance process

Before implementation, make static or fixture-backed versions of exactly two
explorer states:

1. a normal decoder table with enough columns to require deliberate selection;
2. a difficult state with a long name, many tags, nulls, multiple sort keys and
   an invalid query preserving the previous results.

Review them at 1440 px first. The proposal is accepted only when:

- persistent and contextual headers together consume little vertical space;
- the page contains no row cards, shadows or dashboard islands;
- the table visually dominates the explorer;
- filters are visible without opening a dialog;
- all colours come from the semantic palette;
- table type is compact but comfortably readable;
- sort priority and direction are obvious without explanation;
- the invalid-query state does not destroy or move the previous table;
- column selection is explicit and reproducible in the URL;
- the same fixture query can later be reproduced through HTML, JSON and CSV.

## 13. Decisions still requiring review

The current proposal deliberately leaves these choices open:

- exact serif stack: Georgia-first versus a more bookish system-serif stack;
- pure white versus the proposed warm-white canvas;
- the final blue/accent hue and amount of colour in table selection;
- 28 px versus 32 px default table-row height;
- whether the contextual description sits beside or below the page title;
- how many official tags can be shown before a tag-group search is introduced;
- whether the first column is sticky by default;
- whether structured changes rewrite the query input itself or show a separate
  canonical query in the status row;
- the record-detail page composition, to be handled in the next workshop.

None of these open choices prevents agreement on the explorer's structure or
interaction model.
