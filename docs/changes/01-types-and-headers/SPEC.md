# Change 01: Types and component headers

Status: agreed (checked against the code, 26 Nov 2026) · Touches `docs/SPEC.md`
sections 3, 4, 5, 6, 7, 8, 9, 10

## Questions for Xiao

None open. Answered on 27 Nov 2026 (raised while building step 4):

3. The default `types` of `ports:` offers `Any` for inputs only, so the
   Python component keeps `Any` inputs (option b; section 6).
4. The export writes `INPUTS = {…}` as the last line of the settings block,
   only in functions whose code uses it, so unwired inputs already hold their
   setting values (section 6).

Answered on 26 Nov 2026 (`docs/changes/README.md`, "Decisions on
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
  while dragging. `resolved_type` is the output's own type for an ordinary
  output, and `null` while a `like:` output is unresolved (the frontend then
  uses its declared `types`; an unwired Panel's are `["Any"]`).

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

Details settled while building step 3:

- Element indices in messages are 0-based, as the Panel shows them:
  `input "rasters": item 2: expected Raster, got Vector`; an output that is
  not a list: `output "values": expected a list of Number, got Number`.
- `Graph.output_is_list(node, port)` says whether an output carries a list:
  an `access: list` output, or a `like:` output of an `item` input fed by a
  list (a Panel passing one through, also through chains of Panels). The
  refusal uses the source node's title:
  `Numbers gives a list; "x" takes one value — use List Item`. A type
  mismatch is reported first.
- The worker does not know the graph, so `RunNode` gets
  `list_keys: frozenset[str]`: the port keys of list inputs that come from
  list outputs (their elements are concatenated; any other key adds one
  element).
- `describe()` of a list: first line `list of 3 Number` when every element
  has the same type, `list of 3` otherwise (`list of 0` when empty); then
  `[i] ` and the first line of each element's `describe()`, for the first 50;
  then `… N more`.
- Cache `meta.json` port info of a list: `{type: <element type or null>,
  access: "list", count, file, format}`. `format: "json"` is the single
  `<port>.json` (`{"value": [...]}`), used when every element has the same
  JSON type (Number, Text, Boolean, Color, Colormap) and for an empty list;
  otherwise `format: "list"` with `file: "<port>/index.json"`
  (`{"items": [<element info>, ...]}`) and one file per element named by its
  index. The cache format number is unchanged (single-value entries keep
  their layout).
- Until change 03 addresses list elements (`<key>[i]`), the Map Viewer
  reports a list wired into it as unsupported ("a list of Raster cannot be
  shown on a map") and the tile, GeoJSON and inspect routes answer `404`.
- API: outputs in `GET /api/components` carry `access`; outputs in
  `GET /api/graph` also carry `resolved_access` (`"list"` or `"item"`, from
  `output_is_list`), so a Panel passing a list through is drawn as a list.
- Export: a list output is returned as `list(x)` (a tuple becomes a list as
  in GeoKnit); a list wire that needs the Number/Boolean → Text conversion is
  spread as `*[str(_v) for _v in a]`.
- Frontend, drawn as a list (double line): an output whose `resolved_access`
  is `"list"` (`/api/graph`; `access` for `/api/components` entries), an
  `access: list` input (also Map Viewer's `layers`), and a Panel's input when
  its output carries a list. A list port's dot gets a second ring in its
  type's colour outside the white one; a list wire is a wider stroke with the
  canvas colour drawn down its middle. Wires take the source output's flag.
- Frontend drag checks (`wireError` in `types.ts`) give the server's
  messages, type mismatch first; the search popup for a wire dropped in empty
  space only offers ports that pass the same check.
- Hover: a list port's heading is `values: list of Number`; the tooltip
  shows the summary's first line and its first 5 items, then `… N more`.
  The Panel shows the whole summary (`describe()`'s 50 items).

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
  except Layer and Any, and inputs may also be `Any`; Q3, answered 27 Nov
  2026). `outputs: editable` is allowed as well. The API sends the input
  side's list as `input_types`.
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
  `INPUTS = {"a": a, "b": b}` as the last line of the settings block, only in
  functions whose code uses the name (Q4, answered 27 Nov 2026). The name is
  reserved: a port or setting called `INPUTS` is a header parse error.
- The Python component's header gets `ports: {inputs: editable, outputs: editable}`
  so the behaviour has one rule instead of a Script special case. "Script
  component" in SPEC 4 becomes "a component with editable ports". A
  component saved from the Python component keeps the line, so it stays
  editable whatever its category.

Details settled while building step 4:

- `ports:` takes the keys `inputs`, `outputs` (value `editable` only) and
  `types` (a list of port types, or one name). At least one side must be
  editable; an unknown key or type, a type listed twice, or another value is
  a header parse error. Listing `Any` or `Layer` in `types` explicitly is
  allowed; only the default leaves them out.
- API: component nodes in `GET /api/graph` (and `PATCH` replies) and entries
  of `GET /api/components` carry `editable_ports: {inputs, outputs, types}`,
  or `null` without `ports:`.
- `PATCH /api/nodes/{id}` `ports`: a side left out stays as it is
  (`Graph.set_ports(node, inputs | None, outputs | None)`). Ports in the
  body also take `types` and `like`, so a side sent back unchanged keeps
  its union types and `like:` outputs.
- A side that is not editable may be sent, but what it declares (names,
  order, types, `access`, `file`, `like`) must not change; otherwise
  `the inputs of Reclassify cannot be edited` (`400`). The same applies to
  both sides of a component without `ports:`.
- On an editable side, every port's types must be in `types`:
  `Raster Calculator inputs are Raster or Number` (three or more:
  `A, B or C`). A port the header already declares outside `types` may stay,
  also renamed, as long as its type does not change. `like:` outputs are not
  checked against `types`. `access` and `file` stay editable as before.
- `INPUTS` is set after the settings block and the wired values, so an
  unwired input holds its setting's value. A port named `INPUTS`:
  `"INPUTS" is reserved and cannot name a port`; a setting named `INPUTS`:
  the same for a setting, with its line number.
- Export: `INPUTS = {"a": a, "b": b}` is written only in functions whose code
  reads the name `INPUTS`, as the last line of the settings block (after the
  settings, so unwired inputs have their values), so exports of components
  that do not use it are unchanged.
- The Python component's default `types` leave out `Any`, so its inputs can
  no longer be made `Any` from the Settings tab (before this change they
  could); a port already declared `Any` stays. A Python node whose saved
  source predates the `ports:` line has fixed ports until the line is added
  in its code.
- Frontend: the Settings tab shows the inputs editor when
  `editable_ports.inputs`, the outputs section when `editable_ports.outputs`;
  the type list offers `types` (plus the port's own type when it is outside
  them); a new port gets the first of `types`; picking a type for a union
  input replaces its types.

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

Details settled while building step 5:

- **Only what exists is listed.** `_layout.yaml` names only the built-ins
  and Params nodes that exist now (`param/text`, `param/slider`,
  `param/panel`, `param/map` and the 20 built-in files). The Params nodes of
  step 6, the `builtin/params/*` geometry components and the other change 04
  components are added to the layout by the step that adds them; the layout
  test (`tests/components/test_layout.py`) fails until they are. Today's
  Params groups: Input (Text, Number Slider), Inspect (Panel), Map (Map
  Viewer). Map Viewer stays in Params, in a group named after its future
  Display group, until change 03 moves it (the check allows `param/map` in
  Params or Display). Train/Test Split sits in Sampling › Split next to
  Split Points until step 9 merges them; Accuracy is Validation › Regression.
  Groups of the existing built-ins follow change 04's tables.
- **Tabs.** The tab order and colours are `TABS` in
  `geoknit/components/layout.py`; the layout's tabs must be a subset of it in
  that order. A tab appears only when it has at least one entry (so Maths,
  Sets, Table and Display are not shown yet); pack and user categories
  follow alphabetically (case-insensitive), coloured `#475569`.
- **Built-in headers carry `group:`.** Every built-in declares
  `group:` and the layout test checks it (and `category:`) equals its place.
  At run time a reference listed in the layout takes the layout's tab and
  group. `group:` must be a non-empty scalar (a list or mapping is a header
  parse error). A pack component whose `group:` names a built-in group of
  the same tab joins that group, after the built-ins.
- **Order of `components`.** `GET /api/components` lists entries sorted by
  tab, then group, then layout position (built-ins), then name
  (case-insensitive) and reference; the frontend keeps this order. Params
  entries have `origin: "param"`, `version: ""`, `settings: []`,
  `editable_ports: null`, `description: ""` and the same port views as
  header components (the Panel's output has `like: data`). Their icon is
  `null` except Map Viewer (`map-viewer`) until step 7.
- **Frontend.** The store holds `tabs`; `categoryColour(tabs, category)`
  (and the `useCategoryColour` hook) look the colour up there, with
  `#475569` for a category that is no tab (an inline component's own
  category). `allEntries` went with `paramEntries`, since the library now
  includes the Params nodes. The search box and the search popup show
  "Tab › Group" (`strings.tabGroup`); search also matches the group name.
  The Map Viewer node and window still use the Params colour until change 03.

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
  The constant calls the vendored classes, so in that case the vendored
  section comes before the values section instead of after it (step 1).
  Boolean → Text wires become `str(...)`, like Number → Text.

Details settled while building step 6 (backend):

- **Ribbon.** Params › Input: Text, Number, Number Slider, Boolean Toggle,
  Value List; Params › Style: Color Swatch, Colormap (change 04's group
  name; change 03 keeps them there); then Inspect and Map. Change 04's
  Geometry group goes between Input and Style.
- **New nodes start as** Number `0`; Toggle `false`; Value List options
  One = 1, Two = 2, Three = 3 with `1` chosen; Color Swatch `#0B7A7C`;
  Colormap `viridis` (named, 2–98 % stretch).
- **Values in the graph.** `Node.value` holds the Python value (`Color`,
  `Colormap`, `bool`, number, text); the workflow file, the cache key and the
  API use the JSON form (`to_json()`): Color `"#RRGGBB[AA]"`, Colormap its
  JSON object. `PATCH value` of a Color Swatch takes any `Color.parse` form
  (`#0b7a7c`, `11,122,124`); of a Colormap any valid Colormap JSON (the
  node offers named ramps until change 03, but the server already stores and
  checks the full form). Errors (`400`): `a Number value must be a number`
  (a `bool` is not one), `a Boolean Toggle value must be true or false`, the
  Color parse message, `not a colormap: …`, `'x' is not one of the Value
  List's options`. A file with such a value is refused on load, naming the
  node.
- **Value List.** `options` is a non-empty list of `{label, value}` (exactly
  these keys); `label` is text, `value` a number (not a Boolean) or text,
  each value listed once (`1` and `1.0` are the same value, `1` and `"1"`
  are not). The output is Number when every value is a number, else Text;
  in a Text list a number option's value is given as text (`str`, as a
  Number → Text wire does), and the cache key and export constant use that
  text. Its value names a file like a Text node's (fingerprinted for the
  cache key). Changing the options keeps the chosen value when it is still
  an option, otherwise chooses the first; `PATCH` may send `options` and
  `value` together. `Graph.set_options` re-checks wires graph-wide, so a
  wire into a Number input is removed when the list becomes Text (and the
  receiving node goes out of date).
- **Integer mode** rounds half up (`2.5` → `3`, `-2.5` → `-2`, like the
  frontend's `Math.round`). On a Slider it rounds `min`, `max` and `value`
  and makes `step` a whole number of at least 1; a range that collapses
  (`0.2..0.4`) is refused (`slider min must be below max`). Turning it off
  keeps the rounded values. `PATCH integer` on any other node: `Text has no
  integer mode` (`400`); `options` on a node other than a Value List:
  `Text has no options`. A Slider whose value only changes type
  (`5` → `5.0`) counts as changed, since its cache key does.
- **Cache keys** keep their recipe and name the output type:
  `{"format", <kind>: <JSON value>, "files"}` with kind `text`, `number`,
  `boolean`, `color` or `colormap`. Text and Slider keys are unchanged; a
  Number and a Slider with the same value share a key, a Toggle `true` and a
  Number `1` do not.
- **Export.** Constants are named as before; the comment says where they
  come from: `# n3 Number (integer)`, `# n4 Boolean Toggle → n5 Flip.flag`,
  `# n6 Value List (One=1, Two=2, Three=3)`, `# n7 Color Swatch`,
  `# n8 Colormap`, and a Slider in integer mode `(0..10, step 1, integer)`.
- **API** (`GET /api/graph` nodes, `POST /api/nodes` and `PATCH` replies):
  Number `{value, integer}`; Number Slider gains `integer`; Boolean Toggle
  `{value: bool}`; Value List `{options: [{label, value}], value}`, with its
  current type in `outputs[0].type` / `resolved_type` (`Number` or `Text`);
  Color Swatch `{value: "#RRGGBB[AA]"}`; Colormap `{value: <Colormap JSON>}`.
  `PATCH /api/nodes/{id}` takes `integer` and `options` next to `value`.
  `GET /api/components` lists the five nodes (`origin: "param"`); the Value
  List entry shows the default `Number` output.

Details settled while building step 6 (frontend):

- **Named ramps for the canvas.** `GET /api/colormaps` (new, tag `library`)
  answers `{name: ["#RRGGBB", …11]}` straight from `NAMED_RAMPS` in
  `core/types.py`, in its order. The frontend loads it once, when the first
  Colormap node is drawn (`store.loadRamps`), and draws a named ramp's
  gradient from those 11 stops (a custom colormap from its own `stops`;
  `reverse` flips them). One source of truth for the stops; the Map Viewer
  keeps drawing tiles and legends from rio-tiler's tables
  (`GET /api/map/{id}` `colormaps`), which the step 1 test keeps within ±1.
  SPEC 9 gains the row when this SPEC is merged.
- **Number** edits inline like Text (double-click, Enter or blur sends,
  Escape cancels). Text that is not a number (`abc`) is not sent; a toast
  says `"abc" is not a number`. While editing, a "whole numbers" box next
  to the field switches integer mode at once (its own undo step).
- **Number Slider** integer mode is a "whole numbers" box in its min / max /
  step / value window; OK sends it with the limits in one `PATCH`.
- **Boolean Toggle**: the switch and its `True` / `False` label are one
  button; a click sends `PATCH value: !value` (one undo step).
- **Value List**: the dropdown on the node lists the labels and sends the
  chosen option's `value`. Double-click on the node (outside the dropdown)
  opens a small options window (label and value per row, add, remove, OK /
  Cancel), like the Slider's, rather than the component window (Params
  nodes have no Settings / Code tabs). OK sends `options` only, so the
  server keeps the chosen value when it is still an option. A value typed as
  a number (`3`, `-0.5`, `1e3`) is a number, anything else text; a row whose
  value text was not touched keeps its value as it was (so text `"1"` stays
  text). A blank label takes the value's text. The port colour follows the
  server's `outputs[0].type`.
- **Color Swatch**: double-click opens a window with `<input type=color>`
  and a hex field. The picker has no alpha, so picking keeps the field's
  `AA`; the field also takes `r,g,b[,a]`, checked by the server.
- **Colormap**: a gradient strip (class chips for a classes colormap) with
  the ramp's name (`custom` for own stops, `N classes`). Double-click lists
  the named ramps with a "Reversed" box; picking one sends
  `{kind: continuous, name, min, max, reverse}`, keeping a continuous
  colormap's `min` / `max`. A classes or custom colormap made through the API
  is drawn but can only be replaced by a named ramp until change 03.
- **Settings tab** shows a wired Params value as `wired: Boolean Toggle =
  True`, `wired: Value List = One` (the option's label), `wired: Colormap =
  viridis`, `wired: Number = 3`, `wired: Color Swatch = #0B7A7C`.

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

Details settled while building step 7:

- **Names.** A Font-GIS name is the file name of its SVG in the Font-GIS
  sources without the code-point prefix (`uEA85-map-legend.svg` →
  `gis:map-legend`, the same as its `fg-map-legend` CSS class); Lucide and
  Tabler use their kebab-case names (`lucide:grid-2x2-check`,
  `tabler:brand-python`). The registry (`ICONS` in
  `frontend/src/icons/registry.tsx`) holds only the icons in use: built-in
  headers, Params entries and the tab fallbacks.
- **Chosen icons.** Built-ins: Read Raster `gis:mosaic`, Write Raster and
  Write Vector `gis:layer-download`, Band Select `gis:layers`, Reclassify
  `gis:map-legend`, Clip `gis:select-extent`, Align Raster `gis:snap`, Read
  Vector `gis:polygon-pt`, Reproject `gis:proj-geo`, Random Sample
  `gis:multipoint`, Stratified Sample `gis:layers-poi`, Split Points and
  Train/Test Split `gis:split`, Extract Values `gis:poi-info`, Random Forest
  `lucide:trees`, SVM `lucide:sigma`, Predict Raster `lucide:wand-sparkles`,
  Confusion Matrix `lucide:grid-2x2-check`, Accuracy `lucide:target`, Python
  `tabler:brand-python` (neither Font-GIS nor Lucide has a Python icon).
  Params (`PARAM_ICONS` in `geoknit/components/layout.py`, one per kind):
  Text `lucide:type`, Number `lucide:hash`, Number Slider
  `lucide:sliders-horizontal`, Boolean Toggle `lucide:toggle-right`, Value
  List `lucide:list`, Color Swatch `gis:color`, Colormap `lucide:rainbow`,
  Panel `lucide:sticky-note`, Map Viewer `gis:map`. Tab fallbacks
  (`CATEGORY_ICONS`): Params `lucide:sliders-horizontal`, Maths
  `lucide:calculator`, Sets `lucide:list`, Table `lucide:table`, Vector
  `gis:polygon-pt`, Raster `gis:mosaic`, Sampling `gis:multipoint`, Model
  `lucide:trees`, Validation `lucide:target`, Display `gis:map`, Script and
  pack or user tabs `lucide:code`.
- **Vendored files.** Font-GIS SVGs come from the `font-gis` npm package
  1.0.6 (`svg/`), Tabler from `@tabler/icons` 3.53.0 (`icons/outline/`);
  neither is a dependency. On copy, Font-GIS files lose their Inkscape
  metadata and ids and get a `viewBox`; every fill and stroke colour becomes
  `currentColor`; a comment at the top credits the author and licence and
  says what changed (CC BY 4.0 asks for both). `gis/` holds Font-GIS's
  `LICENSE.md` and `LICENSE-CC-BY.md`, `tabler/` Tabler's `LICENSE`. Lucide
  is not vendored (it comes from `lucide-react`); its ISC licence and the
  MIT licence of its Feather-derived icons are quoted in
  `THIRD_PARTY_NOTICES.md`. Vendored SVGs are inserted inline, so
  `currentColor` follows the text colour.
- **Wheel.** `force-include` puts the file at
  `geoknit/THIRD_PARTY_NOTICES.md` inside the wheel (the package folder,
  since the wheel has no other place for it besides `dist-info`);
  `scripts/smoke_test.py` checks it is in the installed package.
- **`.svg` icons.** The path is relative to the component file and must stay
  inside the folder the component was loaded from: the pack folder (for a
  pack), the user folder or the built-in folder. So `icons/x.svg` and
  `../shared/x.svg` both work in a pack; an absolute path, a path that
  leaves the pack, a missing file or a `<set>:<name>` icon answer `404`, as
  does an unknown reference (`Registry.icon_path`). The file is served as
  `image/svg+xml` with its bytes unchanged. The icon is the one in the
  library header: a node whose source was edited uses its library
  component's file, an inline node the file of the component it is
  `based_on` (none: the category icon). The ribbon, search and node draw it
  as a CSS mask filled with `currentColor` (so it is one colour, like the
  other icons, and an SVG's scripts never run); if it fails to load, the
  category icon is drawn instead. The frontend builds the URL with
  `componentIconUrl(ref)` (`api.ts`).
- **`docs/icons.md`** has one row per name (preview, name, set and licence)
  and a short note for pack authors. GitHub does not render inline SVG, so
  the previews are files in `docs/icons/` (`gis-map.svg`, …) drawn in
  `#64748b`, readable on light and dark backgrounds; the test checks both the
  Markdown and the folder (no missing, changed or extra file). Command:
  `UPDATE_ICONS=1 npx vitest run src/icons` in `frontend/`. The test reads
  the built-in headers with `import.meta.glob(…, {query: "?raw"})` and the
  `PARAM_ICONS` block of `layout.py` with `?raw`, so `PARAM_ICONS` keeps
  literal keys and values; the few Node APIs it uses are declared in
  `frontend/src/icons/node.d.ts` instead of adding `@types/node`.
- **Unknown names** (including the old bare names) draw the category's icon
  and log `GeoKnit: unknown icon "x"; using the category icon (see
  docs/icons.md)` once per name (`strings.unknownIcon`). A missing `icon:`
  draws the category icon silently.

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

Details settled while building step 8 (backend):

- **Views** are built by `geoknit/core/views.py` (`view(value)`), in the
  worker next to `describe()` (also for results read back from the disk
  cache and for `put_value` values), in `_finish_param` and in the
  in-process executor. A Panel's view is the view of the value passing
  through (an unwired Panel: the `None` summary view). A view that fails to
  build becomes a summary view; it never fails a run. `kind` says the shape:
  - `{kind: "value", type: "Number" | "Text" | "Boolean", value}`;
  - `{kind: "color", type: "Color", value: "#RRGGBB[AA]"}`;
  - `{kind: "colormap", type: "Colormap", value: <Colormap JSON>}` (as in
    the workflow file; a named ramp's stops come from `GET /api/colormaps`);
  - `{kind: "list", type: <element type, or null when mixed>, count,
    items: [<element view>, …]}`, the first 50 elements. An element view is
    a `value` / `color` / `colormap` view as above, otherwise
    `{kind: "summary", type, text}` with the first line of its `describe()`
    (also for a Table or Vector element: no grid inside a list);
  - `{kind: "table", type: "Table" | "Vector", columns, rows, index,
    total_rows, offset, geometry}`: the first page (200 rows) in the page
    shape below;
  - `{kind: "summary", type: <type or null>, text: <describe()>}` for Raster,
    Model and anything else.
- **Where views travel.** The worker's `done` carries
  `{cache_key, summary, view}` per port. The `done` event on `/ws` gains
  `views: {port: view}` next to `outputs: {port: summary}` (`outputs` keeps
  its shape). `GET /api/nodes/{id}/output` answers `{state, log, error,
  outputs: {port: summary}, views: {port: view}, keys: {port: port key or
  null}, disk_cache: bool}`. `keys` is what `/api/table/{key}` takes; a
  Panel's `data` key is the key of the output feeding it.
- **`GET /api/table/{key}?offset=0&limit=200`** (tag `run`) →
  `{columns, rows, index, total_rows, offset, geometry}`: `columns` the
  column names (geometry columns included, in frame order), `rows` one array
  per row in column order, `index` the index labels of those rows (a
  RangeIndex continues from `offset`), `total_rows` the table's length,
  `offset` as asked, `geometry` the names of the geometry columns (`[]` for a
  Table). `offset` past the end gives `rows: []`. `limit` 0–1000 and
  `offset` ≥ 0, otherwise `400`. `404` for: a key that is not a port key, a
  key not in the disk cache (`not in the cache; run first`), a list element
  out of range or of a list stored as one JSON file, a port that is not a
  Table or Vector (also a whole list), and any key when the disk cache is off
  (`the disk cache is off: …`).
- **The disk cache is off** when `disk_cache` is false in the output reply
  (the server always runs with it today; `geoknit run --no-cache` has no
  Panel). The Panel then shows the view's first page with the note "the disk
  cache is off: only the first 200 rows". A `404` while paging (an entry
  evicted since) is shown as an error in the grid, not as that note.
- **Reading pages.** The cache now writes Tables and Vectors with Parquet
  row groups of 10 000 rows (`ROW_GROUP_ROWS`; same layout and format
  number, old entries still read), and a page reads only the row groups it
  overlaps (`pyarrow.parquet.ParquetFile.read_row_groups`, the file opened
  and closed per request so Windows can delete it). GeoParquet WKB geometry
  is decoded with shapely only to get its type name. A pickle fallback entry
  is loaded once and memoised (the last 4, by path). This lives in
  `geoknit/server/tables.py`; pandas, pyarrow and shapely are imported on the
  first page request.
- **JSON-safe values.** Cells and index labels: `None`, NaN, `NaT`, `pd.NA`
  → `null`; booleans (also `numpy.bool_`) and integers (also numpy ints) as
  they are; finite floats as numbers, infinities as `"inf"` / `"-inf"`;
  dates, times and timestamps → ISO 8601 text (`2026-01-02T03:04:05`, with
  the offset when time-zoned); `bytes` → `"<N bytes>"`; a shapely geometry →
  its type name (`Point`, `LineString`, …; a missing geometry `null`);
  `Decimal` → number; anything else → its `str()`. Text cells longer than
  1000 characters are cut and end in `…`. A Number *value* view sends NaN
  and infinities as `"nan"`, `"inf"`, `"-inf"`, as `describe()` prints them.

Details settled while building step 8 (frontend):

- **Where the Panel gets its view.** The store keeps `views` per node and
  port (from `done` events and from `GET /api/nodes/{id}/output` after a
  reload). A Panel that is wired and `done` draws `views[id].data`
  (`components/nodes/PanelView.tsx`); otherwise it shows "(empty)", "run to
  update" or the error as before, and a result without a view falls back to
  the `describe()` text.
- **Simple values.** Number and Text as sent (so NaN shows `nan`); a Boolean
  as `True` / `False`, like the Toggle. A Colormap's classes: one row per
  class, a chip and its label (the class value when the label is empty), and
  a last chip labelled `other` when the colormap has an `other` colour.
- **Lists** show the header line `list of N Type` (as `describe()`'s first
  line; `list of N` when mixed), then one row per element: its index and its
  one-line view (a Color: a small chip and the hex; a Colormap: a small strip
  and its name), and `… N more` past the first 50.
- **The grid.** Missing cells are blank, booleans `True` / `False`,
  geometry cells in italics. Column widths are set once per result in
  characters (monospace) from the header and the first page, between 3 and
  32 characters; longer text is cut with `…` and shown whole on hover. The
  header row and the index column stay in view while scrolling. Later pages
  are 200 rows, asked for when the grid is within 120 px of its end (also
  right after a page arrives, so a Panel taller than its rows fills itself).
- **The paging key** (`keys.data`) and `disk_cache` come from
  `GET /api/nodes/{id}/output`, fetched once per result when a Panel shows a
  table (the `done` event does not carry them).
- **The disk-cache note** shows under the grid only when the table has more
  rows than the first page. A failed page shows `could not load more rows:
  <detail>` at the end of the grid, and the Panel stops paging until the
  next result.

---

## Not in this change

- Running a component once per list element (auto-iteration).
- Data trees (lists of lists).
- Named CSS colours.
- The `pip install` offer for a missing `requires` package (SPEC 12 promises
  it; it is not implemented, and nothing here needs it).
