# Change 01 plan: Types and component headers

Read `CLAUDE.md`, `docs/SPEC.md` and `docs/changes/01-types-and-headers/SPEC.md`
before each step. Steps are in order; each ends with **Done when** checks.
The SPEC's "Where the code lives today" list names the files each step
touches.

---

## Step 1: New types in the core

- [x] `core/types.py`: Boolean, Color (with `parse`), Colormap (with the 10
      named ramps as data, `named()`), the Layer type name; `to_json` /
      `from_json`; `describe()` for each
- [x] `type_of`: `bool` and `numpy.bool_` → Boolean; `check_value`: `bool` is
      not a Number and `0/1` is not a Boolean
- [x] Boolean → Text in `can_connect`, `convert_for_input`, export `_convert`
      and the frontend `canConnect`; new types in `DATA_TYPES` (Python and
      TypeScript) and in the header parser
- [x] Cache: JSON for Boolean, Color, Colormap (`_write_value` /
      `_read_value` rebuild by the type in `meta.json`)
- [x] Export: types vendored when a Color/Colormap constant is used; vendored
      `types.py` still runs without GeoKnit

**Done when** (pytest):
- `True` into a Number input and `1` into a Boolean input both fail with the
  expected message; a component returning `numpy.float64(2) > 1` as Boolean
  succeeds
- `Color.parse` accepts `#0b7a7c`, `#0B7A7CFF`, `11,122,124`, rejects `teal`
- `Colormap.named("viridis")` round-trips through JSON and through the disk
  cache unchanged
- the 11 stops of every named ramp match rio-tiler's table (±1 per channel)
- an exported script using a Color constant runs with `import geoknit` blocked

## Step 2: Union input types and `like:` outputs

- [ ] Header parser: `type: [A, B]` (`Port.types`), `like: <input>`, errors
      for unknown inputs, `Any` in a list, duplicates, `like` + `type`
- [ ] Graph: wiring checks against union types; `Graph.output_type()`
      resolving `like:` through chains; Panel's pass-through becomes
      `{like: data}` (only an unwired Panel is `Any`);
      graph-wide re-check that removes wires when an input's source changes
      type; load and `apply_dict` check wires after all are added
- [ ] Run: union check on inputs; resolved output types sent in `RunNode`
      (`output_types`) and checked by the worker and the in-process executor
- [ ] API: ports in `/api/graph` and `/api/components` carry `types`; outputs
      carry `like` and `resolved_type`
- [ ] Frontend: two-colour port dot, tooltip "Raster can't connect to
      Table | Vector", drag checks use `resolved_type`

**Done when:**
- pytest: a test component `data: [Table, Vector]`, `out: {like: data}`
  wired from a Vector accepts a Vector-only consumer and refuses a
  Table-only one; re-wiring `data` from a Table removes that wire
- pytest: a chain of two `like:` components re-resolves end to end when the
  first input changes type, also with a Panel in the middle
- pytest: Read Raster → Panel → a Number input is refused when drawn; an
  unwired Panel's output still connects anywhere
- pytest: a workflow file whose wire out of a `like:` output comes before the
  wire that resolves it loads with both wires
- pytest: a `like:` output returning a DataFrame while resolved to Vector
  errors with "expected Vector, got Table"
- Playwright: dragging a Raster wire onto a `[Table, Vector]` input shows the
  refusal tooltip

## Step 3: List values

- [ ] Header: `access: list` on outputs (`_parse_ports`, `_port_line`);
      element type checks on list outputs and list inputs
- [ ] Worker and in-process executor: list inputs concatenate single and
      list wires in order (by source port)
- [ ] Refuse list output → item input with the spec message; `Any` item
      inputs (Panel) take the list whole
- [ ] Cache: list folder format with `index.json`; single JSON for simple
      types; `written_rasters` handles list elements
- [ ] Panel and hover summaries for lists; double-line ports and wires
- [ ] Export: lists and `[*a, b, *c]` inputs

**Done when** (pytest):
- a component returning `[3, 1, 2]` as `list Number` feeds a list input
  together with a single-value wire; the receiver gets `[3, 1, 2, 7]`
- a list output dropped on an item input is refused with the spec message;
  dropped on a Panel it is accepted and the Panel shows `list of 3 Number`
- a list of 3 Rasters survives a worker restart (disk cache) with band
  names intact
- the exported synthetic workflow still matches GeoKnit
  (`tests/test_export_equivalence.py` unchanged)

## Step 4: Editable ports for any component

- [ ] Header key `ports: {inputs|outputs: editable, types: [...]}`
- [ ] `Graph.set_ports` refuses edits the header does not allow
- [ ] `INPUTS` dict in the namespace (worker, in-process executor, export)
- [ ] Python component switched to the header key; the frontend
      `category === "Script"` check removed
- [ ] Settings tab: port editor shown for any component with editable
      ports, limited to `types`

**Done when:**
- pytest: a test component with `ports: {inputs: editable, types: [Raster, Number]}`
  gets a new port of type Raster; changing it to Text is refused with `400`
  through `PATCH /api/nodes/{id}`; port edits on Reclassify are refused
- pytest: a component with inputs `a`, `b` sees `INPUTS == {"a": …, "b": …}`,
  in GeoKnit and in the exported script
