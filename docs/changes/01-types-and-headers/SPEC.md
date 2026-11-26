# Change 01: Types and component headers

Status: agreed (checked against the code, 26 Nov 2026) · Touches `docs/SPEC.md`
sections 3, 4, 5, 6, 7, 8, 9, 10

## Questions for Xiao

None open. Answered on 26 Nov 2026 (`docs/changes/README.md`, "Decisions on
the review questions"):

1. Components see their inputs through an `INPUTS` dict (section 6).
2. Panel's pass-through output becomes `{like: data}`, Grasshopper-style: it
   takes the type of its input, `like:` chains resolve through Panels, and
   only an unwired Panel stays `Any` (section 4).

Added at the same time: the Panel viewer (section 11).

---

This change sets the contracts that new components (change 04) and the
Map Viewer rework (change 03) build on: new data types, list values, ports
that accept several types, outputs that follow an input's type, editable
ports outside the Script tab, ribbon groups, icon names and new Params nodes.
0.1.0 is not published yet, so `.geoknit` `format` stays `1` and no migration
is written; `examples/` and the tests are updated in the same change.

Where the code lives today (for the build sessions):

- types and connection rules: `geoknit/core/types.py` (`type_of`,
  `check_value`, `can_connect`, `convert_for_input`, `describe`), mirrored in
  `frontend/src/types.ts` (`DATA_TYPES`, `PORT_COLOURS`, `canConnect`);
- header parsing: `geoknit/core/component.py` (`_parse_ports`; `Port` is a
  frozen dataclass with `type: str`);
- wiring checks: `geoknit/core/graph.py` (`add_wire`, `_drop_broken_wires`);
- port rewriting: `geoknit/core/settings_edit.py` (`set_ports`, `_port_line`);
- Params nodes: `PARAMS` and `_PARAM_PORTS` in `graph.py` (fixed ports per
  kind), `node_to_dict` / `node_from_dict` / `_update_node` in
  `core/workflow.py`, `compute_keys` in `core/cache.py`, `_finish_param` in
  `runtime/client.py`, `_run_param` in `core/executor.py`, `constant()` in
  `core/export.py`, `node_view` / `_apply_patch` in `server/session.py`, and
  `paramEntries()` in `frontend/src/catalog.ts`;
- list inputs are collected in two places: `Worker._run_node`
  (`runtime/worker.py`) and `InProcessExecutor._gather_inputs`
  (`core/executor.py`).

---

## 1. New data types (SPEC 3)

Add to the table:

| Type | Python object | Port colour (light) | Panel summary (`describe()`) |
|------|---------------|---------------------|------------------------------|
| Boolean | `bool` | `#0369A1` | `True` / `False` |
| Color | `geoknit.types.Color` | `#4D7C0F` | `Color #0B7A7C` (hex value; the frontend adds a swatch) |
| Colormap | `geoknit.types.Colormap` | `#4338CA` | kind, name, min/max or number of classes (the frontend adds a gradient strip) |
| Layer | `geoknit.types.MapLayer` | `#A21CAF` | layer name, source type, style (change 03) |

`geoknit.types` here means `geoknit/core/types.py`, the module that already
holds `ModelBundle`. Port colours for the dark theme are in change 02.

Rules:

- **Boolean is not a Number.** Python's `bool` is a subclass of `int`. Today
  `type_of(True)` returns `None`, so a `bool` is refused everywhere ("expected
  Number, got bool"). It becomes `Boolean`. The check stays explicit: a `bool`
  arriving at a Number input is an error (`input "n": expected Number, got
  Boolean`), and `0`/`1` arriving at a Boolean input is an error too.
  `numpy.bool_` counts as Boolean and is converted to `bool` when it is read
  as an output, so `result = a > b` works with numpy numbers. (numpy numbers
  already count as Number, because `type_of` tests `numbers.Real`.)
- New connection convenience, like Number → Text: **Boolean → Text** (`str`),
  in `can_connect`, `convert_for_input`, the export's `_convert`, and
  `canConnect` in the frontend.
- **Color** is a frozen dataclass `Color(hex: str)`. `hex` is `#RRGGBB` or
  `#RRGGBBAA`, stored upper case. `Color.parse(s)` accepts those two forms
  (any case) and `r,g,b` / `r,g,b,a` with 0–255 values; anything else is an
  error naming the accepted forms. No named CSS colours (no extra dependency).
- **Colormap** is a frozen dataclass:
  - `kind`: `"continuous"` or `"classes"`;
  - continuous: `name` (one of the named ramps below, or `None` for custom),
    `stops: tuple[tuple[float, Color], ...]` with positions 0…1 in order,
    `min: float | None`, `max: float | None` (`None` = the layer's 2–98 %
    stretch), `reverse: bool`;
  - classes: `classes: tuple[tuple[int | float, Color, str], ...]`
    (value, colour, label), and `other: Color | None` for values not listed
    (`None` = transparent).
  - `Colormap.named(name, reverse=False)` builds a continuous colormap from
    the ramps the Map Viewer already offers (`COLORMAPS` in
    `server/tiles.py`: viridis, magma, plasma, cividis, turbo, greys_r,
    terrain, rdylgn, spectral, blues). Their stops live in
    `geoknit/core/types.py` as plain data (11 stops each), so exported scripts
    and the server-side `describe()` need neither matplotlib nor rio-tiler.
    The Map Viewer draws named ramps from rio-tiler's 256-entry tables
    (`tiles._lut`). A test checks that the 11 stops are samples of those
    tables (±1 per channel), so the legend and the tiles agree.
  - `to_json()` / `from_json()` on Color and Colormap. This is the form used
    in the workflow file, the cache and the API.
- **Layer** carries a map layer from Map Layer to Map Viewer. It is defined in
  change 03; it is listed here so the type list, colours and connection rules
  are settled in one place. Change 01 only adds the name to the type list.
- `DATA_TYPES` (Python and TypeScript) gains Boolean, Color, Colormap and
  Layer; the header parser accepts them; the Python component's port editor
  offers them (Layer is not offered: only Map Layer makes one).
- Cache formats (SPEC 6): Boolean, Color and Colormap are JSON (the existing
  `{"value": …}` file; `meta.json` already records the port type, and
  `_read_value` uses it to rebuild Color and Colormap). Layer has no cache
  entry (change 03).
- `Any` stays an input-only type. An output is `Any` only while it is
  unresolved: an unwired Panel, or a `like:` output whose `Any` input is not
  wired (section 4).

## 2. Number and Number Slider: integer mode (SPEC 3, 5, 7)

Integer is not a type. Number Slider and the new Number node (section 8) get
`integer: true|false` (default `false`). With `integer: true` the value is a
Python `int`, `min`/`max`/`value` are rounded to integers and `step` is at
least 1. The workflow file stores `integer` only when it is `true`, so
existing files keep their bytes. `PATCH /api/nodes/{id}` accepts `integer`.
A component that needs an integer and receives a float with a fractional part
raises its own error; GeoKnit does not convert.

## 3. Ports that accept several types (SPEC 3, 4)

An input's `type` can be a list:

```yaml
# inputs:
#   data: {type: [Table, Vector]}
```

- `Port.type` stays the first listed type (so existing code that reads
  `port.type` keeps working), and a new field `Port.types: tuple[str, ...]`
  holds them all (one element for an ordinary port).
- An output connects to such an input when its type is one of the listed
  types (or the output is `Any`). Number → Text and Boolean → Text still
  apply per listed type.
- When the node runs, the value must have one of the listed types; otherwise
  the error names them all: `input "data": expected Table | Vector, got Raster`.
- The tooltip on a refused wire lists them: "Raster can't connect to
  Table | Vector".
- The input's port dot is drawn with the first listed type's colour and a
  thin ring of the second; the hover summary names all types.
- `Any` cannot appear in a list; a list of one type is the same as that type;
  a type listed twice is a parse error.
- Only inputs take a list of types. Outputs use `like:` (section 4).
- API: ports in `GET /api/graph` and `GET /api/components` carry `types`
  (list) next to `type`.

## 4. Outputs that follow an input's type: `like:` (SPEC 3, 4)

```yaml
# outputs:
#   selected: {like: data}
```

- The output's type is the type of the value wired into input `data`. Before
  anything is wired it has the input's declared type (or types), drawn as
  in section 3.
- **Resolution** happens in the graph, from the wires, never from values:
  `Graph.output_type(node, port)` follows a `like:` output to the source of
  the named input, and on to that source's resolved type when it is itself a
  `like:` output, so chains work (Split Points → Select Rows → Sort Rows).
- **Panel follows the same rule.** Its pass-through output becomes
  `data: {like: data}` (in `_PARAM_PORTS`), so a Panel takes the type of what
  is wired into it, and chains resolve through Panels
  (Read Vector → Panel → Select Rows is a Vector all the way). Only an
  unwired Panel's output is `Any`: it connects anywhere, and when the Panel
  is wired its outgoing wires are re-checked like any other `like:` output.
  This replaces SPEC 3's "an `Any` output (Panel's pass-through) connects to
  any input; the value's type is checked when the receiving node runs".
  Today a Panel lets a Raster reach a Number input until Run; after this
  change that wire is refused when drawn. The export's `_as_text` helper
  (for an `Any` → Text wire) is then needed only for an unwired Panel.
- **Unresolved output.** A `like:` output whose input is not wired connects to
  an input that accepts at least one of its possible types. When the input is
  wired later, the output resolves, and wires leaving it that no longer fit
  are removed.
- **Wiring checks** use the resolved type: when `data` is fed by a Vector,
  `selected` is a Vector and can only go where a Vector can go. Wiring,
  re-wiring or unwiring `data` re-checks the wires leaving `selected`, and
  removes those that no longer fit. It does the same downstream through
  further `like:` outputs, and marks the nodes that lost a wire out of date.
  This is the same rule as SPEC 4 "Changing a component's code", generalised
  from `_drop_broken_wires` to a graph-wide re-check.
- **Loading and undo.** `graph_from_dict` and `apply_dict` add wires in file
  order, and a wire leaving a `like:` output can come before the wire that
  resolves it. Wires are therefore checked after all of them are added, and
  load does not drop wires that fit once everything is resolved.
- After the code runs, the output value must have the resolved type
  (a GeoDataFrame for Vector, a DataFrame that is not a GeoDataFrame for
  Table), otherwise the usual "wrong type" error. The worker does not know
  the graph, so the server sends the resolved output types with `run_node`
  (new field `output_types: {port: type}` in `protocol.RunNode`); the
  in-process executor uses the graph directly.
- `like:` must name an input of the same component; anything else is a
  header parse error. `like:` and `type:` on the same output is an error.
- For a `list` input, `like:` resolves to the type of its wires; wires of
  different types into an input that an output is `like` are refused
  ("all wires into "items" must have the same type").
- API: output ports in `GET /api/graph` carry `like` and `resolved_type`; the
  frontend uses `resolved_type` for colours and its own `canConnect` checks
  while dragging.

## 5. List values (SPEC 3, 4, 6, 10)

Today a wire carries one value and `access: list` collects several wires
(only Map Viewer uses it; `run_component` checks only that the value is a
Python list, not its elements). This change lets a wire carry a list.

- An output can be declared `access: list`:
  `sorted: {like: items, access: list}` or `values: {type: Number, access: list}`.
  Its value must be a Python `list` (a `tuple` is converted); every element
  is checked against the output's type. (`_parse_ports` and `_port_line`
  refuse `access` on outputs today; both change.)
