# Pre-release changes

Changes that go into GeoKnit before (or soon after) the 0.1.0 release. Each
change has its own folder with:

- `BRIEF.md` (from change 05 on): the decisions taken in discussion, the
  options rejected and why, and open questions. Written outside the
  codebase, so it says *what* and *why*, not *how*.
- `SPEC.md`: what the change adds or changes. It names the sections of
  `docs/SPEC.md` it touches and describes only the difference.
- `PLAN.md`: steps with **Done when** checks, one step per Claude Code session
  (start in plan mode, read `CLAUDE.md`, `docs/SPEC.md`, this change's
  `SPEC.md` and the step).

`docs/SPEC.md` stays the source of truth for what is built. A change's
`SPEC.md` can be edited as often as needed while it is a draft. When a change
is done, its text is merged into `docs/SPEC.md` in the same pull request that
finishes it, and its status here becomes **done**. The folder stays as a
record.

## Working with Claude Code

Ideas and decisions are discussed outside the repo; Claude Code turns them
into a spec and plan checked against the code, then implements them.

1. **Brief.** A discussion ends with `docs/changes/NN-name/BRIEF.md`.
2. **Spec and plan** (Claude Code, plan mode): read `CLAUDE.md`,
   `docs/SPEC.md` and the brief, check it against the codebase, write
   `SPEC.md` and `PLAN.md` in the style of the other changes. Decisions in
   the brief are kept. A decision that conflicts with the code, or is much
   harder than it looks, is not changed: it goes under
   **Questions for Xiao** at the top of `SPEC.md`.
3. **Review.** Xiao reads the spec; open questions are decided, the brief is
   updated, the spec follows.
4. **Build.** One PLAN step per session, ticking its boxes when its
   **Done when** checks pass.
5. **Finish.** Merge the change's SPEC into `docs/SPEC.md`, mark it done
   here.

The repo is the source of truth. Copies of these files kept elsewhere for
discussion are refreshed from the repo, never the other way round.

Changes 01–04 were drafted before this workflow, from `docs/SPEC.md` alone.
The "Decisions" section below is their brief: those decisions are fixed,
everything else in their SPEC and PLAN is a draft to correct against the
code.

## Index

| # | Change | Status | Needs | Release |
|---|--------|--------|-------|---------|
| 01 | [Types and component headers](01-types-and-headers/SPEC.md) | **done** | – | 0.1.0 |
| 02 | [Light and dark theme](02-theme-light-dark/SPEC.md) | **done** | – (01 for the new type colours) | 0.1.0 |
| 03 | [Map layers and colormaps](03-map-layers/SPEC.md) | **done** | 01, 02 | 0.1.0 |
| 04 | [Component library](04-component-library/SPEC.md) | agreed | 01 (03 for Display) | core set in 0.1.0, the rest in 0.1.x |
| 05 | [Run modes, radial menu, disable](05-run-modes/SPEC.md) | agreed | 01 (icons), 03 (view nodes) | 0.1.0 |

Statuses: **draft** (being discussed), **agreed** (ready to build),
**in progress**, **done** (merged into `docs/SPEC.md`).

## Order

```
01 types and headers ──┬── 03 map layers ──┬── 05 run modes ──┐
02 theme (parallel) ───┘                   │                  ├── release 0.1.0
01 ── 04 component library (core set) ─────┴──────────────────┘
                └── 04 (rest) ── 0.1.x
```

01 comes first because 03 and 04 use its new types and header keys. 02 can
start at any time; its type colour tables need the type list from 01. 05
needs 01's icon registry and 03's view nodes.

## Release mapping

0.1.0 = changes 01, 02, 03, 05 and the components marked **0.1.0** in change 04.
The components marked **0.1.x** follow in patch releases. Adding components
never breaks saved workflows, so they do not have to wait for 0.1.0.

`PLAN.md` (repo root) Phase 8 keeps its last box (publish to PyPI) open until these
are done. Add this line under Phase 8:

> Before publishing: changes 01–03, 05 and the 0.1.0 set of change 04 in
> `docs/changes/`.

## Decisions for changes 01–04 (discussion, 26 Nov 2026)

- New types: Boolean, Color, Colormap (and Layer, for the Map Viewer).
  Integer is not a type: Number and Number Slider get an integer mode.
  Geometry is not a type: Point / Polyline / Polygon output a Vector.
- A list is an access mode, not a type. List tools take a list and return
  the type they were given.
- Maths works on Numbers and Booleans only. Raster maths goes through the
  Raster Calculator, which can take Number inputs (sliders still drive it).
- Table tools accept a Table or a Vector and return the same type (geometry
  kept). Attributes turns a Vector into a Table on purpose.
- "Points from polygon" means centroids.
- Icons: Font-GIS first, then Lucide, then Tabler.
- The ribbon gets groups inside each tab.
- Light and dark theme, per user, following the system by default.

## Decisions on the review questions (26 Nov 2026)

Answers to the "Questions for Xiao" raised when 01–04 were checked against
the code. They are fixed like the decisions above.

- 01 Q1: components see their inputs through an `INPUTS` dict.
- 01 Q2: Panel's pass-through output becomes `{like: data}`
  (Grasshopper-style). It takes the type of its input, `like:` chains resolve
  through Panels, and only an unwired Panel stays `Any`.
- 01 Q3 (27 Nov 2026, while building): option (b). The default `types` of
  `ports:` offers `Any` for inputs only, so the Python component keeps `Any`
  inputs.
- 01 Q4 (27 Nov 2026): the export writes `INPUTS = {…}` as the last line of
  the settings block, only where the code uses it.
- 03 Q1: as proposed. Wires into Map Layer style inputs don't carry
  out-of-date, and Map Layer and Map Viewer never need a Run.
- 04 Q1: option (c). No XLSX; Read Table supports CSV/TSV and Parquet only.
- New for 01, Panel viewer:
  - a list shows one row per element with its index;
  - a Table shows a scrollable grid with an index column and headers;
  - a Vector shows its attribute table, with the geometry shown as its type
    name;
  - Number, Text and Boolean show the value, a Color a swatch, a Colormap a
    gradient;
  - Raster and Model keep the `describe()` summary.

  Large tables are paged from the disk cache through an API endpoint (e.g.
  200 rows per page), under a header line "N rows × M columns".