- vitest and Playwright: the existing component-window port tests
  (`ComponentWindow.test.tsx`, `e2e/window.spec.ts`) still pass for the
  Python component

## Step 5: Ribbon groups, tab order, category colours

- [ ] Header key `group:`; `_layout.yaml` (references) for built-ins and
      Params nodes; layout test
- [ ] `GET /api/components` → `{components, tabs}`, Params nodes included;
      frontend `paramEntries`, `categories`, `CATEGORY_ORDER`,
      `CATEGORY_COLOURS` removed
- [ ] Ribbon renders labelled groups; search shows "Tab › Group"
- [ ] Category colours from SPEC section 7

**Done when:**
- pytest: removing a built-in from `_layout.yaml` fails the layout test
- pytest: a fake pack component with `group: Zeta` and one with no group
  come after the built-in groups, "Other" last
- Playwright: the Raster tab shows groups in layout order

## Step 6: New Params nodes and integer mode

- [ ] `param/number`, `param/toggle`, `param/value_list`, `param/color`,
      `param/colormap` (the colormap editor window comes in change 03; until
      then the node offers named ramps only); each through every place listed
      in SPEC section 8
- [ ] Value List output type computed from its options, with the wire
      re-check from step 2
- [ ] `integer` on Number and Number Slider (`PATCH` field too)
- [ ] Save/load, undo, autosave, export for each

**Done when:**
- pytest: save → load → save is byte-identical for a workflow with one of
  each new node; an existing workflow without `integer` keeps its bytes
- pytest: a Value List with options `1, 2, 3` outputs Number; changing one
  option to `"a"` makes it Text and removes a wire into a Number input
- Playwright: clicking a Boolean Toggle flips it, marks downstream out of
  date, and Ctrl+Z restores it
- pytest: the exported script has a `N0x_… = True` constant and runs

## Step 7: Icons

- [ ] `frontend/src/icons/registry.tsx` with `gis:`, `lucide:`, `tabler:`
      names; vendor SVGs (`?raw`, `currentColor`) with licence files;
      `THIRD_PARTY_NOTICES.md` in repo, sdist and wheel (`force-include`)
- [ ] Built-in headers and Params entries switched to prefixed names
      (Font-GIS → Lucide → Tabler); `docs/writing-components.md` updated
- [ ] `.svg` icons: path resolved by the registry,
      `GET /api/components/{ref}/icon`, drawn in ribbon and node
- [ ] `docs/icons.md` generated by a vitest test (`UPDATE_ICONS=1` writes it)
- [ ] Unknown name → category icon + one console warning

**Done when:**
- vitest: every `icon:` in `geoknit/components/builtin/**/*.py` and every
  Params entry resolves in the registry
- vitest: the `docs/icons.md` test fails when the file is stale (runs in CI
  with `npm test`)
- pytest: a fake pack with `icon: icons/x.svg` serves it from
  `/api/components/{ref}/icon`; a path outside the pack folder answers `404`
- `THIRD_PARTY_NOTICES.md` is inside the built wheel (`scripts/smoke_test.py`)

## Step 8: Panel viewer

- [ ] Worker `done` carries a `view` per port next to `summary` (value,
      list of element views, first page of a Table/Vector); Params nodes
      build theirs; `GET /api/nodes/{id}/output` returns it
- [ ] `GET /api/table/{key}?offset&limit` reading pages from the disk cache
      (pyarrow row groups; pickle entries memoised); geometry as type name
- [ ] `PanelNode`: value, swatch, gradient, list rows with index, scrollable
      grid with index column and headers, "N rows × M columns", paging on
      scroll, "disk cache is off" note; all text in `strings.ts`

**Done when:**
- pytest: `/api/table/{key}?offset=200&limit=200` on a 1000-row Table gives
  rows 200–399 and `total_rows: 1000`; a Vector page shows `Point` in its
  geometry column; an unknown key answers `404`
- vitest: the Panel renders each kind of the SPEC table (value, Color,
  Colormap, list, Table, Vector, Raster summary)
- Playwright: a Panel on Extract Values' table shows the header line and the
  grid; a Panel on a Python component returning a 1000-row Table loads the
  next page when scrolled (the synthetic tables have fewer than 200 rows)

## Step 9: Renames, merges, examples

- [ ] Merge Train/Test Split into Split Points (`data: [Table, Vector]`,
      `like:`, `attrs` kept); delete `sampling/train_test_split.py`
- [ ] Rename Accuracy → Regression Accuracy
      (`validation/regression_accuracy.py`)
- [ ] Update both example workflows (Split Points wires `points` → `data`,
      the Accuracy reference), the tests, `docs/ui/SPEC.md`,
      `docs/writing-components.md` (new header keys: `group`, `ports`,
      `INPUTS`, union types, `like`, list outputs, icon names)
- [ ] Merge this SPEC into `docs/SPEC.md`; mark change 01 done in the index

**Done when:**
- `geoknit run examples/synthetic/imd.geoknit` prints the same metrics as
  before the change
- the export equivalence test passes
- `docs/SPEC.md` and `docs/ui/SPEC.md` contain no reference to
  `train_test_split` or `validation/accuracy`
