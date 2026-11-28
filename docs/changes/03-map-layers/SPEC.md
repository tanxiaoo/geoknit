# Change 03: Map layers and colormaps

Status: done (merged into `docs/SPEC.md`, 28 Nov 2026; checked against the code, 26 Nov 2026) · Needs 01 (types,
union inputs, list values, Color and Colormap nodes), 02 (basemap `auto`) ·
Touches `docs/SPEC.md` sections 5, 6, 7, 8, 9, 10

## Questions for Xiao

None open. Question 1 (restyling without a Run) was answered on 26 Nov 2026
as proposed: wires into a Map Layer's style inputs do not carry out-of-date,
and Map Layer and Map Viewer never need a Run (section 4).

---

A colour scheme becomes a value on the canvas that any component can use,
and the Map Viewer shows any number of layers, each with its own style:

```
Read Raster ─────────────┐
Colormap (classes) ──────┴─ Map Layer "IMD classes" ──┐
Read Vector ── Map Layer "AOI" ← Color Swatch ────────┼─ Map Viewer
Stratified Sample ────────────────────────────────────┘   (raw wire: default style)
```

How the Map Viewer works today (for the build sessions): `server/tiles.py`
renders tiles itself. rio-tiler only reads the pixels
(`reader.tile(...)`); the colour step is GeoKnit's own numpy code:
`_lut(name)` takes rio-tiler's 256-entry table for a named ramp, and the
`categorical` style uses `PALETTE[v % 20]`. Styles are checked by
`_check_style` and saved under the Map Viewer node's `map` key
(`node.extra["map"]`). Layers come from `Session._map_inputs` /
`map_view`, keyed by the source's last done port key.

---

## 1. Display tab (SPEC 7, 8)

New ribbon tab **Display** (category colour `#A21CAF`), groups:

- **Style**: Map Layer
- **Map**: Map Viewer (moved from Params; the node id `param/map` is kept)

Color Swatch and Colormap stay in Params › Style (change 01, section 8),
because they are inputs that other tabs use too. Tab and group membership come
from `_layout.yaml` and `GET /api/components` (change 01, section 7).

## 2. Colormap editor (Params › Colormap)

Double-clicking a Colormap node opens a floating window:

