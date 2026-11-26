# Change 03: Map layers and colormaps

Status: draft (checked against the code, 26 Nov 2026) · Needs 01 (types,
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

---

## Not in this change

- Drawing or editing geometry on the map.
- Map export to PNG/PDF (a later Display component that will take Layers).
- Charts (a later Display › Plot group).
- Swipe / side-by-side comparison of two layers.
- Reordering layers inside the viewer (order stays wire order).