- Elements of a list *input* are checked too: `input "rasters": item 2:
  expected Raster, got Vector`. Number → Text and Boolean → Text apply per
  element.
- A list output connects to an `access: list` input. Several wires into a
  list input are concatenated in wire order; a single-value wire adds one
  element, a list wire adds all of its elements. Concatenation is decided by
  the source port (a list output), not by the value.
- A list output into an `item` input is refused ("Sort List gives a list;
  "x" takes one value — use List Item"). One exception: an `item` input of
  type `Any` (Panel's `data`) takes the whole list as one value. Panel's
  pass-through, `like: data`, is then that list (`list of Raster`), so it
  connects only to list inputs that take Rasters. Running a component once per list
  element stays out of v0.1 (SPEC 1).
- Ports carrying lists are drawn with a double line (Grasshopper style) and
  the hover summary shows `list of 12 Number` and the first items.
- Panel shows a list as its length and one line per element (first 50).
  `describe()` already prints `list of N` and one line per element; it gains
  the element type in the first line and the 50-element limit.
- Cache: a list output is stored as a folder `<port>/` with one file per
  element in the element type's format (`0.tif`, `0.ref.json`,
  `1.parquet`, …) plus `index.json`; Number/Text/Boolean/Color/Colormap
  lists are a single JSON file. The worker's "replace computed rasters with
  the COG just written" step (`DiskCache.written_rasters`) handles list
  elements as well.
- Export: list outputs are plain Python lists; list inputs receive
  `[*a, b, *c]` built in wire order (today `wired_value` builds `[a, b, c]`).

## 6. Editable ports outside the Script tab (SPEC 4)

The Python component can add, remove and rename ports. Today that is a
frontend rule only: the component window shows the port editor when
`category === "Script"` (`ComponentWindow.tsx`), and the server's
`Graph.set_ports` accepts port edits on any component. Some new components
need the same (Raster Calculator, Expression, Format), but only with certain
types. New header key:

```yaml
# ports: {inputs: editable, types: [Raster, Number]}
```

- `inputs: editable` makes the inputs editable in the Settings tab as for
  Script components; `types` limits the types offered (default: every type
  except Layer and Any). `outputs: editable` is allowed as well.
- The server enforces it: `set_ports` refuses a change to a side that is not
  editable ("the inputs of Reclassify cannot be edited") and a type outside
  `types` ("Raster Calculator inputs are Raster or Number"). A component
  without `ports:` cannot have its ports edited through the API.
- The rest of SPEC 4 "Ports of a Script component" applies unchanged (new
  ports get a free name, wires follow renames, only `inputs:`/`outputs:`
  lines are rewritten). The new port's type is the first of `types`.
  `_port_line` learns to write `like:`, list outputs and `[A, B]` types, so
  the side that is not edited is written back unchanged.
- **Input names in the code.** Before the code block runs, the namespace
  gets `INPUTS`: a dict of input name → value (wired value or setting
  default), in header order. It is set for every component, and the format
  docs reserve the name. Expression, Format and Raster Calculator pass it to
  `safe_eval` / `str.format`. The export defines
  `INPUTS = {"a": a, "b": b}` at the top of each function body. The name is
  reserved: a port or setting called `INPUTS` is a header parse error.
- The Python component's header gets `ports: {inputs: editable, outputs: editable}`
  so the behaviour has one rule instead of a Script special case. "Script
  component" in SPEC 4 becomes "a component with editable ports". A
  component saved from the Python component keeps the line, so it stays
  editable whatever its category.

## 7. Ribbon groups and layout (SPEC 4, 7, 8, 9)

New optional header key `group:` (for example `group: Overlay`). Inside a
tab, the ribbon shows components in labelled groups, Grasshopper style.

- Tab order: Params, Maths, Sets, Table, Vector, Raster, Sampling, Model,
  Validation, Display, Script, then pack and user categories in alphabetical
  order. (Map Viewer moves from Params to Display; change 03.) Today the
  order is `CATEGORY_ORDER` in `frontend/src/types.ts`; it moves to the server.
- Built-ins: the order of groups and of components inside each group is
  fixed by `geoknit/components/builtin/_layout.yaml`. The registry only
  loads `<category>/*.py`, so a file at the top of `builtin/` is never read
  as a component. Entries are references, because a tab can hold components
  from several folders, and because two folders can hold files with the same
  name (`raster/clip`, `vector/clip`):

  ```yaml
  Params:
    Input: [param/text, param/number, param/slider, param/toggle, param/value_list]
    Geometry: [builtin/params/point, builtin/params/polyline, builtin/params/polygon]
    ...
  Vector:
    Files: [builtin/vector/read_vector, builtin/vector/write_vector]
    CRS: [builtin/vector/reproject]
    ...
  ```

  A test fails if a built-in component or Params node is missing from the
  layout, listed twice, or its `category`/`group` header disagrees with the
  layout.
- Built-in folder names follow the tab in lower case (`maths`, `sets`,
  `table`, `params` for the geometry components), so a reference still says
  where the file is.
- Pack and user components: groups in alphabetical order after the built-in
  groups of the same tab, components alphabetical inside a group. No `group:`
  → group "Other", shown last.
- `GET /api/components` changes shape. It answers
  `{components: [...], tabs: [{name, colour, groups: [name, …]}]}`, each
  component has `group`, and the Params nodes (`param/*`) are in the list
  with their category, group, icon and ports. So the frontend never
  hard-codes the ribbon: `paramEntries()`, `categories()` and
  `CATEGORY_ORDER` in `frontend/src/catalog.ts` / `types.ts` go away.
- Category colours (centre strip): Params, Maths, Sets, Script and pack
  categories `#475569`; Table `#7C3AED`; Vector `#C2410C`; Raster `#0B7A7C`;
  Sampling `#7C3AED` → changes to `#B45309` so it differs from Table;
  Model `#BE185D`; Validation `#15803D`; Display `#A21CAF`. The colours move
  from `CATEGORY_COLOURS` in `frontend/src/types.ts` to the `tabs` answer
  above (change 02 then turns them into theme tokens).

## 8. New Params nodes (SPEC 5, 6, 7)

Handled by the server like Text and Slider: no worker run, cache key
`sha256(format + kind + value)` as `compute_keys` already does for Text and
Slider, value sent to the worker with `put_value`, and exported as constants
(SPEC 10). Today the Params kinds are fixed in `PARAMS` / `_PARAM_PORTS`
(`core/graph.py`). Each new kind needs:

- its ports;
- `set_value` validation;
- `node_to_dict` / `node_from_dict`, with its keys added to `_NODE_KEYS`;
- `_update_node` for undo;
- `_finish_param` and `_run_param`;
- `node_view`;
- an export constant;
- a canvas node in `frontend/src/components/nodes/`.

| Node | `component` | Output | Stored fields | On the canvas |
|------|-------------|--------|---------------|---------------|
| Number | `param/number` | Number | `value`, `integer?` | a pill with "#" badge, edited inline like Text |
| Boolean Toggle | `param/toggle` | Boolean | `value` | a pill with a switch; click toggles (one undo step) |
| Value List | `param/value_list` | Number or Text | `options: [{label, value}]`, `value` (the chosen value) | a dropdown on the node; its window edits the options |
| Color Swatch | `param/color` | Color | `value` (hex) | a swatch; double-click opens a colour picker with a hex field |
| Colormap | `param/colormap` | Colormap | `value` (the Colormap as JSON) | a gradient strip or class chips; double-click opens the colormap editor (change 03) |

- Value List's output type is Number when every option value is a number,
  otherwise Text. Its output port is therefore computed from the node, not
  taken from the fixed `_PARAM_PORTS` table. Changing the options re-checks
  the wires leaving it (the same re-check as section 4).
- Geometry inputs (Point, Polyline, Polygon, Bounding Box) are ordinary
  components (`builtin/params/…`) in the Params tab, group Geometry
  (change 04), because they need shapely and pyproj in the worker.
- Panel stays in Params (group Inspect).
- Export (SPEC 10): constants are named as today (`N03_` + the first input
  they feed), e.g. `N03_INVERT = True`, `N04_COLOR = Color("#0B7A7C")`,
  `N05_COLORMAP = Colormap.named("viridis")` or the full constructor for a
  custom one. Today `geoknit.core.types` is vendored only when a component
  imports `geoknit.helpers`, a Panel needs `describe()`, or an `Any` → Text
  wire needs `_as_text`. A Color or Colormap constant becomes a fourth reason.

## 9. Icons (SPEC 4 "Header", SPEC 8)

`icon:` takes one of:

- `<set>:<name>` with `set` = `gis` (Font-GIS), `lucide` or `tabler`, for
  example `icon: gis:buffer`;
- a relative `.svg` path. SPEC 4 promises this today, but it is **not
  implemented**: `frontend/src/icons.tsx` only maps bare names, and nothing
  serves a pack's file. This change implements it. The registry resolves the
  path against the component file, and `GET /api/components/{ref}/icon`
  serves it (`image/svg+xml`, only files inside the component's folder). The
  ribbon and the node draw it.

Rules:

- Choose in this order: **Font-GIS first, then Lucide, then Tabler.**
- The frontend bundles only the icons it uses. `frontend/src/icons.tsx`
  becomes `frontend/src/icons/registry.tsx`, mapping prefixed names to icons.
  Lucide icons come from `lucide-react` (already a dependency, 1.79). The
  Font-GIS and Tabler icons used are copied as SVG files into
  `frontend/src/icons/vendor/gis/` and `…/tabler/` and imported with Vite's
  `?raw` suffix (no new dependency), so the wheel does not carry full icon
  sets. On copy, fills and strokes are set to `currentColor`.
- `docs/icons.md` lists every available name with a preview, for pack
  authors. A vitest test generates it from the registry: it fails when the
  checked-in file differs, and with `UPDATE_ICONS=1` it writes the file. The
  registry is TypeScript, so a Python script would have to parse it. An
  unknown name falls back to the category icon and logs one console warning
  per name; a pack that wants another icon ships an `.svg`.
- Licences: Font-GIS icons are CC BY 4.0 (attribution required; the font is
  OFL and the code MIT, neither used here), Lucide is ISC, Tabler is MIT.
  Each vendor folder holds its licence file. A `THIRD_PARTY_NOTICES.md` at
  the repo root credits them, and it is also in the wheel: the wheel target
  packages only `geoknit/`, so the file is added with
  `[tool.hatch.build.targets.wheel.force-include]`, and to the sdist's
  `only-include`.
- The current bare names (`reclassify`, `random-forest`, …, plus the
  frontend-only `map-viewer`) are replaced by prefixed names in the built-in
  headers and the Params entries in this change. Bare names are not kept as
  aliases, because nothing is published yet. `docs/writing-components.md`
  lists the bare names today and changes with them.
- Icons are drawn with `currentColor`, so they follow the theme (change 02).

## 10. Renames and merges before release (SPEC 5, 7)

| Before | After | Why |
|--------|-------|-----|
| Sampling › Train/Test Split (`table: Table`) and Split Points (`points: Vector`) | one **Split Points** (`builtin/sampling/split_points`), `data: {type: [Table, Vector]}`, outputs `train`/`test` `{like: data}` | they did the same thing for two types |
| Validation › Accuracy (`builtin/validation/accuracy`) | **Regression Accuracy** (`builtin/validation/regression_accuracy`) | it gives RMSE/MAE/R²/bias, not classification accuracy |
| Params › Map Viewer | Display › Map Viewer (`param/map` id unchanged) | Display tab (change 03) |

- The merged Split Points keeps what Train/Test Split did for Tables: the
  `attrs` (`feature_columns`, set by Extract Values) are copied to both
  outputs, so Random Forest `features="auto"` still works.
- The input is renamed from `points` to `data`, so the wires into Split Points
  in `examples/synthetic/imd.geoknit` and `examples/milan_imd/milan_imd.geoknit`
  change.
- References to the old names are in `docs/SPEC.md`, `docs/ui/SPEC.md`,
  both example workflows, `tests/components/test_builtins.py`,
  `test_sampling.py` and `test_validation.py`. They are all updated in the
  same step.

## 11. Panel viewer (SPEC 7, 8, 9)

Today a Panel shows the `describe()` text of its input in a `<pre>`
(`components/nodes/PanelNode.tsx`), from the per-port summary the worker
sends with `done`. It becomes a viewer that depends on the type:

| Value | Panel shows |
|-------|-------------|
| Number, Text, Boolean | the value |
| Color | a swatch and the hex value |
| Colormap | its gradient (classes: one chip per class with its label) |
| list | one row per element: its index and the element's one-line view (first line of `describe()`, the value for simple types, a swatch for a Color) |
| Table | a scrollable grid with an index column and the column headers, under a header line "N rows × M columns" |
| Vector | its attribute table, as for Table, with the geometry column showing the geometry type name (`Polygon`, `Point`, …) instead of coordinates |
| Raster, Model | the `describe()` summary, as today |

- **Where the data comes from.** The worker already sends a text summary for
  every output port (`done {outputs: {port: {cache_key, summary}}}`). It also
  sends a small `view` next to it:
  - a simple value: the value (Color and Colormap as JSON);
  - a list: its length and the first 50 element views;
  - a Table or Vector: row count, column names and the first page of rows.

  The server keeps `view` with the summary, and Params nodes build theirs in
  `_finish_param`. `GET /api/nodes/{id}/output` returns it per port.
- **Paging.** Later pages are read from the disk cache:
  `GET /api/table/{key}?offset=0&limit=200` → `{columns, rows, index,
  total_rows, offset}`. Here `{key}` is a port key as in the map routes,
  `limit` is at most 1000, and a key not in the disk cache answers `404`.
  The geometry column is sent as its type name. A list element is
  addressed as `<key>[i]` (section 5).
  - Pages are read with pyarrow row groups, so a large table is never loaded
    whole for one page. A pickle fallback entry is loaded once and memoised.
  - This is the second place where the server process reads a result itself,
    after the Map Viewer (SPEC 2). pandas and pyarrow are imported the first
    time a page is asked for.
  - With the disk cache off, the Panel shows the first page and says
    "the disk cache is off: only the first 200 rows".
- The Panel stays resizable; the grid scrolls inside it and asks for the next
  page when the user scrolls near the end. Column widths follow the header
  and the first page.
- `geoknit run` and the export keep printing the `describe()` text (SPEC 10);
  only the canvas changes.

---

## Not in this change

- Running a component once per list element (auto-iteration).
- Data trees (lists of lists).
- Named CSS colours.
- The `pip install` offer for a missing `requires` package (SPEC 12 promises
  it; it is not implemented, and nothing here needs it).