- **Kind**: Continuous | Classes.
- **Continuous**: named ramp (the 10 from change 01) or Custom; Reverse;
  min/max each "auto" (the layer's 2–98 % stretch) or a fixed number. Custom
  shows the gradient with draggable stops; click on the bar adds a stop;
  each stop has a colour picker with a hex field and a position 0–1.
- **Classes**: a table value | colour | label with Add / Remove / reorder;
  "Other values": transparent or a colour; "Fill colours from ramp" assigns
  colours from a named ramp to the listed values in order.
- Preview strip at the top. Each change is one `PATCH /api/nodes/{id}`
  `{value}`, so one undo step. It redraws open maps that use it without a
  Run (section 4). It makes a component that uses the Colormap out of date as
  usual.
- Paste a class table: lines of `value, #hex, label` (tab or comma
  separated) pasted into the table replace it, so a legend kept in a
  spreadsheet comes in at once.

## 3. Map Layer (Display › Style)

A server-handled node (`param/layer`, like Panel: no code, no worker run).

| Input | Type | Default (shown in its window) |
|-------|------|-------------------------------|
| data | `[Raster, Vector]` | required |
| colormap | Colormap | none → the Map Viewer's default for that layer |
| color | Color | none → the Map Viewer's default vector colour (`#d62728`, same in both themes; change 02) |
| opacity | Number | 1.0 (0–1) |
| bands | Text | none → default band choice (SPEC 8 "Rasters"); `"1"` or `"4,3,2"`, numbers or band names, 1 or 3 bands as today |
| name | Text | the source node's title and port |

Output: `layer: Layer`.

- Unwired inputs are set in a small window (double-click), as for Number
  Slider: colormap from a dropdown of named ramps, colour picker, opacity
  slider, bands, name. Values are saved on the node under `style`.
- `MapLayer` (the Layer value, in `geoknit/core/types.py`) is a frozen
  dataclass: `source` (the port key of `data`), `kind` (`raster` |
  `vector`), `name`, `colormap: Colormap | None`, `color: Color | None`,
  `opacity: float`, `bands: list[int] | None`, `field: str | None`. It holds
  no pixels or features.
- **Building it.** The server builds the MapLayer itself; nothing runs in the
  worker.
  - A style input wired from a Params node uses that node's current value.
  - One wired from a component (a Colormap made by code) uses that
    component's last done result, read from its disk cache entry (JSON), as
    Map Viewer layers are read today. With the disk cache off, or before that
    component has run, the input counts as unwired and the window says so.
  - A style input wired from a list is refused (they are `item` inputs).
- **Cache and keys.** The Map Layer has no cache entry. Its port key is
  `sha256("layer" + data port key + style JSON)` (a new branch in
  `compute_keys`, like Panel's). Its value is sent to the worker with
  `put_value`, so a Panel can describe it and a later component can take a
  Layer.
- A `colormap` on a vector layer colours its features by a field. Map Layer
  then shows a `field` dropdown with the columns of the vector, from
  `describe_vector`. The colormap is continuous for numeric fields and
  matches classes on the field's values. The server sends the field values
  with the GeoJSON, which already has every attribute, and MapLibre colours
  them with a `match` or `interpolate` expression built from the Colormap.
  Without `colormap`, vectors use `color`.
- Panel on a Layer shows its name, source and style.

## 4. Map Viewer (SPEC 6, 7, 8)

- Input `layers` becomes `{type: [Raster, Vector, Layer], access: list}`
  (union types from change 01; today it is `Any`). Panel's `Any` pass-through
  still connects. Tables and the other types can no longer be wired in, so
  the "cannot be shown on a map" status only remains for a Panel that passes
  one through.
- One layer per wire as today. A list wire (change 01) adds one layer per
  element. Layer ids are `<node id>.<port>` as today, and `<node id>.<port>[i]`
  for list elements. The port-key pattern of the tile and vector routes
  (`_KEY` in `tiles.py`) and the list-element entries in the cache
  (change 01, section 5) get the same `[i]` suffix.
- **Raw Raster/Vector wire**: behaves exactly as today; style edited and
  saved in the window under the node's `map.styles`.
- **Layer wire**: the style comes from the Map Layer.
  - The layer's data is the Map Layer's `source`, so the layer is ready when
    that source is `done`, as for a raw wire.
  - In the window's style panel, the fields set by the Map Layer (wired or
    set in its window) show their value with "from Map Layer <name>" and are
    read-only.
  - A "Go to Map Layer" link selects that node.
  - Show/hide stays editable in the viewer and is saved under `map.styles`
    as today. Order is wire order, as today.
- **No Run for styles** (decided 26 Nov 2026). Today a style change (`map` in
  `PATCH /api/nodes/{id}`) never makes anything out of date. That carries
  over:
  - The solver does not propagate out-of-date along wires into a Map Layer's
    style inputs (`colormap`, `color`, `opacity`, `bands`, `name`). Changing
    a Colormap, Color Swatch or Slider that only feeds those inputs still
    marks the Params node itself out of date, as every Params edit does. The
    open maps redraw at once.
  - Map Layer and Map Viewer are *view nodes*. They are not in a run plan's
    work, and they are not counted in "N components out of date". Their state
    is `done` when their sources are `done`.
  - A redraw re-requests tiles with the new style, or re-styles the GeoJSON.
    No component runs and no `started` event is sent.
- **Legend**: continuous → gradient bar with min/max; classes → one row per
  class with its label (value when the label is empty); vectors with a
  colour → a swatch with the layer name. (`legendFor` in
  `components/map/layers.ts` already draws all three for today's styles,
  plus an RGB legend. It gains custom stops, class labels and a Colormap's
  `other` colour.)
- **Tiles** (`/tiles/{key}/…`): new query parameter `cmap` carrying a
  Colormap as compact JSON. It replaces `colormap` when present. The tile
  route stays stateless (a port key plus query parameters), so the server
  never resolves node ids there.
  - A continuous colormap becomes a 256-entry lookup table, built from its
    stops and rescaled by min/max, in the same numpy step that applies
    `_lut` today.
  - A classes colormap becomes a value → RGBA lookup in the same step as
    today's `categorical` palette. `other` colours the rest, or makes it
    transparent when `None`. An `#RRGGBBAA` colour multiplies the tile's
    alpha.
  - Named ramps that are not customised keep using `_lut` (rio-tiler's
    tables).
- The default palette for small-integer rasters (`v mod 20`) is unchanged
  when no Colormap is given.
- Basemap: `auto` (default, follows the theme), `light`, `dark`, `none`
  (change 02).

## 5. Workflow file (SPEC 5)

- `param/layer` nodes: `{"id", "component": "param/layer", "style": {...},
  "position"}`. Style keys: `colormap` (Colormap JSON), `color`, `opacity`,
  `bands`, `name`, `field`. `style` joins `_NODE_KEYS` in `core/workflow.py`.
  An edit of `style` is one undo step. It goes through the solver rule of
  section 4, so it is not a layout-only key like `map`.
- `param/colormap` nodes: `{"value": <Colormap JSON>}` (change 01).
- Map Viewer `map.basemap` accepts `auto` | `light` | `dark` | `none`;
  `map.styles[<layer id>].colormap` also accepts a Colormap JSON object, next
  to today's ramp names and `categorical`.

## 6. API (SPEC 9)

- `PATCH /api/nodes/{id}` accepts `style` for Map Layer (merged like `map`,
  `null` resets a field) and `value` for Colormap and Color nodes
  (change 01).
- `GET /api/map/{id}` returns, for each layer, `from_layer: <node id> | null`
  and the effective style with `locked: [field, …]`.
- `GET /api/map/{id}` is also what the open window re-reads after a style
  change. The server sends a new `/ws` event `map_changed {node}` when a
  Map Layer or a Params node that feeds one changes, so the window does not
  wait for `run_finished`.

## 7. Export (SPEC 10)

Map Layer and Map Viewer are comments in the script
(`# n14 Map Layer "IMD classes": n03.raster, colormap n09`). A Panel on a
Layer prints `(Map Layer, not exported)`. Colormap and Color constants are
exported (change 01), so a component that takes a Colormap (for example a
future "Write Map PNG") still runs.

## 8. Implementation choices (step 3)

Points the sections above leave open, as built in step 3 (backend):

- **Style values** (`geoknit/core/layers.py`). Each style input takes, in
  order: a wired Params node's current value (followed through Panels, also
  when that node is out of date); a wired component's last done result; the
  value saved in `style`; the default. A wired value of the wrong type (after
  the usual Number → Text conversion), an opacity outside 0–1, unknown band
  names, or a component without a usable result count as unwired. The node
  view's `layer.issues` says why, per input (`data`, `colormap`, `color`,
  `opacity`, `bands`, `name`); `layer.wired` names each wired input whose
  value is used (`params` | `component`).
- **Saved `style`** is checked on load and on PATCH (an unknown field or bad
  value is refused, 400 / `WorkflowError`) and stored in normal form:
  `colormap` as Colormap JSON (a ramp name is accepted in a PATCH and saved as
  `{"kind": "continuous", "name": …}`), `color` as upper-case `#RRGGBB[AA]`,
  `bands` as `"4,3,2"` (spaces removed), `opacity` a number 0–1, `name` and
  `field` non-empty text. A new Map Layer saves `"style": {}`. `PATCH
  {"style": null}` resets every field.
- **`MapLayer.bands`** is a tuple (the dataclass is frozen); its JSON form is a
  list. Band names in `bands` are matched against the raster's band names
  read from its cache entry (no pixels); `field` is kept only for vectors.
- **`kind`** comes from the data wire's type in the graph; when that is
  ambiguous (a union output) it comes from the data's done result. So the
  layer, and its port key, exist before any run whenever the graph types say
  Raster or Vector. Without data, the `layer` port key is the empty key
  (value `None`).
- **Port key**: `<sha256("layer" + data port key + style JSON)>.layer`, the
  style JSON being `MapLayer.to_json()` without `source` (sorted keys, compact
  separators). `keys.nodes` is `None` for a Map Layer (no work, no cache
  entry), as for a Panel.
- **View-node state** (`Solver.view_state`, revised 28 Nov 2026 after
  Xiao's review): a Map Viewer is always `done` and draws every layer whose
  source works. A Map Layer follows its `data` wire: `done` when it is;
  `skipped` when it is `error` or `skipped` (so a Panel on the layer is
  skipped too); `never_run` without data or when it never ran; otherwise
  `out_of_date`. Style sources never affect it.
- **Banner count** (decided 28 Nov 2026): "N components out of date" counts
  components only; Params nodes (inputs, Panels, view nodes) never count, so
  a Colormap edit leaves the banner hidden. A Run with mode `test` on a
  view node plans nothing; `to_node` plans its upstream.
- **Plan order**: with view nodes in the graph, plans follow the whole
  graph's topological order, so a Panel on a Map Layer runs after a
  component wired into the layer's style.
- **Style edits** (`style` PATCH, wiring or unwiring a style input, deleting
  a node that only feeds style inputs) mark nothing out of date, so a
  Panel or component downstream of the Map Layer keeps its state until the
  next Run, which finds its key changed and runs it again (as for a changed
  file, SPEC 6). A `style` PATCH is refused during a run (409), as other
  result edits.
- **Worker**: the layers are sent with `PutValue` at the start of a Run, and
  again after a component wired into a style input finishes (its result now
  resolves, so later nodes get the new layer).
- **API**
  - Node view of a Map Layer (`GET /api/graph`, PATCH answers): `style` (the
    saved fields) and `layer: {key, value, issues, wired}` (`value` is the
    `MapLayer` JSON: `source, kind, name, colormap, color, opacity, bands,
    field`), or `null` before the server built it.
  - `GET /api/layer/{id}` (new, tag `map`): the same build plus `node`,
    `state`, `style`, `columns` (a vector's columns, from `describe_vector`,
    for the `field` dropdown) and `bands` (a raster's band names); both `null`
    until the data is `done` with the disk cache on. 400 for another node.
  - `/ws` `map_changed {node, viewers}`: sent after any edit, undo/redo or
    Run that changes a Map Layer's port key; `viewers` are the Map Viewers
    downstream of it. Sent before the `states` event of that edit.
  - `GET /api/nodes/{id}/output` of a done Map Layer: `outputs.layer` is the
    `describe()` text, `views.layer` a `summary` view, `keys.layer` the port
    key. A Panel on it shows the same (three lines: `Layer · <name> · <kind>`,
    `source <key start>….<port>`, then the style: colormap, bands or colour
    and field, opacity; `default` where the Map Viewer chooses).
- **Display tab**: Map Layer's ribbon icon is `gis:layers`. Map Layer and Map
  Viewer nodes and windows use the Display colour.
- **Map Layer window** (frontend): it shows colormap, opacity and name, plus
  bands for a raster, colour and `field` for a vector (all but `field` before
  the data's type is known), and any other input that is wired. A wired input
  whose value is used is read-only with "from <node title>" ("(last result)"
  for a component); one listed in `issues` stays editable, with the reason
  under it, and `issues.data` shows at the top. The colormap dropdown offers
  none and the named ramps (sent as the ramp name); a saved colormap that is
  more than a plain ramp shows as "(edited)" until another choice is made.
  Colour hex, bands and name are sent on Enter or blur (empty resets the
  field); the colour picker and opacity slider send once they rest (400 ms,
  or on pointer up), so a drag is one PATCH. "Reset all" sends `style: null`.
  The `field` dropdown is filled from `GET /api/layer/{id}` `columns`, and
  disabled until they are known. On `map_changed` the page re-reads the graph.
- **Export**: step 3 wrote a stub comment; step 5 wrote the full one
  (section 10 below).

## 9. Implementation choices (step 4)

Points sections 4 and 6 leave open, as built in step 4 (Map Viewer with Layers):

- **Wires**: `layers` is `Port("layers", Raster, types=[Raster, Vector, Layer],
  access=list)`. A Model, Table, Text, … wire is refused (400, `X can't connect
  to Raster | Vector | Layer`), and a Panel's wire is removed once the Panel
  carries such a type (the usual re-check). So "cannot be shown on a map"
  (`unsupported`) is now only reached by a value whose type the graph could
  not tell (a union output or `Any` pass-through whose result is something
  else, or a list of simple values stored as one JSON file); the code path is
  kept.
- **Lists**: a done list result stored one file per element gives one layer
  per element, id `<src>.<port>[i]`, title `<title> › <port> [i]`, key
  `<port key>[i]`; before a run (count unknown) it is one `not_run` stub
  `<src>.<port>`. `DiskCache.port_info` (and so `read_port`, `band_names`)
  accepts `<port key>[i]` itself (`cache.split_element`); `tiles._KEY` takes an
  optional `[\d+]`, so tiles, GeoJSON, stats and inspect answer element keys;
  the whole list port, an index out of range, and `[i]` on a port that is no
  list stay 404.
- **Layer wires** are found by following Panels back (`layers.origin_wire`): a
  Panel on a Map Layer wired in draws that Map Layer's layer. The layer id stays
  the wire's `<src>.<port>` (the Panel's, when wired through one); `title` is the
  layer's `name`; `key` is the layer's `source` once the Map Layer is `done`.
  Without data the stub is `not_run` with the Map Layer's `issues.data`.
- **`locked`** is a per-layer list next to `style` (not inside it), sorted. It
  holds the fields the Map Layer sets (`layers.set_fields`): `colormap`,
  `color`, `bands`, `field` when not `None`, and `opacity` only when wired or
  saved in the Map Layer (its default 1.0 leaves the viewer's opacity
  editable). Mapped to viewer style: a raster takes `colormap` (Colormap JSON),
  `bands`, `opacity`, and `min`/`max` too when a continuous Colormap has its own
  min or max; a vector takes `color`, `opacity`, and `colormap` + `field` only
  when both are set and the field exists (otherwise it is drawn with `color`).
  `style` = server default, then the viewer's saved `map.styles[id]`, then the
  locked values. `visible`, and any field not locked, stay editable and saved
  in `map.styles` as before.
- **Field range**: for a vector coloured by a continuous Colormap with auto
  min/max, the server computes the field's min/max over the features the
  GeoJSON carries (the first 50 000) and sends it as `vector.field = {name,
  numeric, min, max}` in `GET /api/map/{id}` (rather than the window scanning
  the GeoJSON itself, which MapLibre loads by URL).
- **Expressions** (`fieldColour` in `components/map/layers.ts`): classes →
  `["match", ["get", f], v1, c1, …, other]` when every class value is an
  integer (MapLibre's `match` takes integer labels only; a repeated value keeps
  its first class), else a `case` of `==` tests; a transparent `other` is
  `rgba(0, 0, 0, 0)`. Continuous → `["case", ["==", ["typeof", ["get", f]],
  "number"], ["interpolate", ["linear"], ["get", f], …stops], transparent]`, the
  stops being the Colormap's own (or its named ramp's 9 colours evenly) over
  min/max; equal min and max give the top colour. `#RRGGBBAA` colours go to
  MapLibre as `rgba(…)` (`cssColour`, in `palettes.ts`).
- **Draw order** stays as for raw wires: vectors above rasters, then wire order
  (first on top). The layer list is in wire order.
- **Window**: a layer from a Map Layer shows "Layer" as its type, a line "from
  Map Layer <name>" with a "Go to Map Layer" link, and its locked controls
  disabled (hovering one shows the same "from Map Layer <name>"); a vector
  coloured by a field shows "coloured by <field>" instead of the swatches.
  "Go to Map Layer" selects only that node on the canvas and frames it
  (`store.selectNode`, through `pendingSelect`). The vector legend is now drawn:
  a swatch and the layer's name.
- **Live redraw**: the store counts `map_changed` events whose `viewers`
  include the open Map Viewer (`mapVersion`); the window re-reads
  `GET /api/map/{id}` on each. Raster tiles get a new URL (new `cmap`), so
  MapLibre reloads them; vector paint is set again from the new style. A
  `map_changed` for another viewer does not re-read.

## 10. Implementation choices (step 5)

- **Examples**: `examples/synthetic/imd.geoknit` and
  `examples/milan_imd/milan_imd.geoknit` add a Colormap `n23` (classes 1–7,
  one per Reclassify rule, labelled `0 %`, `0–20 %`, …, `100 %`, green to dark
  red, `other` transparent), a Map Layer `n24` (`data` ← Reclassify
  `classes`, `colormap` ← `n23`, `style: {"name": "IMD classes"}`) and a Map
  Viewer `n25` (`layers` ← `n24.layer`, then Split Points `test`). Nothing
  reads them, so the metrics are unchanged; the predicted map is not wired in
  (it would put the viewer downstream of the sliders the canvas test moves).
- **Export comments**: `# <id> Map Layer "<name>": <data>, <input> <node>, …`
  with the name from `layers.layer_name` (wired Params value, saved style,
  else `<source title> › <port>`, else the node title without data), the
  data as `<node>.<port>` and each wired style input in
  `LAYER_STYLE_INPUTS` order; `no data` without a data wire. The Map Viewer
  is `# <id> Map Viewer: <node>.<port>, …` or `no layers`. Referenced nodes
  use the script's padded names (`n04`), the leading id the node id, as the
  other comments do.

---

## Not in this change

- Drawing or editing geometry on the map.
- Map export to PNG/PDF (a later Display component that will take Layers).
- Charts (a later Display › Plot group).
- Swipe / side-by-side comparison of two layers.
- Reordering layers inside the viewer (order stays wire order).
