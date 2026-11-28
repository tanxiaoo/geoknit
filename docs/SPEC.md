# GeoKnit design spec (v0.1)

GeoKnit is a local, open-source visual programming tool for geospatial
analysis, modelled on Grasshopper for Rhino. Users place components on a
canvas, connect them with wires, change sliders, text and settings, and press
Run. Every component is a small Python script with declared inputs and
outputs, in the spirit of GHPython. The first target is land-cover and
continuous-variable mapping: sample → extract → train → predict → validate.

This file is the source of truth for behaviour. If code and spec disagree,
fix one of them in the same change.

---

## 1. Scope

### In v0.1

- Canvas editor in the browser, served locally by a Python backend.
- Data types Number, Text, Boolean, Raster, Vector, Table, Model, Color and
  Colormap (plus Layer for the Map Viewer), lists of them, ports that accept
  several types and outputs that follow an input's type (section 3).
- One component file format shared by built-ins, user Python components and
  community packs (section 4).
- Built-in components for the Milan IMD workflow and its close variants
  (section 7).
- Component window: Settings and Code tabs that edit the same component,
  Output log always visible.
- Panel component (inspect any output: values, lists, tables), Map Viewer with
  any number of layers, and Map Layer, which styles one layer with a Colormap
  or Color (section 8).
- Project folder panel; drag a file onto the canvas to get a Text with its
  path.
- Manual Run, Run to here, Test (one component), Stop.
- In-memory results in a long-lived worker process, plus a disk cache.
- Save and open `.geoknit` files; export a workflow to a plain `.py` script.
- Assistant panel as a visible placeholder; the backend API is already
  complete enough for an agent to drive the canvas (section 9).

### Not in v0.1

- Google Earth Engine components (v0.2 pack).
- Working AI assistant.
- Running a component once per list item (auto-iteration over years, tiles).
- Data trees (lists of lists).
- Named CSS colours.
- Choosing another Python environment or conda env.
- Desktop installer (`.exe`).
- UI translations (but all UI text lives in one file, see CLAUDE.md).

---

## 2. Architecture

```
Browser (React + React Flow)
   │  REST + WebSocket on 127.0.0.1
   ▼
Server process (FastAPI)          owns the graph, plans runs, serves files/tiles
   │  multiprocessing Pipe (spawn)
   ▼
Worker process                    imports geo libraries, runs components,
                                  holds results in memory, reads/writes cache
```

- The server never imports rasterio/geopandas/sklearn on the request path;
  heavy work happens in the worker. This keeps the UI responsive and lets
  Stop kill a stuck run without killing the app. Two exceptions read cached
  results in the server process: the Map Viewer (section 8), whose
  `server/tiles.py` imports rasterio, rio-tiler and geopandas the first time a
  map is opened, and the Panel's table pages (`server/tables.py`, section 9),
  which import pandas, pyarrow and shapely the first time a page is asked for.
- `geoknit/core` (graph, types, component format, solver, serialization,
  export) has no dependency on the server or frontend and can run headless.
  `geoknit run file.geoknit` uses it with a worker process but no server, so
  it shares the disk cache and Stop behaviour with the app.

---

## 3. Data types

| Type   | Python object | Port colour (light / dark) | Panel summary (`describe()`) |
|--------|---------------|-------------|-------------------------------|
| Number | `int` or `float` (not `bool`) | `#64748B` / `#94A3B8` | the value |
| Text   | `str` | `#A16207` / `#FBBF24` | the value (multi-line allowed) |
| Boolean | `bool` | `#0369A1` / `#38BDF8` | `True` / `False` |
| Raster | `xarray.DataArray` opened with rioxarray, dims `(band, y, x)`, lazy (dask-backed) | `#0B7A7C` / `#2DD4BF` | bands, band names, width × height, resolution, dtype, CRS, nodata |
| Vector | `geopandas.GeoDataFrame` | `#C2410C` / `#FB923C` | feature count, geometry type, CRS, columns |
| Table  | `pandas.DataFrame` (not geographic) | `#7C3AED` / `#A78BFA` | rows, columns, first 5 rows |
| Model  | `geoknit.types.ModelBundle` | `#BE185D` / `#F472B6` | estimator type, task, target, feature names, parameters |
| Color  | `geoknit.types.Color` | `#4D7C0F` / `#A3E635` | `Color #0B7A7C` |
| Colormap | `geoknit.types.Colormap` | `#4338CA` / `#818CF8` | kind, name, min/max or number of classes (`Colormap · continuous · viridis · 2–98 % stretch`) |
| Layer  | `geoknit.types.MapLayer`, a styled map layer from Map Layer to Map Viewer | `#A21CAF` / `#E879F9` | `Layer · <name> · <kind>`, its source, its style |

The port colours are the `--gk-type-<name>` tokens of the frontend theme
(section 8, "Theme"): the dark theme uses lighter shades of the same hues, so
wires stay visible on a dark canvas.

`geoknit.types` here means `geoknit/core/types.py`. `DATA_TYPES` (Python, and
`frontend/src/types.ts`) lists these ten types. Only Map Layer makes a Layer
(no port editor offers it).

`ModelBundle` is a dataclass: `estimator`, `task` (`"regression"` or
`"classification"`), `target: str`, `feature_names: list[str]`,
`info: dict`.

**Color** is a frozen dataclass `Color(hex)`, `hex` being `#RRGGBB` or
`#RRGGBBAA`, stored upper case; `rgba` gives the four channels (alpha 255
when the hex has none). `Color.parse(s)` accepts those two forms (any case)
and `r,g,b` / `r,g,b,a` with values 0–255; anything else (also a named CSS
colour such as `teal`) is an error naming the accepted forms.

**Colormap** is a frozen dataclass:

- `kind`: `"continuous"` or `"classes"`;
- continuous: `name` (one of the named ramps below, or `None` for custom),
  `stops: tuple[tuple[float, Color], ...]` with positions 0…1 in order (at
  least 2), `min: float | None`, `max: float | None` (`None` = the layer's
  2–98 % stretch; `min` below `max`), `reverse: bool`;
- classes: `classes: tuple[tuple[int | float, Color, str], ...]` (value,
  colour, label; each value once), and `other: Color | None` for values not
  listed (`None` = transparent).
- `Colormap.named(name, reverse=False)` builds a continuous colormap from the
  ten ramps the Map Viewer offers: viridis, magma, plasma, cividis, turbo,
  greys_r, terrain, rdylgn, spectral, blues. Their stops (11 each) are plain
  data in `NAMED_RAMPS` in `geoknit/core/types.py`, so exported scripts and
  `describe()` need neither matplotlib nor rio-tiler. The Map Viewer draws
  tiles from rio-tiler's 256-entry tables; a test checks that the 11 stops are
  samples of those tables (±1 per channel), so legends and tiles agree.
- `to_json()` / `from_json()` on Color and Colormap give the form used in the
  workflow file, the cache and the API: a Color is its hex text; a Colormap is
  `{kind, name, stops?, min, max, reverse}` (a named ramp whose stops were not
  edited leaves out `stops`) or `{kind: "classes", classes: [[value, hex,
  label], …], other}`. Unknown keys are an error.

**MapLayer** (the Layer value) is a frozen dataclass: `source` (the port key
of the data, a Raster or Vector result in the cache), `kind` (`"raster"` |
`"vector"`), `name`, `colormap: Colormap | None`, `color: Color | None`,
`opacity: float` (0–1, default 1), `bands: tuple[int, ...] | None` (1 or 3
band numbers from 1) and `field: str | None` (vectors only). `None` style
fields mean the Map Viewer's default for that layer. It holds no pixels or
features. Its JSON form (`to_json()` / `from_json()`) has the same keys,
`colormap` in Colormap JSON, `color` as hex, `bands` as a list.

`Any` is an input-only type (Panel, Map Viewer, inputs of the Python
component). An output is `Any` only while it is unresolved: an unwired Panel,
or a `like:` output whose `Any` input is not wired.

### Connection rules

- An output connects to an input of the same type, to an input that lists its
  type (below), or to an `Any` input.
- Conveniences: Number → Text and Boolean → Text (converted with `str`). They
  apply per listed type of an input and per element of a list.
- **Boolean is not a Number.** Python's `bool` is a subclass of `int`, so the
  check is explicit: a `bool` arriving at a Number input is an error
  (`input "n": expected Number, got Boolean`), and `0`/`1` arriving at a
  Boolean input is an error too. `numpy.bool_` counts as Boolean and is
  converted to `bool` when it is read as an output, so `result = a > b` works
  with numpy numbers (which count as Number).
- An unresolved output (an unwired Panel's pass-through) connects to any
  input; the value's type is checked when the receiving node runs
  (`input "x": expected Number, got Text`).
- Everything else is refused when the user drops the wire, with a tooltip
  such as "Raster can't connect to Number" or "Raster can't connect to
  Table | Vector".
- An input has `access: item` (default, one wire) or `access: list` (several
  wires, collected into one list, below). A second wire into an `item` input
  is refused ("input "x" of Reclassify is already connected"); remove the old
  wire first.
- Cycles are refused when the wire is created.
- Wires are re-checked graph-wide whenever a type can change: changing a
  component's code, a port edit, a Value List's options, or wiring,
  re-wiring or unwiring an input that a `like:` output follows. Wires whose
  port disappeared or whose type no longer fits are removed, and the nodes
  that lost a wire go out of date.

### Ports that accept several types

An input's `type` can be a list: `data: {type: [Table, Vector]}`.

- `Port.type` is the first listed type, and `Port.types` holds them all (one
  element for an ordinary port).
- An output connects to such an input when its type is one of the listed
  types (or the output is unresolved).
- When the node runs, the value must have one of the listed types, otherwise
  the error names them all: `input "data": expected Table | Vector, got
  Raster`.
- `Any` cannot appear in a list; a list of one type is the same as that type;
  a type listed twice is a parse error. Only inputs take a list of types;
  outputs use `like:`.

### Outputs that follow an input's type: `like:`

`selected: {like: data}` gives the output the type of the value wired into
input `data`. Before anything is wired it has the input's declared type (or
types).

- **Resolution** happens in the graph, from the wires, never from values:
  `Graph.output_type(node, port)` follows a `like:` output to the source of
  the named input, and on to that source's resolved type when it is itself a
  `like:` output, so chains work (Split Points → Select Rows → Sort Rows).
- **Panel follows the same rule.** Its pass-through output is
  `data: {like: data}`, so a Panel takes the type of what is wired into it and
  chains resolve through Panels (Read Vector → Panel → Select Rows is a Vector
  all the way). Read Raster → Panel → a Number input is refused when drawn.
- **Unresolved.** A `like:` output whose input is not wired connects to an
  input that accepts at least one of its possible types. When the input is
  wired later, the output resolves, and wires leaving it that no longer fit
  are removed (also downstream through further `like:` outputs).
- **Wiring checks** use the resolved type: when `data` is fed by a Vector,
  `selected` is a Vector and can only go where a Vector can go.
- **Loading and undo.** A wire leaving a `like:` output can come before the
  wire that resolves it in the file, so `graph_from_dict` and `apply_dict`
  check wires after all of them are added; load never drops wires that fit
  once everything is resolved.
- After the code runs, the output value must have the resolved type (a
  GeoDataFrame for Vector, a DataFrame that is not a GeoDataFrame for Table),
  otherwise `output "selected": expected Vector, got Table`.
- `like:` must name an input of the same component; anything else is a
  header parse error, and so is `like:` together with `type:`.
- For a `list` input, `like:` resolves to the type of its wires; wires of
  different types into an input that an output follows are refused
  (`all wires into "items" must have the same type`). The frontend refuses
  the same wire while dragging (section 8).
- A `like:` output of an `item` input of type `Any` that is fed by a list
  carries that list (a Panel passing one through, `Graph.output_is_list`).
  After the run its value must then be a list, and its elements are checked
  against the resolved type (`output "out": item 3: expected Number, got
  Text`), as for an `access: list` output. The worker gets these outputs with
  `run_node` (`RunNode.list_outputs`).
- Renaming an input (`was` in a `ports` edit, section 9) also renames it in
  every `like:` that names it, whether or not the outputs are editable or sent
  in the same edit. Removing an input that a `like:` names is a parse error.

### Lists

A list is an access mode, not a type: a wire can carry a list of values of
one type.

- An output declared `access: list` (`values: {type: Number, access: list}`,
  `sorted: {like: items, access: list}`) must hold a Python `list` (a `tuple`
  is converted); every element is checked against the output's type. An
  output that is not a list: `output "values": expected a list of Number, got
  Number`.
- Elements of a list *input* are checked too, with 0-based indices as the
  Panel shows them: `input "rasters": item 2: expected Raster, got Vector`.
- A list output connects to an `access: list` input. Several wires into a
  list input are concatenated in wire order: a single-value wire adds one
  element, a list wire adds all of its elements. This is decided by the
  source port, not by the value. A component returning `[3, 1, 2]` and a
  Number `7` wired into one list input give `[3, 1, 2, 7]`.
- `Graph.output_is_list(node, port)` says whether an output carries a list:
  an `access: list` output, or a `like:` output of an `item` input fed by a
  list (a Panel passing one through, also through chains of Panels).
- A list output into an `item` input is refused, naming the source node:
  `Numbers gives a list; "x" takes one value — use List Item` (a type
  mismatch is reported first). One exception: an `item` input of type `Any`
  (Panel's `data`) takes the whole list as one value. Panel's pass-through is
  then that list, so it connects only to list inputs that take its element
  type.

`describe()` must never read pixel data; it uses metadata only, so hovering
or a Panel on a 1 GB raster is instant. For a list it prints
`list of 3 Number` when every element has the same type (`list of 3`
otherwise, `list of 0` when empty), then `[i] ` and the first line of each
element's `describe()` for the first 50, then `… N more`.

---

## 4. Component format

One `.py` file is one component. The same format is used for built-ins,
the Python component on the canvas, components a user saves, and
community packs. This is the central idea of GeoKnit.

```python
# geoknit: component
# name: Reclassify
# category: Raster
# group: Calculate
# icon: gis:map-legend
# description: Turn a continuous raster into classes using break rules.
# inputs:
#   raster: Raster
#   breaks: Text
# outputs:
#   classes: Raster
# requires: [numpy]

# --- settings ---
no_match = "nodata"   # options: nodata | keep
dtype = "uint8"       # options: uint8 | int16

# --- code ---
import numpy as np
from geoknit.helpers import parse_breaks

rules = parse_breaks(breaks)
v = raster.values
out = np.zeros(v.shape, dtype=dtype)
...
classes = raster.copy(data=out)
print(f"{len(rules)} classes")
```

### Header

- The first comment block, starting with the line `# geoknit: component`.
- The rest of the block is YAML after stripping the leading `# `.
- Keys: `name`, `category` (ribbon tab), `group` (labelled group inside the
  tab; a non-empty scalar), `icon` (below), `description`, `inputs`,
  `outputs`, `ports` (below), `requires` (pip package names).
- A port is `name: Type`, or a mapping:
  - inputs: `type` (one type or a list, section 3), optional `access`
    (`item` | `list`, e.g. `values: {type: Number, access: list}`) and
    `file: write`;
  - outputs: `type` or `like: <input>` (section 3), optional `access: list`.
- `file: write` on a Text input names a file the component writes, e.g.
  `path: {type: Text, file: write}`. Such paths are not fingerprinted for the
  cache (section 6), so writing the file does not make the node out of date
  again.
- The name `INPUTS` is reserved: a port called `INPUTS` is a parse error
  (`"INPUTS" is reserved and cannot name a port`).

### Icons

`icon:` takes one of:

- `<set>:<name>` with `set` = `gis` ([Font-GIS](https://github.com/Viglino/font-gis)),
  `lucide` ([Lucide](https://lucide.dev)) or `tabler`
  ([Tabler](https://tabler.io/icons)), for example `icon: gis:buffer`. Choose
  in this order: Font-GIS first, then Lucide, then Tabler. A Font-GIS name is
  the file name of its SVG in the Font-GIS sources without the code-point
  prefix (`uEA85-map-legend.svg` → `gis:map-legend`, the same as its
  `fg-map-legend` CSS class); Lucide and Tabler use their kebab-case names
  (`lucide:grid-2x2-check`, `tabler:brand-python`). `docs/icons.md` lists
  every available name with a preview.
- a relative `.svg` path, resolved against the component file. It must stay
  inside the folder the component was loaded from (the pack folder, the user
  folder or the built-in folder), so `icons/x.svg` and `../shared/x.svg` both
  work in a pack. The server serves it (`GET /api/components/{ref}/icon`,
  section 9) and the frontend draws it in one colour (section 8). Draw it in
  black or `currentColor` on a transparent background.

An unknown name falls back to the category's icon and logs one console
warning per name; a missing `icon:` draws the category icon silently.

### Editable ports: `ports:`

```yaml
# ports: {inputs: editable, types: [Raster, Number]}
```

- `ports:` takes the keys `inputs`, `outputs` (value `editable` only) and
  `types` (a list of port types, or one name). At least one side must be
  editable; an unknown key or type, a type listed twice, or another value is a
  header parse error.
- `types` limits the types offered on the editable sides. Its default is every
  type except Layer and `Any`, and inputs may also be `Any`. Listing `Any` or
  `Layer` explicitly is allowed. The Python component declares
  `ports: {inputs: editable, outputs: editable}`, so its inputs can be `Any`;
  a component saved from it keeps the line, so it stays editable whatever its
  category.
- The server enforces it (`Graph.set_ports`): a side that is not editable may
  be sent back, but what it declares (names, order, types, `access`, `file`,
  `like`) must not change, otherwise `the inputs of Reclassify cannot be
  edited`. The same applies to both sides of a component without `ports:`, so
  its ports cannot be edited through the API. On an editable side every
  port's types must be in `types`: `Raster Calculator inputs are Raster or
  Number` (three or more: `A, B or C`). A port the header already declares
  outside `types` may stay, also renamed, as long as its type does not
  change. `like:` outputs are not checked against `types`; `access` and
  `file` stay editable.

### Settings block

- Between `# --- settings ---` and `# --- code ---`.
- Only top-level assignments whose value is a literal: int, float, str,
  bool, None, or a list/tuple of those. Anything else is a parse error,
  shown in the component's Output.
- An optional trailing comment shapes the Settings form:
  `# options: a | b | c` → dropdown, `# range: 0..1000` → number field with
  limits, `# multiline` → text area. No comment → text field. Options that
  read as numbers, `True`/`False` or `None` are those values; others are text.
- Each name may be set only once. A setting called `INPUTS` is a parse error
  (with its line number).
- A setting whose name equals an input name is that input's default value.
  An input with no same-named setting is required.

### Code block

Plain Python after `# --- code ---`. Inputs are available as variables, and
all together in the dict `INPUTS`; outputs are read back by name when the
code ends.

### Running one component

1. Create a fresh namespace.
2. Execute the settings block.
3. For each wired input, assign its value, overriding the setting. A wired
   value of the wrong type → error naming expected and actual type (all
   listed types for a union input; per element, with its index, for a list
   input).
4. A required input that is neither wired nor set → error
   `input "raster" is not connected`.
5. Set `INPUTS`: a dict of input name → value (the wired value, or the
   setting's value for an unwired input), in header order. Components whose
   inputs are not known in advance (Raster Calculator, Expression, Format)
   pass it to `safe_eval` / `str.format`.
6. Execute the code block with the project folder as working directory (so
   relative paths in Text components work), capturing `print`, stderr,
   warnings and logging (INFO and above) into the component's Output, one
   entry per line.
7. Read each declared output from the namespace. Missing → error. Wrong
   type → error naming expected and actual type. A `like:` output is checked
   against the type the graph resolved for it (the worker receives it with
   `run_node`, section 6); a list output element by element.
8. Exceptions show the traceback in Output, with line numbers relative to the
   component file.

The Python component on the canvas additionally has an `out` Text output
holding everything printed, as in GHPython. The rule is general: any
component with an output `out: Text` that its code does not set gets the
printed text there.

### Settings ↔ Code sync

- The Settings tab edits the settings block in place: parse with `ast`,
  replace only the source span of the changed literal, keep comments and
  formatting. A round-trip test must prove this.
- The Code tab edits the whole file (Monaco). On apply, the file is
  re-parsed; the Settings tab and the node's ports update from the header.
- If the header or settings block fails to parse, the Settings tab shows the
  error and is disabled until the code is fixed.
- The Code tab applies its text when the user leaves the tab, leaves the
  editor, presses Test or OK, or saves the workflow (Ctrl+S). Closing the
  window with × drops code that was not applied yet.
- Ports of a component with editable ports (`ports:`, above) are edited in
  its Settings tab: add, remove, rename, set type (limited to `types`). This
  rewrites only the header's `inputs:` and `outputs:` lines (other header
  lines, the settings block and the code stay byte-for-byte the same); the
  side that is not edited is written back unchanged, including `like:`,
  list outputs and `[A, B]` types. Wires on a renamed port follow it; wires on
  a removed port, or a port whose new type no longer fits, are removed. A new
  port gets a free name (`x1`, `y1`) and the first of `types`. A Python node
  whose saved source predates the `ports:` line has fixed ports until the
  line is added in its code.

### Where component code is stored

- Unmodified library component: the workflow stores a reference
  (`builtin/raster/reclassify`, version) plus the current settings values.
- Modified code (anything outside the settings block differs from the
  library source): the workflow stores the full source and
  `based_on: builtin/raster/reclassify@<version>`. The node shows a small
  "modified" mark, also after the workflow is saved and reopened (an inline
  node whose `based_on` the library no longer has still counts as modified).
- "Save as component…" writes the file to
  `~/.geoknit/components/<category>/<name>.py`, both names taken from the
  header in lower case with `_` for anything but letters and digits
  (`My NDVI!` → `my_ndvi`), giving the reference `user/<category>/<name>`.
  An existing file is replaced only after the user confirms. It appears in
  the ribbon under its category, marked as a user component. The node on the
  canvas is unchanged. The environment variable `GEOKNIT_USER_COMPONENTS`
  moves the folder (used by the end-to-end tests).
- "Open in VS Code" writes the component file to a temporary folder and
  starts VS Code (its `code` command) on it. While the server runs, the file
  is watched: saving it in VS Code applies the text to the node (one undo
  step, as from the Code tab; held back while a run is active), and changes
  made in GeoKnit (Settings tab, undo) are written back to the file.
  Opening another workflow stops the watching. Without `code` on the PATH the
  request is refused with a message saying so.

### Community packs

A pip package declares an entry point in group `geoknit.components` that
returns a folder path (the entry point is a path string or a function
returning one). Every component file in that folder is loaded at startup.
New categories become new ribbon tabs.

Component references, by source (each folder holds `<category>/<name>.py`;
files starting with `_` are ignored, and so is any file at the top of the
folder):

| Source | Reference |
|--------|-----------|
| built-in | `builtin/<category>/<name>` |
| `~/.geoknit/components/` | `user/<category>/<name>` |
| pack (entry point `fake = …`) | `fake/<category>/<name>`, version = the package version |

The names `builtin`, `user`, `inline` and `param` are reserved for packs. A
file that does not parse, or a pack that fails to load, is skipped with a
warning and never stops GeoKnit from starting.

### Ribbon tabs and groups

- Tabs, in order: Params, Maths, Sets, Table, Vector, Raster, Sampling,
  Model, Validation, Display, Script (`TABS` in
  `geoknit/components/layout.py`), then pack and user categories in
  alphabetical order (case-insensitive). A tab appears only when it has at
  least one entry.
- Built-ins and Params nodes: the order of groups and of components inside
  each group is fixed by `geoknit/components/builtin/_layout.yaml`, a map tab
  → group → references (`builtin/raster/clip`, `param/text`). References,
  because a tab can hold components from several folders and two folders can
  hold files with the same name (`raster/clip`, `vector/clip`). Built-in
  folder names follow the tab in lower case. The layout's tabs are a subset
  of `TABS` in that order. A test fails if a built-in component or Params
  node is missing from the layout, listed twice, or its `category:` /
  `group:` header disagrees with its place; at run time a reference listed in
  the layout takes the layout's tab and group.
- Pack and user components: groups in alphabetical order after the built-in
  groups of the same tab, components alphabetical inside a group. A `group:`
  that names a built-in group of the same tab joins that group, after the
  built-ins. No `group:` → group "Other", shown last.

### Display

Each node shows either its name (vertical, in the centre strip) or its icon.
A canvas-wide "Show as Text | Icon" switch sets the default; each node can
override it in its Settings tab.

---

## 5. Workflow file (`.geoknit`)

JSON, UTF-8, sorted keys, 2-space indent, so it diffs well in git.

```json
{
  "format": 1,
  "geoknit_version": "0.1.0",
  "nodes": [
    {
      "id": "n7",
      "component": "builtin/raster/reclassify",
      "version": "0.1.0",
      "settings": {"no_match": "nodata", "dtype": "uint8"},
      "position": [410, 10],
      "display": "default"
    },
    {
      "id": "n12",
      "component": "inline",
      "based_on": "builtin/model/random_forest@0.1.0",
      "source": "# geoknit: component\n...",
      "position": [250, 400],
      "display": "icon"
    },
    {"id": "n1", "component": "param/text", "value": "data/clms_imd_2018.tif", "position": [16, 41]},
    {"id": "n5", "component": "param/slider", "min": 50, "max": 1000, "step": 50, "value": 300, "position": [16, 480]},
    {"id": "n6", "component": "param/toggle", "value": true, "position": [16, 560]}
  ],
  "wires": [{"from": ["n1", "value"], "to": ["n2", "path"]}],
  "groups": [{"title": "Train · predict · validate", "nodes": ["n12", "n13"]}],
  "view": {"display": "text", "zoom": 1.0, "offset": [0, 0]}
}
```

- File paths in Text components are relative to the folder holding the
  `.geoknit` file when they point inside it (written with `/` on every OS).
- A library component whose code outside the settings block is unchanged is
  stored by reference with all its current settings values; otherwise it is
  stored `inline` with `based_on` (section 4).
- Params nodes and their stored fields:

  | Node | `component` | Output | Stored fields |
  |------|-------------|--------|---------------|
  | Text | `param/text` | Text | `value` |
  | Number | `param/number` | Number | `value`, `integer` (only when true) |
  | Number Slider | `param/slider` | Number | `min`, `max`, `step`, `value`, `integer` (only when true) |
  | Boolean Toggle | `param/toggle` | Boolean | `value` |
  | Value List | `param/value_list` | Number or Text | `options: [{label, value}]`, `value` (the chosen value) |
  | Color Swatch | `param/color` | Color | `value` (`"#RRGGBB[AA]"`) |
  | Colormap | `param/colormap` | Colormap | `value` (the Colormap JSON, section 3) |
  | Panel | `param/panel` | like its input | optional `size: [width, height]` once resized |
  | Map Layer | `param/layer` | Layer | `style` (below; `{}` for a new one) |
  | Map Viewer | `param/map` | – | optional `map: {basemap, styles}` (section 8) |

  Component nodes always have `display`.
- **Map Layer `style`** holds the values of its unwired style inputs and the
  vector `field` (section 8, "Map Layer"): keys `colormap` (Colormap JSON),
  `color` (upper-case `#RRGGBB[AA]`), `opacity` (a number 0–1), `bands`
  (text such as `"4,3,2"` or `"B04"`, spaces removed), `name` and `field`
  (non-empty text). It is checked on load and on `PATCH` (an unknown field or
  a bad value is refused, naming the node) and stored in that normal form, so
  save → load → save keeps the bytes. Editing it is one undo step; it is not a
  layout-only key like `map`, but it marks nothing out of date (section 6).
- **Map Viewer `map`**: `basemap` is `auto` (default, follows the theme),
  `light`, `dark` or `none`; `styles` maps a layer id to its style, whose
  `colormap` is a named ramp, `categorical`, or a Colormap JSON object.
- **Integer mode.** With `integer: true` a Number or Slider value is a Python
  `int`. Values are rounded half up (`2.5` → `3`, `-2.5` → `-2`, like the
  frontend's `Math.round`), exactly: an integer stays as it is (also above
  2^53) and a float is floored, then its fraction compared with 0.5 (so
  `0.49999999999999994` → `0`). A Slider also rounds `min` and `max` and
  makes `step` a whole number of at least 1 (`0.3` → `1`); a step of 0 or
  less is refused first (`slider step must be positive`), and a range that
  collapses (`0.2..0.4`) is refused (`slider min must be below max`). An edit
  is checked whole before anything changes, so a refused `PATCH {value:
  "abc", integer: true}` leaves the node (and the undo history) as it was.
  Turning it off keeps the rounded values. **On load** a Number or Slider with
  `integer: true` must already hold whole numbers (JSON integers, not `2.5`
  or `3.0`), a Slider a `step` of at least 1 and `min` below `max`; otherwise
  the file is refused, naming the node (`node "n3": integer mode needs whole
  numbers (value 2.5)`). It is refused rather than rounded so that a valid
  file keeps its bytes (save → load → save) and a hand-edited one never
  changes silently. A component that needs an integer and receives a float
  with a fractional part raises its own error; GeoKnit does not convert.
- **Value List.** `options` is a non-empty list of `{label, value}` (exactly
  these keys); `label` is text, `value` a number (not a Boolean) or text,
  each value listed once (`1` and `1.0` are the same value, `1` and `"1"` are
  not). The output is Number when every value is a number, otherwise Text; in
  a Text list a number option's value is given as text (`str`, as a
  Number → Text wire does). Its output port is computed from the node, and a
  change of type re-checks the wires leaving it (section 3). Changing the
  options keeps the chosen value when it is still an option, otherwise
  chooses the first. A Text Value List's value names a file like a Text
  node's (fingerprinted for the cache key).
- **Values in memory** are the Python values (`Color`, `Colormap`, `bool`,
  number, text); the file, the cache key and the API use their JSON form. A
  file whose Params value is invalid (a `bool` as a Number, `1` as a Boolean,
  a colour that does not parse, a value that is not one of the Value List's
  options) is refused on load, naming the node.
- New nodes start as: Number `0`; Boolean Toggle `false`; Value List options
  One = 1, Two = 2, Three = 3 with `1` chosen; Color Swatch `#0B7A7C`;
  Colormap `viridis` (named, 2–98 % stretch).
- Keys GeoKnit does not know are kept and written back unchanged.
- Saving a workflow that was just loaded produces the same bytes.
- `format` is bumped on breaking changes, with a migration function. A file
  with a newer `format` than GeoKnit supports is refused with a message
  asking to update GeoKnit.

---

## 6. Execution

### Node states

`never_run`, `out_of_date` (orange dot), `running`, `done`, `error` (red),
`skipped` (an upstream component failed).

### Out of date

Changing a setting, the code, a wire, or a Params value marks that node and
everything downstream `out_of_date`. On Run, components that read files also
check the file's size and modification time.

**View nodes.** Map Layer and Map Viewer only show results; they never need a
Run:

- Wires into a Map Layer's style inputs (`colormap`, `color`, `opacity`,
  `bands`, `name`) carry no out-of-date. Changing a Colormap, Color Swatch or
  Slider that only feeds those inputs marks that Params node itself out of
  date, as every Params edit does, and the open maps redraw at once
  (section 8). A `style` edit, wiring or unwiring a style input, and deleting
  a node that only feeds style inputs mark nothing out of date either; a Panel
  or component downstream of the Map Layer keeps its state until the next
  Run, which finds its key changed and runs it again (as for a changed file).
- View nodes are not in a run plan's work and are not counted in "N
  components out of date". Their state (`Solver.view_state`) follows their
  sources, which are a Map Layer's `data` wire and every wire into a Map
  Viewer's `layers`: `done` when all sources are; `skipped` when one is
  `error` or `skipped` (so a Panel on the layer is skipped too); `never_run`
  without sources or when one never ran; otherwise `out_of_date`. Style
  sources never affect it.
- A Run with mode `test` on a view node plans nothing; `to_node` plans its
  upstream. With view nodes in the graph, plans follow the whole graph's
  topological order, so a Panel on a Map Layer runs after a component wired
  into the layer's style.
- A `style` PATCH is refused during a run (409), as other result edits.

### Run commands

- **Run**: every node that is not `done` (out of date, never run, error,
  skipped), in topological order. A node whose upstream failed is `skipped`.
- **Run to here**: this node and the upstream nodes it needs.
- **Test** (component window): this node only, using cached inputs; errors
  if an input has no cached result yet.
- **Stop**: terminates the worker, marks the running node `error: stopped`,
  starts a fresh worker. In-memory results are lost; the disk cache stays.

Runs are manual only in v0.1. A toolbar banner shows
"N components out of date · Run".

### Worker protocol

Messages over a `multiprocessing` Pipe (spawn start method, also on Linux,
so behaviour matches Windows):

- server → worker:
  - `run_node {node_id, source, inputs: {port: cache_key | [cache_key, …]},
    cache_key, output_types, list_keys, list_outputs}`. Settings are part of `source`. A
    `list` input gets its keys in wire order. The worker does not know the
    graph, so `output_types: {port: type}` carries the resolved types of
    `like:` outputs (checked after the code runs), and
    `list_keys: frozenset[str]` the keys of list inputs that come from list
    outputs (their elements are concatenated; any other key adds one
    element), and `list_outputs: frozenset[str]` the `like:` outputs that
    carry a list although declared `item` (section 3). The in-process
    executor uses the graph directly.
  - `put_value {cache_key, value}`: a Params value (Text, Number, Slider,
    Boolean Toggle, Value List, Color Swatch, Colormap), an empty Panel's
    `None`, or a Map Layer's `MapLayer`, sent before each run so the worker
    can look it up. Map Layers are sent again after a component wired into a
    style input (directly or through Panels) finishes (its result now resolves, so later nodes get the new
    layer).
  - `clear_cache` (answered by `cleared {complete}`), `shutdown`.
- worker → server: `ready {pid}`, `started`, `log {line}`,
  `done {outputs: {port: {cache_key, summary, view}}, cached}`,
  `error {traceback}`, `cleared {complete}`. `cached` is true when the result
  came from worker memory or the disk cache without running the code.
  `summary` is the `describe()` text and `view` the Panel view (section 8),
  built next to it for every port (also for results read back from the disk
  cache and for `put_value` values) by `geoknit/core/views.py`. A view that
  fails to build becomes a summary view; it never fails a run.
- The worker's working directory is the project folder for its whole life,
  so a raster opened with a relative path still finds its file when it is
  read again later.
- Before anything imports rasterio, the worker removes `PROJ_LIB`,
  `PROJ_DATA` and `GDAL_DATA` from its environment when the rasterio wheel
  bundles its own PROJ/GDAL data. A system install (PostGIS, QGIS, OSGeo4W)
  often sets them to an older `proj.db`, which breaks every CRS operation.
  A non-wheel install (e.g. conda) is left alone.
- **Windows file locks**: an open raster file cannot be replaced or deleted
  on Windows, and lazy rasters keep their file open. After every node the
  worker closes the raster files xarray keeps open; lazy rasters reopen them
  on their next read. So users can overwrite a source raster between runs
  (the next Run sees the new size/mtime and recomputes), and the cache can
  delete its own files.
- Params nodes (Text, Number, Slider, Boolean Toggle, Value List, Color
  Swatch, Colormap, Panel, Map Layer, Map Viewer) are handled by the server,
  which also builds their summaries and views; only components go to the
  worker.
- If the worker dies on its own (e.g. a component calls `os._exit`), the
  running node gets `error` "the worker process stopped unexpectedly" and a
  fresh worker is started.

The server forwards these as WebSocket events to the browser.

### Cache

- Keys depend only on the graph and the files it names, so the server keys
  every node in topological order before running anything:
  - component: `sha256(cache format + component source with settings +
    upstream port keys of each input, ports sorted by name, wires in wire
    order + file fingerprints)`;
  - Params value nodes: `sha256({format, <kind>: <JSON value>, files})` with
    kind `text`, `number`, `boolean`, `color` or `colormap` (a Value List
    uses `number` or `text` after its type; a Slider `number`), and `files`
    the fingerprint of a Text value that names a file. So a Number and a
    Slider with the same value share a key; a Toggle `true` and a Number `1`
    do not. A Slider whose value only changes type (`5` → `5.0`) gets a new
    key;
  - Panel: no key; its output reuses the key of the wire feeding it;
  - Map Layer: no node key and no cache entry; its `layer` port key is
    `<sha256("layer" + data port key + style JSON)>.layer`, the style JSON
    being `MapLayer.to_json()` without `source` (sorted keys, compact
    separators). Without data the port key is the empty key (value `None`);
  - Map Viewer: no key and no outputs.
- A port key is `<node key>.<port>`.
- **File fingerprint**: a Text value, or a text setting of a component, that
  names an existing file (relative to the project folder) adds its absolute
  path, size and modification time. That is how "components that read files"
  are detected; no header key is needed. On every Run all keys are
  recomputed, and a `done` node whose key changed becomes `out_of_date`
  together with everything downstream.
- Files a component writes are not fingerprinted: a setting of a
  `file: write` input (section 4), and a Text whose wires all go to
  `file: write` inputs. A Text that also feeds a reader keeps its
  fingerprint. So a deleted output file is written again only after the
  node changes or the cache is cleared.
- Lookup order: worker memory → disk → run. Worker memory is lost on Stop or
  restart.
- Disk cache: `<project>/.geoknit/cache/<node key>/`, holding one file per
  output port plus `meta.json` (format, port types, summaries, size). Raster
  → COG (written as a tiled GeoTIFF window by window, then copied to a COG
  with overviews; band names kept as band descriptions). Vector →
  GeoParquet, Table → Parquet (pickle if Parquet refuses the dtypes), both
  written in row groups of 10 000 rows so a page of rows can be read alone.
  Model → joblib. Number, Text, Boolean, Color and Colormap → JSON
  (`{"value": …}`, Color and Colormap in their JSON form, rebuilt by the
  port type recorded in `meta.json`; numpy scalars such as `np.int64`,
  `np.float32` and `np.bool_`, also as list elements, are written as the
  Python number or `bool` they hold, so they read back as `int`, `float`
  and `bool`). A Raster that is still an unchanged
  lazy view of a file (straight from `rioxarray.open_rasterio`) is not
  copied: the cache writes `<port>.ref.json` (path, size, mtime, band names),
  and a changed source file makes it a miss.
- **Lists.** The `meta.json` port info of a list is `{type: <element type or
  null>, access: "list", count, file, format}`. `format: "json"` is a single
  `<port>.json` (`{"value": [...]}`), used when every element has the same
  JSON type (Number, Text, Boolean, Color, Colormap) and for an empty list.
  Otherwise `format: "list"`: a folder `<port>/` with one file per element
  named by its index in the element type's format (`0.tif`, `0.ref.json`,
  `1.parquet`, …) and `file: "<port>/index.json"` (`{"items": [<element
  info>, ...]}`). One element is addressed by `<port key>[i]`
  (`cache.split_element`; `DiskCache.port_info`, `read_port` and
  `band_names` accept it), which is how the Map Viewer draws list elements.
- COG overviews use nearest resampling for integer rasters (class values stay
  intact) and average for floats; the Map Viewer draws its tiles from them.
- Entries are written to a temporary folder and renamed, so a crash never
  leaves a half-written entry. A bump of the cache format makes old entries
  miss.
- Default limit 10 GB. Least-recently-used eviction (the modification time
  of `meta.json` is the last use) after each write. It never evicts the entry
  just written or any entry whose results are in worker memory, because
  those may be lazy views of its files. So the cache can stay above the limit
  while they are in use.
- Removing an entry deletes `meta.json` first, so it is invalid at once even
  if a file inside is still locked. Folders without `meta.json` (leftovers,
  temporary folders of crashed writes) are deleted on the next eviction.
- "Clear cache" in the menu: the worker drops its memory, then deletes the
  disk cache; every node becomes `out_of_date`.

### Large rasters (city scale, ~2 Sentinel-2 tiles, 64 bands)

- Built-ins never call `.load()` on a whole raster unless they must.
- Extract Values samples at point locations without loading the raster.
- Predict Raster works in windows (default 512 px), writes a COG into the
  cache and returns it opened lazily. It returns a lazy (dask) prediction;
  the cache writes it window by window, and the worker then replaces any
  computed raster output (also a list element) with the COG it just wrote
  (`DiskCache.written_rasters`), so downstream nodes read the file instead of
  computing it again. With the disk cache off (`--no-cache`) each downstream
  node computes the lazy raster itself.
- `describe()` uses metadata only.

---

## 7. Built-in components (v0.1)

Breaks syntax used by Reclassify: rules separated by `|`. A single number is
an exact match; `a-b` means a < x ≤ b. Exact rules are checked first.
Classes are numbered 1…N in rule order; 0 means no rule matched (nodata
pixels also get 0). With `no_match="nodata"` the output marks 0 as nodata;
with `keep`, 0 is an ordinary value. Example:
`0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100` gives one raster with 7
classes. The parser is `geoknit.helpers.parse_breaks`.

An output cannot share its name with an input (section 4), so components
that return a changed copy name their output after the result (`clipped`,
`selected`, `reprojected`).

Components are listed by tab and group, in ribbon order
(`builtin/_layout.yaml`, section 4).

| Tab › Group | Component | Inputs | Outputs | Settings / notes |
|-------------|-----------|--------|---------|------------------|
| Params › Input | Text | – | Text | value; edit inline on double-click |
| Params › Input | Number | – | Number | value, integer; edit inline on double-click |
| Params › Input | Number Slider | – | Number | min, max, step, value, integer |
| Params › Input | Boolean Toggle | – | Boolean | value; click toggles |
| Params › Input | Value List | – | Number or Text (from its options) | options (label, value), the chosen value |
| Params › Style | Color Swatch | – | Color | value (hex) |
| Params › Style | Colormap | – | Colormap | value; double-click opens the Colormap editor (section 8) |
| Params › Inspect | Panel | data: Any | data: `{like: data}` (pass-through) | shows the Panel viewer (section 8); yellow, resizable |
| Vector › Files | Read Vector | path: Text | vector | layer=None |
| Vector › Files | Write Vector | vector, path: Text (`file: write`) | file: Text | format from extension: .gpkg, .shp, .geojson, .parquet |
| Vector › CRS | Reproject | vector, crs: Text | reprojected: Vector | |
| Raster › Files | Read Raster | path: Text | raster | bands="all", masked=True; lazy, 512 px chunks with all bands |
| Raster › Files | Write Raster | map: Raster, path: Text (`file: write`) | file: Text | COG, compress="deflate" |
| Raster › Bands | Band Select | raster, bands: Text | selected: Raster | bands as "1,2,3" or names |
| Raster › Calculate | Reclassify | raster, breaks: Text | classes: Raster | no_match, dtype |
| Raster › Extent | Clip | raster, aoi: Vector | clipped: Raster | all_touched=False; AOI reprojected to the raster CRS |
| Raster › Extent | Align Raster | source, reference: Raster | raster | resampling="nearest"; reads the whole source (the one built-in that is not lazy) |
| Sampling › Draw | Random Sample | raster, aoi: Vector, n, seed | points: Vector | only valid (non-nodata) pixels of band 1; an `id` column |
| Sampling › Draw | Stratified Sample | classes: Raster, value: Raster, aoi: Vector, n: Number, seed: Number | points: Vector | equal n per class (warn if a class has fewer pixels); points at pixel centres; value_field="value", class_field="cls"; classes and value on one grid; reads band 1 of both inside the AOI's bounding box |
| Sampling › Split | Split Points | data: Table \| Vector | train, test: `{like: data}` | test_fraction=0.3, seed=42, stratify_by=None; splits points (held out for validation) or table rows; the input's `attrs` (`feature_columns`, set by Extract Values) are copied to both outputs, so Random Forest `features="auto"` still works |
| Sampling › Extract | Extract Values | points: Vector, raster: Raster | table: Table | columns from band descriptions, else b01…; keeps point attributes; drops nodata rows with a warning; sets `table.attrs["feature_columns"]` |
| Model › Train | Random Forest | table, target: Text, n_trees, max_depth, min_leaf, seed | model: Model | task="regression", max_features="sqrt", features="auto" (feature_columns attr, else numeric columns except target); trains on all cores, predicts on one thread so maps are repeatable |
| Model › Train | SVM | table, target: Text | model: Model | task, kernel="rbf", C=1.0, gamma="scale", standardize=True |
| Model › Apply | Predict Raster | model, raster | map: Raster | window=512; band names must equal `model.feature_names`, else error listing the missing ones; float32 for regression, smallest int type for classes |
| Validation › Classification | Confusion Matrix | map, reference: Vector, field: Text | matrix: Table, metrics: Table | matrix: reference classes as rows, map classes as columns; metrics: columns metric, class, value; overall accuracy and kappa first, then producer's/user's accuracy and F1 per class |
| Validation › Regression | Regression Accuracy | map: Raster, reference: Vector, field: Text | metrics: Table | one row: n, dropped, RMSE, MAE, R², bias (observed − predicted); nearest pixel; points outside, on nodata or without a value dropped and counted |
| Display › Style | Map Layer (`param/layer`) | data: Raster \| Vector; colormap: Colormap; color: Color; opacity: Number; bands: Text; name: Text | layer: Layer | a view node, no code; unwired style inputs set in its window and saved under `style` (section 8) |
| Display › Map | Map Viewer (`param/map`) | layers: Raster \| Vector \| Layer (list) | – | a view node, no code; double-click opens the map window (section 8); styles saved with the node |
| Script › Python | Python | user-defined | user-defined + out: Text | `ports: {inputs: editable, outputs: editable}`: ports added/removed in the component window; the template has no inputs |

Random Forest and SVM inputs that also appear as settings (n_trees, max_depth,
min_leaf, seed) can be left unwired; the setting is then used.

Built-in references are `builtin/<folder>/<file>`, e.g.
`builtin/sampling/split_points` and `builtin/validation/regression_accuracy`.
Change 04 adds the Geometry components (Point, Polyline, Polygon, Bounding
Box: ordinary components in `builtin/params/`, Params › Geometry, between
Input and Style). Map Viewer sits in Display › Map; its id `param/map` is
the one it had under Params.

### Reference workflow: Milan IMD (`examples/milan_imd/`)

```
Text data/CLMS_2018_Milan_UTM32N.tif ─ Read Raster ─┬─ Reclassify ← Text breaks ─┐
                                                    └──────────── value ─────────┤
Text data/aoi_milan.gpkg ── Read Vector ─────────────────────── aoi ─────────────┤
Slider n, Slider seed ───────────────────────────────────────────────────────────┴─ Stratified Sample ─ Split Points ─┬─ train
Text data/AlphaEarth_2018_Milan_UTM32N.tif ─ Read Raster ──┬─ Extract Values ← train points                           │
                                                           │        └─ Random Forest ← Text "IMD", Slider n_trees     │
                                                           └─ Predict Raster ← model ─┬─ Write Raster ← Text outputs/imd_rf.tif
                                                                                      └─ Regression Accuracy ← test points, Text "IMD" ─ Panel
Reclassify ─ Map Layer "IMD classes" ← Colormap (7 classes, labelled) ─┬─ Map Viewer
Split Points test ─────────────────────────────────────────────────────┘
```

The Map Viewer (with its Map Layer and IMD class Colormap, one class per
Reclassify rule) is off the metrics path: nothing reads it, so it never
changes the metrics. `examples/synthetic/imd.geoknit` is the same workflow,
map included, on generated data.

Validation uses held-out sample points, not separate reference data:
Stratified Sample stores the CLMS IMD of each point in the field `IMD`;
Split Points (stratified by class, 30 % test) sends the training points to
Extract Values and the test points to Regression Accuracy, which compares the
predicted map at each test point with its `IMD`.

The data files are copied into `examples/milan_imd/data/` by the user and are
git-ignored:

| File | Content |
|------|---------|
| `CLMS_2018_Milan_UTM32N.tif` | 1 band, CLMS IMD 2018 in %, float32, nodata 255 |
| `aoi_milan.gpkg` | one polygon (layer `milano_city_rect_UTM32N`) |
| `AlphaEarth_2018_Milan_UTM32N.tif` | 64 bands named A00…A63, float32, nodata NaN |

All rasters are EPSG:32632, 10 m. The AlphaEarth GeoTIFF is exported from
Earth Engine once, outside GeoKnit.

---

## 8. User interface

Layout, top to bottom and left to right. The design mockups are in
`docs/ui/`: `01-main.png` (canvas, names), `02-icon-mode.png` (canvas,
icons), `03`–`06` (component window), `07` (Map Viewer). They are drawn in the
light theme and are not made from the app; the app's own screenshots are in
`docs/img/milan/` (section 12).

- **Top bar**: GeoKnit logo, workflow file name and save state, worker
  status, the theme button (Lucide `sun-moon`, "Theme" below), Export .py,
  Stop, Run. The top bar is navy in both themes.
- **Ribbon**: one tab per category, in the order of section 4 ("Ribbon tabs
  and groups"); inside a tab the components sit in labelled groups,
  Grasshopper style; search box. The ribbon is built entirely from
  `GET /api/components` (`tabs` and the ordered `components`, Params nodes
  included); the frontend hard-codes no tab, group or order. Search matches
  names and group names and shows each result's place as "Tab › Group".
  Double-clicking empty canvas opens the same search as a popup at the
  cursor.
- **Project folder (left)**: just the file tree of the project folder.
  No buttons or info box. Hides `.geoknit/`. Dragging a file onto the canvas
  creates a Text component with its relative path. Refreshes after each run
  and on window focus.
- **Canvas (centre)**: grid background. Grasshopper-style nodes: input
  names on the left, a coloured centre strip with the vertical name or the
  icon, output names on the right. Port dots and wires coloured by type.
  Out-of-date nodes and their incoming wires are faded with an orange dot.
  Errors red. Selected nodes outlined green. Groups are labelled boxes.
  The centre strip is coloured by category (the `tabs` colours): Params,
  Maths, Sets, Script and pack categories `#475569`; Table `#7C3AED`; Vector
  `#C2410C`; Raster `#0B7A7C`; Sampling `#B45309`; Model `#BE185D`;
  Validation `#15803D`; Display `#A21CAF`. A category that is no tab (an
  inline component's own category) is `#475569`. The strips have the same
  colours in both themes, with white text.
- **Ports**: a union input's dot is drawn in the first listed type's colour
  with a thin ring of the second; the hover summary names all types. Output
  colours and drag checks follow `resolved_types` (`GET /api/graph`, the
  types the server's own wiring checks use: one once resolved, an unwired
  Panel's `["Any"]`, and for a `like:` output fed by an unresolved one, the
  types that one can have, e.g. a Panel after an unwired Split Points is
  `Table | Vector`); without them `resolved_type`, then the declared `types`.
  A port that carries a list (an output whose
  `resolved_access` is `"list"`, an `access: list` input, a Panel's input
  when its output carries a list) gets a second ring in its type's colour
  outside the white one; a list wire is a wider stroke with the canvas colour
  drawn down its middle, Grasshopper's double line. Wires take the source
  output's flag. While dragging, the frontend checks wires with the server's
  rules and messages (`wireError` in `types.ts`, type mismatch first, then a
  list into an item input, then `all wires into "items" must have the same
  type` for a list input that an output is `like`, from the arriving types
  of the wires already in it), and the search popup for a wire dropped in empty space only offers ports that
  pass the same check.
- **Params nodes on the canvas**:
  - Text: a pill with a "T" badge, edited inline on double-click.
  - Number: a pill with a "#" badge, edited inline like Text (double-click,
    Enter or blur sends, Escape cancels). Text that is not a number (`abc`) is
    not sent; a toast says `"abc" is not a number`. While editing, a "whole
    numbers" box next to the field switches integer mode at once (its own
    undo step).
  - Number Slider: a track with its value; double-click opens a small window
    with min / max / step / value and a "whole numbers" box; OK sends them in
    one `PATCH`.
  - Boolean Toggle: a pill with a switch; the switch and its `True` / `False`
    label are one button, and a click sends `value: !value` (one undo step).
  - Value List: a dropdown on the node lists the labels and sends the chosen
    option's value. Double-click outside the dropdown opens a small options
    window (label and value per row, add, remove, OK / Cancel); OK sends
    `options` only, so the server keeps the chosen value when it is still an
    option. A value typed as a number (`3`, `-0.5`, `1e3`) is a number,
    anything else text; a row whose value text was not touched keeps its
    value as it was (so text `"1"` stays text). A blank label takes the
    value's text. The port colour follows the server's `outputs[0].type`.
  - Color Swatch: a swatch; double-click opens a window with
    `<input type=color>` and a hex field. The picker has no alpha, so picking
    keeps the field's `AA`; the field also takes `r,g,b[,a]`, checked by the
    server.
  - Colormap: a gradient strip (class chips for a classes colormap) with the
    ramp's name (`custom` for own stops, `N classes`). Double-click opens the
    Colormap editor (below). Named ramps are drawn from the 11 stops of
    `GET /api/colormaps`, loaded once when the first Colormap node is drawn
    (a custom colormap from its own `stops`; `reverse` flips them).
  - Map Layer and Map Viewer (Display tab) are drawn as component nodes in the
    Display colour; double-click opens their windows (below).
  - Panel: a yellow box with its input on the left and its pass-through
    output on the right, showing the Panel viewer (below).
- **Icons** (section 4): `frontend/src/icons/registry.tsx` maps prefixed
  names to icons and holds only the icons in use (built-in headers, Params
  entries, tab fallbacks), so the wheel does not carry full icon sets.
  Lucide icons come from `lucide-react`; the Font-GIS and Tabler icons used
  are SVG files in `frontend/src/icons/vendor/gis/` and `…/tabler/`, imported
  with Vite's `?raw` suffix and inserted inline. On copy (Font-GIS from the
  `font-gis` npm package 1.0.6, `svg/`; Tabler from `@tabler/icons` 3.53.0,
  `icons/outline/`; neither is a dependency), Font-GIS files lose their
  Inkscape metadata and ids and get a `viewBox`, every fill and stroke colour
  becomes `currentColor`, and a comment at the top credits the author and
  licence and says what changed. So icons follow the text colour. A pack's
  `.svg` icon is drawn in the ribbon, search and node as a CSS mask filled
  with `currentColor` (one colour, and an SVG's scripts never run), from
  `componentIconUrl(ref)` (`api.ts`); if it fails to load, the category icon
  is drawn instead. The icon is the library header's: a node whose source was
  edited uses its library component's, an inline node the one of the
  component it is `based_on` (none: the category icon). Params icons are
  `PARAM_ICONS` in `geoknit/components/layout.py`; tab fallbacks
  (`CATEGORY_ICONS`): Params `lucide:sliders-horizontal`, Maths
  `lucide:calculator`, Sets `lucide:list`, Table `lucide:table`, Vector
  `gis:polygon-pt`, Raster `gis:mosaic`, Sampling `gis:multipoint`, Model
  `lucide:trees`, Validation `lucide:target`, Display `gis:map`, Script and
  pack or user tabs `lucide:code`. An unknown name logs `GeoKnit: unknown
  icon "x"; using the category icon (see docs/icons.md)` once per name.
- **`docs/icons.md`** has one row per available name (preview, name, set and
  licence) and a note for pack authors. GitHub does not render inline SVG,
  so the previews are files in `docs/icons/` (`gis-map.svg`, …) drawn in
  `#64748b`, readable on light and dark backgrounds. A vitest test generates
  both from the registry and fails when the checked-in Markdown or folder
  differs (missing, changed or extra file); `UPDATE_ICONS=1 npx vitest run
  src/icons` in `frontend/` writes them. It reads the built-in headers with
  `import.meta.glob(…, {query: "?raw"})` and the `PARAM_ICONS` block of
  `layout.py` with `?raw`, so `PARAM_ICONS` keeps literal keys and values.
  Another test checks that every built-in and Params icon resolves.
- **Canvas toolbar**: zoom − / % / +, Fit, "Show as Text | Icon" (saved in
  the workflow's `view`), a hint, and the banner "<what changed> · N
  components out of date · Run". Right-clicking a node offers Run to here.
- **Status bar (bottom)**: data-type colour legend, state legend.
- **Assistant (right)**: collapsible placeholder marked "Next version".

Component window (double-click a node): floating and draggable, header with
category and name (and the "modified" mark); tabs **Settings** (inputs with
their wired source or an editable default, the component's settings, "show
on canvas as"; ports too for components with editable ports) and **Code**
(Monaco editor with the full component file, Open in VS Code); **Output**
always visible below both tabs (state, log lines of the last run, the
traceback of an error); buttons Save as component…, Test and OK. Settings
fields apply on change (dropdowns) or on Enter / leaving the field; each
change is one undo step. Test runs this component only, using cached inputs
(`POST /api/run` `mode: test`). OK applies the code and closes. Monaco is
bundled with the frontend (no CDN) and loaded the first time a Code tab
opens.

- The Settings tab shows the inputs editor when `editable_ports.inputs`, the
  outputs section when `editable_ports.outputs`; the type list offers
  `types` (`input_types` for inputs, plus the port's own type when it is
  outside them); a new port gets the first of `types` (on either side);
  picking a type for a union input replaces its types. A `like:` output has no
  type to pick: it shows `like <input>` (`strings.likeInput`). Renaming an
  input sends `was`, and the server renames the `like:` that follows it.
- A wired Params value is shown as `wired: Boolean Toggle = True`,
  `wired: Value List = One` (the option's label), `wired: Colormap =
  viridis`, `wired: Number = 3`, `wired: Color Swatch = #0B7A7C`.

### Panel viewer

A Panel shows what passes through it, by type:

| Value | Panel shows |
|-------|-------------|
| Number, Text, Boolean | the value (Number and Text as sent, so NaN shows `nan`; a Boolean as `True` / `False`) |
| Color | a swatch and the hex value |
| Colormap | its gradient; classes: one row per class, a chip and its label (the class value when the label is empty), and a last chip labelled `other` when there is an `other` colour |
| list | the header line `list of N Type` (as `describe()`'s first line; `list of N` when mixed), then one row per element: its index and its one-line view (a Color: a small chip and the hex; a Colormap: a small strip and its name; otherwise the first line of `describe()`), and `… N more` past the first 50 |
| Table | a scrollable grid with an index column and the column headers, under a header line "N rows × M columns" |
| Vector | its attribute table, as for Table, with the geometry column showing the geometry type name (`Polygon`, `Point`, …, in italics) |
| Raster, Model, Layer | the `describe()` summary (a Layer: name, source and style, section 8 "Map Layer") |

- **Views.** The worker sends a `view` next to each port's summary
  (section 6); Params nodes build theirs in the server. A Panel's view is the
  view of the value passing through (an unwired Panel: the `None` summary
  view). `kind` says the shape:
  - `{kind: "value", type: "Number" | "Text" | "Boolean", value}` (NaN and
    infinities as `"nan"`, `"inf"`, `"-inf"`, as `describe()` prints them);
  - `{kind: "color", type: "Color", value: "#RRGGBB[AA]"}`;
  - `{kind: "colormap", type: "Colormap", value: <Colormap JSON>}` (a named
    ramp's stops come from `GET /api/colormaps`);
  - `{kind: "list", type: <element type, or null when mixed>, count,
    items: [<element view>, …]}`, the first 50 elements. An element view is a
    `value` / `color` / `colormap` view, otherwise `{kind: "summary", type,
    text}` with the first line of its `describe()` (also for a Table or
    Vector element: no grid inside a list);
  - `{kind: "table", type: "Table" | "Vector", columns, rows, index,
    total_rows, offset, geometry}`: the first page (200 rows) in the shape of
    `GET /api/table/{key}` (section 9);
  - `{kind: "summary", type: <type or null>, text: <describe()>}` for Raster,
    Model and anything else.
- The store keeps `views` per node and port (from `done` events, and from
  `GET /api/nodes/{id}/output` after a reload). A Panel that is wired and
  `done` draws its view (`components/nodes/PanelView.tsx`); otherwise it
  shows "(empty)", "run to update" or the error, and a result without a view
  falls back to the `describe()` text.
- **The grid.** Missing cells are blank, booleans `True` / `False`. Column
  widths are set once per result in characters (monospace) from the header
  and the first page, between 3 and 32 characters; longer text is cut with
  `…` and shown whole on hover. The header row and the index column stay in
  view while scrolling. The Panel stays resizable and the grid scrolls inside
  it. Later pages (200 rows) are read from the disk cache
  (`GET /api/table/{key}`) when the grid is within 120 px of its end (also
  right after a page arrives, so a Panel taller than its rows fills itself).
  A page that comes back empty before `total_rows` rows are shown ends the
  paging for that result (it would otherwise be asked for again at the same
  offset). The paging key (`keys.data`) and `disk_cache` come from
  `GET /api/nodes/{id}/output`, fetched once per result when a Panel shows a
  table.
- **Disk cache off** (`disk_cache` false): the Panel shows the first page
  and, when the table has more rows, the note "the disk cache is off: only
  the first 200 rows". A failed page (e.g. an entry evicted since) shows
  `could not load more rows: <detail>` at the end of the grid, and the Panel
  stops paging until the next result.
- `geoknit run` and the export keep printing the `describe()` text
  (section 10); only the canvas has the viewer.

### Colormap editor

Double-clicking a Colormap node opens a floating window:

- **Kind**: Continuous | Classes, with a preview strip at the top.
- **Continuous**: a named ramp (the ten of section 3) or Custom; Reverse;
  min and max each "auto" (the layer's 2–98 % stretch) or a fixed number.
  Custom shows the gradient with draggable stops; a click on the bar adds a
  stop; each stop has a colour picker with a hex field and a position 0–1.
- **Classes**: a table value | colour | label with Add, Remove and reorder;
  "Other values": transparent or a colour; "Fill colours from ramp" assigns
  colours from a named ramp to the listed values in order.
- **Paste**: lines of `value, #hex, label` (tab or comma separated) pasted
  into the table replace it, so a legend kept in a spreadsheet comes in at
  once.
- Each change is one `PATCH /api/nodes/{id}` `{value}`, so one undo step. It
  makes a component that uses the Colormap out of date as usual, and redraws
  open maps that use it through a Map Layer without a Run (section 6, "View
  nodes").

### Map Layer

A Map Layer (`param/layer`, Display › Style, ribbon icon `gis:layers`)
styles one map layer. It is a view node handled by the server, like Panel:
no code, no worker run.

| Input | Type | Default |
|-------|------|---------|
| data | Raster \| Vector | required |
| colormap | Colormap | none → the Map Viewer's default for that layer |
| color | Color | none → the Map Viewer's default vector colour (`#d62728`, both themes) |
| opacity | Number | 1.0 (0–1) |
| bands | Text | none → the default band choice (Map Viewer, "Rasters"); `"1"` or `"4,3,2"`, numbers or band names, 1 or 3 bands |
| name | Text | the source node's title and port (`Reclassify › classes`) |

Output: `layer: Layer` (a `MapLayer`, section 3).

- **Style values** (`geoknit/core/layers.py`). Each style input takes, in
  order: a wired Params node's current value (followed through Panels, also
  when that node is out of date); a wired component's last done result, read
  from its disk cache entry; the value saved in `style` (section 5); the
  default. A wired value of the wrong type (after the usual Number → Text
  conversion), an opacity outside 0–1, unknown band names, or a component
  without a usable result (not run yet, or the disk cache is off) count as
  unwired. A style input wired from a list is refused (they are `item`
  inputs).
- **Kind** comes from the data wire's type in the graph; when that is
  ambiguous (a union output) it comes from the data's done result. So the
  layer, and its port key (section 6), exist before any run whenever the
  graph types say Raster or Vector. Band names in `bands` are matched against
  the raster's band names read from its cache entry (no pixels); `field` is
  kept only for vectors.
- **Vectors by field**: a `colormap` on a vector layer colours its features
  by the attribute `field`, chosen in the window from the vector's columns.
  The colormap is continuous for numeric fields and matches classes on the
  field's values. Without `colormap` (or without `field`), vectors use
  `color`.
- **Window** (double-click): colormap, opacity and name, plus bands for a
  raster, colour and `field` for a vector (all but `field` before the data's
  type is known), and any other input that is wired. A wired input whose
  value is used is read-only with "from <node title>" ("(last result)" for a
  component); one whose wired value is not used stays editable, with the
  reason under it, and a problem with `data` shows at the top. The colormap
  dropdown offers none and the named ramps (sent as the ramp name); a saved
  colormap that is more than a plain ramp shows as "(edited)" until another
  choice is made. Colour hex, bands and name are sent on Enter or blur (empty
  resets the field); the colour picker and opacity slider send once they
  rest (400 ms, or on pointer up), so a drag is one PATCH. "Reset all" sends
  `style: null`. The `field` dropdown is filled from `GET /api/layer/{id}`
  `columns`, and disabled until they are known. On `map_changed` (section 9)
  the page re-reads the graph.
- **Panel** on a Layer shows three lines: `Layer · <name> · <kind>`,
  `source <key start>….<port>`, then the style (colormap, bands or colour and
  field, opacity; `default` where the Map Viewer chooses).

### Map Viewer

Map Viewer window: MapLibre map with an OpenStreetMap basemap (light or
dark, following the theme by default), a layer list from the wired inputs,
per-layer colormap / min / max / band(s) / opacity, a legend, and
click-to-inspect pixel values of every layer. Its `layers` input is `{type:
[Raster, Vector, Layer], access: list}`: a raw Raster or Vector wire is styled
in the window, a Layer wire by its Map Layer.

- **Node and window**: the canvas node shows its `layers` input and how many
  layers are wired; double-click opens the map window (no Settings/Code
  tabs). The window is a floating, draggable panel: on the left the basemap,
  the layer list (show/hide, style, legend, reset to defaults) and Inspect;
  on the right the map, framed on all layers when it opens and whenever the
  set of drawable layers changes. It reloads its layers after every run and
  when wires change. MapLibre is bundled with the frontend (no CDN) and
  loaded the first time a map opens.
- **Layers**: one per wire, in wire order, with the id `<node id>.<port>` of
  its source. A layer is read from the disk cache by the port key of its
  source's last successful run, so it shows only after a Run, and not at all
  with the disk cache off. A Table, Model, Text, … wire is refused (`X can't
  connect to Raster | Vector | Layer`), and a Panel's wire is removed once the
  Panel carries such a type, so "cannot be shown on a map" (`unsupported`) is
  only reached by a value whose type the graph could not tell (a union output
  or `Any` pass-through whose result is something else, or a list of simple
  values stored as one JSON file). Vectors are drawn above rasters;
  otherwise the first wire is drawn on top. The layer list is in wire order.
- **Lists**: a list wire adds one layer per element. A done list result
  stored one file per element gives the ids `<node id>.<port>[i]`, titles
  `<title> › <port> [i]` and keys `<port key>[i]`; before a run (count
  unknown) it is one `not_run` stub `<node id>.<port>`. The tile, GeoJSON,
  stats and inspect routes answer element keys; the whole list port, an
  index out of range, and `[i]` on a port that is no list answer 404.
- **Layer wires** (from a Map Layer, also through Panels): the layer's data
  is the Map Layer's `source`, so it is ready when that source is `done`, as
  for a raw wire. The layer id stays the wire's `<src>.<port>` (the Panel's,
  when wired through one); the title is the layer's `name`. Without data the
  layer is a `not_run` stub with the Map Layer's data issue. The fields the
  Map Layer sets (`colormap`, `color`, `bands`, `field` when not `None`, and
  `opacity` only when wired or saved in the Map Layer) are `locked`: their
  controls are disabled with "from Map Layer <name>" (also on hover), and a
  "Go to Map Layer" link selects only that node on the canvas and frames it.
  The layer shows "Layer" as its type; a vector coloured by a field shows
  "coloured by <field>" instead of the colour swatches. A raster takes
  `colormap`, `bands`, `opacity`, and `min` / `max` too when a continuous
  Colormap has its own; a vector takes `color`, `opacity`, and `colormap` +
  `field` only when both are set and the field exists (otherwise it is drawn
  with `color`). The style is the server default, then the viewer's saved
  `map.styles[id]`, then the locked values. `visible`, and any field not
  locked, stay editable and saved in `map.styles`.
- **Live redraw**: when a Map Layer, or a Params node that feeds one,
  changes, the server sends `map_changed {node, viewers}` (section 9); an open
  window whose node is among `viewers` re-reads `GET /api/map/{id}`. Raster
  tiles get a new URL (new `cmap`), so MapLibre reloads them; vector paint is
  set again from the new style. No component runs.
- **Rasters**: 256 px Web Mercator PNG tiles rendered by rio-tiler from
  overviews, transparent outside the raster and on nodata. Defaults:
  exactly 3 bands → RGB; an integer band with at most 32 distinct values →
  classes in a fixed palette (class `v` gets colour `v mod 20`); otherwise
  band 1 with `viridis`. Min/max default to the 2–98 % percentiles of the
  shown bands, read from an overview. Colormaps: the ten named ramps
  (section 3), `categorical`, or a Colormap (section 3).
- **Colour step** (`server/tiles.py`): rio-tiler only reads the pixels; the
  colouring is GeoKnit's own numpy step. A named ramp that is not customised
  uses rio-tiler's 256-entry table (`_lut`). A continuous Colormap becomes a
  256-entry lookup table built from its stops and rescaled by its min/max
  (else the layer's). A classes Colormap becomes a value → RGBA lookup in the
  same step as the `categorical` palette: `other` colours the rest, or makes
  it transparent when `None`, and an `#RRGGBBAA` colour multiplies the tile's
  alpha. Without a Colormap, small-integer rasters keep the `v mod 20`
  palette.
- **Vector colours from a Colormap** (`fieldColour` in
  `components/map/layers.ts`): classes → `["match", ["get", f], v1, c1, …,
  other]` when every class value is an integer (a repeated value keeps its
  first class), else a `case` of `==` tests; a transparent `other` is
  `rgba(0, 0, 0, 0)`. Continuous → `["case", ["==", ["typeof", ["get", f]],
  "number"], ["interpolate", ["linear"], ["get", f], …stops], transparent]`,
  the stops being the Colormap's own (or its named ramp's, evenly) over
  min/max. For an "auto" min/max the server computes the field's range over
  the features the GeoJSON carries and sends it as `vector.field = {name,
  numeric, min, max}` in `GET /api/map/{id}`; equal min and max give the top
  colour. `#RRGGBBAA` colours go to MapLibre as `rgba(…)` (`cssColour` in
  `palettes.ts`).
- **Legend**: continuous → a gradient bar with min/max (custom stops
  included); classes → one row per class with its label (the value when the
  label is empty), and the Colormap's `other` colour; RGB → the three bands;
  a vector with a colour → a swatch and the layer name.
- **Overviews**: cached COGs carry them. A raster that is still a reference
  to a source file larger than 1024 px without overviews gets a VRT with
  external overviews (`<port>.view.vrt` + `.ovr`) inside its cache entry the
  first time it is shown; the user's file is never touched. The window says
  it is reading the layers meanwhile (about 20 s for a 64-band city raster).
- **Many bands**: GDAL reprojects every band of the file it reads, so a
  raster with more than 3 bands is drawn through a small VRT of just the
  shown bands (`<file>.bands-<b>.vrt` in the cache entry), which keeps the
  overviews. Changing bands resets min/max to the 2–98 % stretch of the new
  bands.
- **Open files**: the server keeps the rasters it reads tiles from open for
  20 s after the last tile (GDAL caches decoded blocks per open file), and
  closes them all when a run starts, the cache is cleared or the server
  stops, so on Windows a run can replace or evict them.
- **Vectors**: GeoJSON in EPSG:4326, at most 50 000 features (the window
  says when a layer is cut). A raster or vector without a CRS is an error
  on its layer.
- **Inspect**: a click returns every band of every raster layer at that
  point: the pixel the point falls in, as Extract Values reads it. Vector
  attributes come from the GeoJSON the window already has.
- **Styles** (basemap `auto` | `light` | `dark` | `none`, per-layer
  `colormap` (a named ramp, `categorical` or a Colormap JSON object),
  `bands`, `min`, `max`, `opacity`, `visible`, and `color` for vectors) are
  saved in the workflow under the node's `map` key. Each change is one undo
  step and never makes anything out of date.
- **Basemap**: `auto` is the default (also for a map saved without a
  `basemap` key) and shows `light` or `dark` after the current theme,
  switching live when the theme changes; a saved `light` or `dark` stays as
  it is. `light` and `dark` are both OpenStreetMap's own raster tiles
  (`tile.openstreetmap.org`, no API key, attribution shown), recoloured with
  MapLibre raster paint properties (`BASEMAP_PAINT` in
  `components/map/layers.ts`): `light` is greyed (`raster-saturation` -0.85,
  `raster-brightness-min` 0.25, `raster-contrast` -0.15) so the layers stand
  out; `dark` inverts the brightness (`raster-brightness-min` 1,
  `raster-brightness-max` 0), turns the hues back (`raster-hue-rotate` 180)
  and lowers the saturation (-0.7). No CSS filter is used, because it would
  also recolour the data layers drawn on the same canvas. Both need the
  internet. `none` works offline, never contacts the tile server, and shows
  the `map-bg` colour of the theme.
- **Colours and the theme**: layers are never recoloured by the theme (a
  colormap or class palette means the same colours in both themes, and a
  vector's default colour is `PALETTE[3]`, `#d62728`, in both). The map
  background for basemap `none`, the click marker, the point outline and the
  MapLibre controls (zoom buttons, scale bar, attribution) are UI and follow
  the theme: their colours are `--gk-map-…` tokens, read with `themeColor()`
  for MapLibre paint properties and the marker, and applied to the controls
  by `styles.css`.

### Theme

GeoKnit has a light and a dark theme. The theme belongs to the user, not the
workflow: opening a colleague's `.geoknit` file never changes it.

- **Setting** `theme`: `system` (default) | `light` | `dark`. `system`
  follows the browser's `prefers-color-scheme`, live when the OS switches. It
  is stored in `settings.json` next to `trusted.json` (section 12) and
  changed with `PATCH /api/settings` (section 9).
- **Top bar**: one button (Lucide `sun-moon`) cycles System → Light → Dark;
  its tooltip names the current choice.
- **No flash before the first paint**: the server answers `/` and
  `/index.html` itself (ahead of the static files) and writes the saved
  choice on the page as `<html data-theme-setting="…">`. A small inline
  script in `frontend/index.html` turns it into `data-theme="light|dark"`
  before any CSS applies, resolving `system` with
  `matchMedia("(prefers-color-scheme: dark)")`. Under `npm run dev` the
  attribute is missing: the script falls back to `system` and the app applies
  the saved choice once `GET /api/settings` answers.
- **Tokens**: every UI colour is a CSS custom property `--gk-…` in
  `frontend/src/theme.css`, with one block per theme
  (`:root[data-theme="light"]`, `:root[data-theme="dark"]`; the light values
  also apply without the attribute). No other `.css`, `.ts`, `.tsx` or `.svg`
  file under `frontend/src` holds a colour literal (hex, a colour function,
  a named colour), except test files, the vendored icon SVGs and
  `frontend/src/palettes.ts`, the one home of data colours (class palette,
  vector colour choices), which mean the same in both themes. A vitest test
  (`colourLiterals.test.ts`) fails on any other literal. TypeScript uses
  `var(--gk-…)` where CSS accepts it; MapLibre paint properties get a value
  from `themeColor(token)` (`frontend/src/theme.ts`, read with
  `getComputedStyle`), read again when the theme changes (`useTheme()`).
- **Token groups**: surfaces (`app-bg`, `panel-bg`, `canvas-bg`,
  `canvas-grid`, `node-bg`, `node-border`, `topbar-bg`, `field-bg`,
  `map-bg`, …); text (`ink`, `muted`, `on-strip`, `on-type`, …); states
  (`out-of-date`, `error`, `selected`, `running`); Panel note
  (`panel-note-bg`, `panel-note-ink`, `panel-note-border`); one per data type
  (`type-number`, …, section 3) and the category strip of a category that is
  no tab (`cat-other`); wires (`wire-width`, `wire-faded-opacity`); Map
  Viewer UI (`map-marker`, `map-point-outline`, `map-ctrl-…`, `map-scale-…`,
  `map-attrib-…`).
- **Palettes** (surfaces, text and states; the type colours are in
  section 3):

  | Token | Light | Dark |
  |-------|-------|------|
  | app-bg / panel-bg | `#FFFFFF` / `#F8FAFC` | `#0B1220` / `#111827` |
  | canvas-bg | `#E5E8EC` | `#111827` |
  | canvas-grid | `#D4D8DE` | `#1F2937` |
  | node-bg | `#EEF0F3` | `#1E293B` |
  | node-border | `#64748B` | `#475569` |
  | ink / muted | `#0F172A` / `#64748B` | `#E5E7EB` / `#94A3B8` |
  | panel-note-bg / ink | `#FEF6C7` / `#0F172A` | `#3B3416` / `#FDE68A` |
  | out-of-date / error / selected | `#D97706` / `#DC2626` / `#16A34A` | `#F59E0B` / `#F87171` / `#4ADE80` |
  | map-bg | `#F1F3F4` | `#1F2937` |

- **Contrast** (vitest, WCAG contrast ratio): every type colour against
  `canvas-bg` and `node-bg` of its theme ≥ 3:1; `ink` ≥ 4.5:1 and `muted`
  ≥ 3:1 against `panel-bg`, `node-bg` and `panel-note-bg`; `on-strip`
  (white) against every category strip colour ≥ 4.5:1. Both theme blocks
  must define the same tokens.
- **Parts that are not plain CSS**: Monaco (Code tab) uses `vs` in light and
  `vs-dark` in dark, switched live (`monaco.editor.setTheme`); the Map Viewer
  basemap and map UI colours are described under "Map Viewer". Icons use
  `currentColor` and follow the text colour. Native form controls
  (scrollbars, checkboxes, range sliders, select menus) follow the theme
  through `color-scheme` in each theme block; text fields and selects take
  their background from `field-bg`.
- **Fills with text on them**: white stays on the category strips, primary
  buttons and toasts. Where a fill is a light colour in dark (a type colour
  behind a badge, the slider value, the banner buttons) the text has its own
  token (`on-type`, `slider-ink`, `banner-button-ink`): dark ink in the dark
  theme, white in light. The Panel keeps its sticky-note look in dark with a
  muted yellow.
- Not themed: exported scripts and written files (they carry no UI colours).

### Interactions and editing

Interactions: drag port to port to wire; drag from a port into empty space
opens search filtered to compatible types; Delete; Ctrl+Z / Ctrl+Y;
Ctrl+C / Ctrl+V; Ctrl+G group; Ctrl+S save; wheel zoom; middle-drag or
space-drag pan; Fit. Hovering a port or wire shows its `describe()` summary
after a run; a list port's heading is `values: list of Number`, and the
tooltip shows the summary's first line and its first 5 items, then
`… N more`.

Editing details:

- **Undo / redo** (Ctrl+Z, Ctrl+Y or Ctrl+Shift+Z, toolbar arrows): every
  request that changes the workflow is one step, kept by the server (200
  steps), so edits made through the API undo the same way. Deleting or moving
  several things, a paste and a restored autosave are one step each. Undo
  changes only what differs, so only those nodes and their downstream nodes
  go out of date; moves never do. The canvas view (Show as, zoom) is not
  undone. Opening a workflow clears the history; saving does not.
- **Copy / paste**: Ctrl+C copies the selected nodes and the wires among them;
  Ctrl+V pastes them with new ids, their top-left corner at the pointer (or
  offset when the pointer is off the canvas), and selects them.
- **Groups**: Ctrl+G puts the selected nodes in a box titled "Group".
  Clicking the title selects its nodes (to drag them together),
  double-clicking renames it, right-clicking offers Ungroup. A group whose
  last node is deleted is removed.
- **Save / open**: the file name in the top bar shows "saved", "unsaved
  changes" or "not saved" (new workflow) and opens a menu: Save (Ctrl+S),
  Save as…, and the `.geoknit` files of the project folder to open.
  Double-clicking a `.geoknit` file in the folder tree also opens it.
  Opening asks before discarding unsaved changes. Ctrl+S on a new workflow
  asks for a name.
- **Autosave**: after every edit the server writes the unsaved workflow to
  `~/.geoknit/autosave/<name>-<hash>.geoknit` (next to `trusted.json`, never
  in the project folder, so a shared folder cannot plant one), and removes it
  when the workflow is saved or back to its saved state. When a workflow is
  opened (or the server starts) and its autosave differs, a banner offers
  Restore (one undo step) or Discard; the first edit replaces the autosave.

---

## 9. Server API

Every UI change goes through this API, so an AI agent can later do anything
the user can. FastAPI publishes the OpenAPI schema at `/docs`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/components` | the library for the ribbon: `{components, tabs}` (below) |
| GET | `/api/components/{ref}/icon` | a component's `.svg` icon (section 4) |
| GET | `/api/colormaps` | the named ramps: `{name: ["#RRGGBB", …11]}`, in `NAMED_RAMPS` order |
| GET | `/api/graph` | current workflow |
| POST | `/api/nodes` | add a node `{component, position}` |
| PATCH | `/api/nodes/{id}` | change settings, source, ports, position, display, value, integer, options, Slider limits, Panel size, Map Layer `style`, Map Viewer `map` |
| POST | `/api/nodes/{id}/save_component` | "Save as component…" `{overwrite}`; `409` if it exists (section 4) |
| POST | `/api/nodes/{id}/vscode` | Open in VS Code: write a temp file, start `code`, watch it (section 4) |
| PATCH | `/api/view` | canvas view: `display` (text \| icon), `zoom`, `offset` |
| GET | `/api/status` | Python version, worker `idle` \| `running`, worker pid |
| DELETE | `/api/nodes/{id}` | remove |
| POST | `/api/wires` / DELETE `/api/wires` | connect / disconnect (type and cycle checks) |
| POST | `/api/delete` | remove `{nodes, wires}` as one undo step |
| PATCH | `/api/positions` | move `{positions: {id: [x, y]}}` as one undo step |
| POST | `/api/paste` | add copies of `{nodes, wires, offset}` (workflow format) under new ids |
| POST | `/api/undo`, `/api/redo` | step through the edit history (section 8) |
| POST | `/api/groups` / PATCH, DELETE `/api/groups/{index}` | add, rename / change, ungroup |
| POST | `/api/run` | `{mode: all | to_node | test, node_id?}` |
| POST | `/api/stop` | stop the worker |
| POST | `/api/cache/clear` | "Clear cache" (section 6) |
| GET | `/api/nodes/{id}/output` | Output log, per-port summaries, views and port keys |
| GET | `/api/table/{key}?offset&limit` | a page of rows of a cached Table or Vector (Panel paging) |
| GET | `/api/files` | project folder tree |
| POST | `/api/workflow/save`, `/api/workflow/open` | file operations |
| POST | `/api/workflow/trust` | trust the open workflow (section 11) |
| POST | `/api/workflow/recover` | `{restore}`: restore or discard the autosave (section 8) |
| GET | `/api/settings` | the user's settings: `{theme}` (section 8, "Theme") |
| PATCH | `/api/settings` | change them: `{theme: system \| light \| dark}` |
| POST | `/api/export/py` | Export .py `{path?, overwrite?}`: the script, written into the project if `path` (section 10) |
| GET | `/api/map/{id}` | Map Viewer layers: status, bounds, bands, statistics, style, `from_layer`, `locked` (section 8) |
| GET | `/api/layer/{id}` | a Map Layer for its window: its layer, state, style, a vector's columns, a raster's band names |
| GET | `/api/map/{id}/inspect?lon&lat` | band values of every raster layer at a point |
| GET | `/api/raster/{key}/stats?bands` | 2–98 % stretch of bands, classes of a small-integer band |
| GET | `/tiles/{key}/{z}/{x}/{y}.png?bands&colormap&cmap&min&max` | raster tiles for Map Viewer (rio-tiler); `cmap` a Colormap as compact JSON, replacing `colormap` |
| GET | `/api/vector/{key}.geojson` | vector layer in EPSG:4326, max 50 000 features; total in `X-GeoKnit-Features` |
| WS | `/ws` | events: node state changes, log lines, run finished |
| GET | `/`, `/index.html` | the app, with the saved theme on `<html data-theme-setting>` |

The server binds to `127.0.0.1` only.

Details:

- One server holds one project folder and one open workflow. Relative paths
  resolve against the workflow's folder (the project folder while it is
  unsaved), as in `geoknit run`. Save and open take a `.geoknit` path
  relative to the project folder; paths outside it are refused.
- **Ports** in the API are `{name, type, types, access}` (in
  `GET /api/graph` also `file`): `types` lists every accepted type (one
  element for an ordinary port) and `type` is the first. Outputs also carry
  `like` (the input's name or `null`). In
  `GET /api/graph`, outputs also carry `resolved_type` (the output's own type
  for an ordinary output, the resolved type of a `like:` output, `null` while
  it is unresolved), `resolved_types` (every type it can carry,
  `Graph.output_types`: one element once resolved, `["Any"]` for an unwired
  Panel, otherwise the possible types, which can be narrower than the
  declared `types`: a Panel fed by an unwired Split Points has `types:
  ["Any"]` but `resolved_types: ["Table", "Vector"]`; the frontend checks
  drags against these) and `resolved_access` (`"list"` or `"item"`, from
  `output_is_list`, so a Panel passing a list through is drawn as a list).
- **`GET /api/components`** answers `{components: [...], tabs: [{name,
  colour, groups: [name, …]}]}`. Each component entry has `ref`, `version`,
  `origin`, `name`, `category`, `group`, `icon`, `description`, `inputs`,
  `outputs`, `requires`, `settings` (with their form hints) and `editable_ports`
  (`{inputs, outputs, types, input_types}`, or `null` without `ports:`;
  `input_types` adds `Any` when the default `types` apply). The Params nodes
  are in the list too (`origin: "param"`, `version: ""`, `settings: []`,
  `editable_ports: null`, `description: ""`, their `PARAM_ICONS` icon and the
  same port views as header components; the Panel's output has
  `like: data`, the Value List shows the default `Number` output). Entries
  are sorted by tab, then group, then layout position (built-ins), then name
  (case-insensitive) and reference; the frontend keeps this order.
- **`GET /api/components/{ref}/icon`** serves the `.svg` named by the
  component's `icon:` as `image/svg+xml`, bytes unchanged
  (`Registry.icon_path`), with `X-Content-Type-Options: nosniff` and
  `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline';
  sandbox`, so a pack's SVG opened on the app's origin runs no script and
  loads nothing (the canvas draws it as a CSS mask). An absolute path, a path that leaves the folder
  the component was loaded from, a missing file, a `<set>:<name>` icon and an
  unknown reference answer `404`.
- `GET /api/graph` returns `{workflow, nodes, out_of_date, path, trusted,
  running, dirty, can_undo, can_redo, recovery}`: `workflow` is the
  `.geoknit` document, `nodes` maps each id to its title, state, ports, and
  (components) settings with their form hints, source, `modified`,
  `parse_error` and `editable_ports`. Params nodes carry their value fields
  (also in `POST /api/nodes` and `PATCH` replies): Text `{value}`; Number
  `{value, integer}`; Number Slider `{min, max, step, value, integer}`;
  Boolean Toggle `{value: bool}`; Value List `{options: [{label, value}],
  value}`, with its current type in `outputs[0].type` / `resolved_type`;
  Color Swatch `{value: "#RRGGBB[AA]"}`; Colormap `{value: <Colormap JSON>}`.
  A Map Layer carries `style` (the saved fields) and `layer: {key, value,
  issues, wired}` or `null` before the server built it: `key` its `layer`
  port key, `value` the `MapLayer` JSON (`source, kind, name, colormap,
  color, opacity, bands, field`), `issues` input → why its wired or saved
  value is not used (`data`, `colormap`, `color`, `opacity`, `bands`,
  `name`), `wired` each wired input whose value is used → `params` |
  `component`.
- `PATCH /api/nodes/{id}` changes only the fields sent: `settings`
  (`{name: value}`), `source`, `ports`, `value`, `integer`, `options`,
  `min`/`max`/`step`, `position`, `display`, for a Map Viewer `map`
  (`{basemap?, styles?: {layer id: style | null}}`, merged into the saved
  settings; `null` resets a layer to its defaults), and for a Map Layer
  `style` (merged like `map`: a `null` field resets it, `style: null` resets
  every field; a ramp name is accepted for `colormap` and saved as
  `{"kind": "continuous", "name": …}`; an unknown field or bad value answers
  `400`; refused during a run, `409`).
  - `ports` is `{inputs?, outputs?}`, each a list of `{name, type, types?,
    like?, access?, file?, was?}` where `was` is the old name of a renamed
    port. A side left out stays as it is; a side sent back unchanged keeps its
    union types and `like:` outputs. A renamed input is renamed in the
    `like:` of the outputs that follow it (section 4). Edits are checked against the header's
    `ports:` (section 4): `the inputs of Reclassify cannot be edited`,
    `Raster Calculator inputs are Raster or Number` (`400`).
  - `value`: of a Color Swatch any `Color.parse` form (`#0b7a7c`,
    `11,122,124`); of a Colormap any valid Colormap JSON. `options` and
    `value` may be sent together for a Value List. Errors (`400`): `a Number
    value must be a number` (a `bool` is not one), `a Boolean Toggle value
    must be true or false`, the Color parse message, `not a colormap: …`,
    `'x' is not one of the Value List's options`; `integer` on a node other
    than Number or Slider: `Text has no integer mode`; `options` on a node
    other than a Value List: `Text has no options`.
- `GET /api/nodes/{id}/output` answers `{state, log, error, outputs: {port:
  summary}, views: {port: view}, keys: {port: port key or null}, disk_cache:
  bool}`. `views` are the Panel views (section 8); `keys` is what
  `/api/table/{key}` takes (a Panel's `data` key is the key of the output
  feeding it); `disk_cache` is false when results are not written to disk.
- **`GET /api/table/{key}?offset=0&limit=200`** (tag `run`) →
  `{columns, rows, index, total_rows, offset, geometry}`: `columns` the
  column names (geometry columns included, in frame order), `rows` one array
  per row in column order, `index` the index labels of those rows (a
  RangeIndex continues from `offset`), `total_rows` the table's length,
  `offset` as asked, `geometry` the names of the geometry columns (`[]` for
  a Table). `{key}` is a port key as in the map routes; a list element is
  addressed as `<key>[i]`. `offset` past the end gives `rows: []`. `limit`
  0–1000 and `offset` ≥ 0, otherwise `400`. `404` for: a key that is not a
  port key, a key not in the disk cache (`not in the cache; run first`), a
  list element out of range (`list element 5 is out of range (3 elements)`),
  an element of a list stored as one JSON file (`"values" is a list of
  Number, not a table`) or of a port that is no list (`"n" is not a list`),
  a port that is not a Table or Vector (also a whole list), and any key when
  the disk cache is off (`the disk cache is off: …`).
  - Pages read only the Parquet row groups they overlap
    (`pyarrow.parquet.ParquetFile.read_row_groups`; the file is opened and
    closed per request so Windows can delete it); GeoParquet WKB geometry is
    decoded with shapely only to get its type name. A pickle fallback entry
    is loaded once and memoised (the last 4, by path). This lives in
    `geoknit/server/tables.py`.
  - JSON-safe cells and index labels: `None`, NaN, `NaT`, `pd.NA` → `null`;
    booleans (also `numpy.bool_`) and integers (also numpy ints) as they are;
    finite floats as numbers, infinities as `"inf"` / `"-inf"`; dates, times
    and timestamps → ISO 8601 text (`2026-01-02T03:04:05`, with the offset
    when time-zoned); `bytes` → `"<N bytes>"`; a shapely geometry → its type
    name (`Point`, `LineString`, …; a missing geometry `null`); `Decimal` →
    number; anything else → its `str()`. Text cells longer than 1000
    characters are cut and end in `…`.
- `GET /api/map/{id}` answers `{basemap, basemaps, layers, colormaps,
  max_features}`; `basemap` is the saved one or `auto`, and `basemaps` lists
  `auto`, `light`, `dark`, `none`. A Map Viewer `map` patch with another
  basemap answers `400` (`basemap is one of auto, light, dark, none`). Each
  layer has `from_layer` (the Map Layer's node id, or `null` for a raw wire)
  and, for a Map Layer's layer, `locked` (a sorted list of the style fields
  it sets) next to the effective `style`; a vector coloured by a continuous
  Colormap with auto min/max has `vector.field = {name, numeric, min, max}`.
- `GET /api/layer/{id}` (tag `map`) answers the Map Layer's build as in
  `GET /api/graph` plus `node`, `state`, `style`, `columns` (a vector's
  columns, from `describe_vector`, for the `field` dropdown) and `bands` (a
  raster's band names); both `null` until the data is `done` with the disk
  cache on. Another node answers `400`.
- `GET /api/nodes/{id}/output` of a done Map Layer: `outputs.layer` is the
  `describe()` text, `views.layer` a `summary` view, `keys.layer` the port
  key.
- `/api/settings` belongs to the user, not the workflow: a change is not part
  of undo, never makes anything out of date, and is allowed during a run and
  on a read-only workflow. A theme other than `system`, `light`, `dark`
  answers `422` (like any invalid request body) and `null` answers `400`;
  nothing is written.
- `{key}` in the map routes is a port key `<node key>.<port>` from
  `GET /api/map/{id}`, or `<node key>.<port>[i]` for an element of a list
  (section 8); a key that is not in the disk cache answers `404`. The tile
  route stays stateless (a port key plus query parameters): the server never
  resolves node ids there.
- `POST /api/run` starts the run in the background and answers `202
  {plan}` at once; progress arrives on `/ws`. While a run is active, a second
  run and every edit that changes results answer `409` ("stop the run
  first"); position, display and group changes are still allowed, undo and
  redo are not.
- Errors answer `{"detail": message}`: `400` for refused edits (the
  messages of sections 3–5), `403` for a read-only workflow (section 11),
  `404` for an unknown node.
- `/ws` sends JSON events: `states {states, out_of_date}` on connect, after
  every edit and after each run; `started`, `log {line}`, `done {outputs,
  views, cached}` (`outputs: {port: summary}`, `views: {port: view}`),
  `error {traceback}`, `skipped {traceback}` per node, each with `node`;
  `run_finished {report: {ran, cached, failed, skipped, ok}}`;
  `workflow_opened {path}`; `worker {python, worker, pid}` when a run starts
  and ends; `node_changed {node}` when a file open in VS Code was applied to
  its node; `map_changed {node, viewers}` after any edit, undo/redo or Run
  that changes a Map Layer's port key (`node` the Map Layer, `viewers` the
  Map Viewers downstream of it), sent before that edit's `states` event.
- `POST /api/export/py` answers `{script, path, warnings}`. Without `path`
  it only returns the script. With `path` (a `.py` file inside the project)
  it also writes it; an existing file answers `409` unless `overwrite` is
  true, and a script not next to the workflow gets a warning (its relative
  paths would not find the data). Export runs nothing, so it is allowed during
  a run and on a read-only workflow. A workflow that cannot be exported
  answers `400` naming the node (section 10).

---

## 10. Export to Python

`Export .py` (top bar, `POST /api/export/py`, `geoknit export`) writes one
script that runs without GeoKnit installed (except `geoknit.helpers`, which is
vendored into the script if used):

- Params values become constants at the top, so the script stays easy to
  tweak: `N01_PATH = 'data/imd.tif'`, named after the node id and the first
  input it feeds, with a comment saying where it comes from and goes:
  `# n3 Number (integer)`, `# n4 Boolean Toggle → n5 Flip.flag`,
  `# n6 Value List (One=1, Two=2, Three=3)`, `# n7 Color Swatch`,
  `# n8 Colormap`, and for a Slider its range
  (`(0..10, step 1, integer)` in integer mode). Examples:
  `N03_INVERT = True`, `N04_COLOR = Color("#0B7A7C")`,
  `N05_COLORMAP = Colormap.named("viridis")` (the full `Colormap(...)`
  constructor for a custom one). A Text Value List's constant is the option's
  text.
- Each component becomes a function `def n07_reclassify(raster, breaks): ...`
  containing its settings block and code and returning its outputs (one
  value, or a tuple in header order). Node ids `nN` are padded to the widest
  id, at least two digits. The parameters are the wired inputs; an unwired
  input with a same-named setting keeps that setting, and the setting of a
  wired input is commented out (`# n_trees = 300  # ← wired input`), which is
  the same as GeoKnit's "settings, then wired inputs override". Indenting the
  code into the function never changes a multi-line string.
- In a function whose code reads the name `INPUTS`, `INPUTS = {"a": a,
  "b": b}` is the last line of the settings block (after the settings, so
  unwired inputs already hold their setting values); other functions are
  unchanged.
- `main()` changes to the script's folder, calls the functions in topological
  order with keyword arguments, prints each Panel as `geoknit run` does
  (`--- Panel <id> ---` and its `describe()` summary, `(empty)` when
  unconnected), and returns `{panel id: value}`. Number → Text and
  Boolean → Text wires become `str(...)`; a component with an `out: Text`
  output collects what it prints.
- Map Layer and Map Viewer are comments in `main()`, in topological order:
  `# n24 Map Layer "IMD classes": n04.classes, colormap n23` (the layer's
  name as GeoKnit builds it, the data's output, then each wired style input
  and the node it comes from, nodes named as the script's functions name
  them; `no data` without a data wire) and
  `# n25 Map Viewer: n24.layer, n10.test` (its layers in wire order, or
  `no layers`). A Panel on a Map Layer prints `(Map Layer, not exported)`.
  Colormap and Color constants are exported, so a component that takes a
  Colormap still runs.
- Lists: a list output (also a `like:` output that carries a list) is
  returned as `list(x)` (a tuple becomes a list as in GeoKnit); a Boolean
  output as `bool(x)`, a list of them as `[bool(_v) for _v in x]`, so a
  `numpy.bool_` (`result = a > b`) becomes `bool` as GeoKnit's output check
  does. Only functions with Boolean outputs change, and no helper is
  vendored for it; a `list` input receives `[*a, b, *c]` built in wire order, a list
  wire spread with `*` and a single-value wire added as one element; a list
  wire that needs the Number/Boolean → Text conversion is spread as
  `*[str(_v) for _v in a]`.
- `geoknit.helpers` and `geoknit.core.types` (which the helpers, `describe()`,
  `ModelBundle`, `Color` and `Colormap` need) are copied in as plain code when
  a component imports from them, a Panel needs `describe()`, an unresolved
  `Any` → Text wire (from an unwired Panel) needs `_as_text`, or a Color or
  Colormap constant is used. The constants call the vendored classes, so in
  that last case the vendored section comes before the values section instead
  of after it. The component's own `from geoknit.helpers import …` lines
  become comments (`as` names become assignments). Any other `geoknit` import
  stays and is reported as a warning: that script still needs GeoKnit.
- Relative paths in the values are relative to the workflow's folder, so the
  script belongs next to the `.geoknit` file; that is the default export path
  (`<workflow>.py`, or `workflow.py` for an unsaved workflow).
- Refused, naming the node: a component whose header or settings do not parse,
  whose code has a syntax error, or with a required input that is neither
  wired nor set.

The exported script must give the same results as GeoKnit for the same
inputs and seeds; CI checks this on the synthetic example (the same Panel
text with `import geoknit` blocked, and the same metrics table value for
value).

---

## 11. Trust

A workflow contains code. When opening a `.geoknit` file that was not
created or saved on this machine (its content hash is not in
`~/.geoknit/trusted.json`), GeoKnit opens it read-only and asks
"This workflow contains Python code. Trust and allow running?".

- The content hash is the sha256 of the file's bytes. Every file GeoKnit
  saves is added; answering yes (`POST /api/workflow/trust`) adds the opened
  file. A file changed elsewhere afterwards is untrusted again.
- Read-only: the workflow can be viewed, but edits and runs answer `403`
  with the question above. A new, unsaved workflow is trusted.
- `geoknit run file.geoknit` does not check trust: naming the file on the
  command line is the decision to run it.

---

## 12. Packaging and platform

- Python ≥ 3.11. Install with `pip install geoknit`. Windows is a
  first-class platform.
- `geoknit [folder]` starts the server on a free port on `127.0.0.1`
  (folder defaults to the current one) and opens the browser once it is
  up. A `.geoknit` file instead of a folder opens that workflow, with its
  folder as the project. Options: `--port N`, `--no-browser`. A missing
  folder exits with code 2. `geoknit run file.geoknit` runs headless and prints each Panel's
  contents to stdout under `--- Panel <id> ---`. Component output and errors
  go to stderr. The exit code is 0 when every node succeeded, 1 otherwise,
  and 130 on Ctrl+C. Options: `-q/--quiet` (hide component output),
  `--clear-cache`, `--no-cache`, `--cache-limit GB`.
- `geoknit export file.geoknit [-o out.py]` writes the workflow as a Python
  script (section 10), by default next to the workflow with a `.py` suffix.
  Warnings and errors go to stderr; the exit code is 0 on success, 1
  otherwise.
- The wheel contains the built frontend in `geoknit/server/static/`; users
  never need Node. The sdist carries the built frontend too, so a wheel built
  from it keeps the canvas. Building a regular wheel without the frontend
  fails (`hatch_build.py`; `GEOKNIT_ALLOW_NO_FRONTEND=1` overrides it);
  editable installs are not checked. Releases are tags `vX.Y.Z` published by
  `.github/workflows/release.yml` (`docs/releasing.md`).
- Icon licences: Font-GIS icons are CC BY 4.0 (attribution required), Lucide
  is ISC (with the MIT licence of its Feather-derived icons), Tabler is MIT.
  Each vendor folder holds its licence files (`gis/`: Font-GIS's
  `LICENSE.md` and `LICENSE-CC-BY.md`; `tabler/`: `LICENSE`). A
  `THIRD_PARTY_NOTICES.md` at the repo root credits them; the sdist includes
  it (`only-include`) and the wheel carries it as
  `geoknit/THIRD_PARTY_NOTICES.md` (`[tool.hatch.build.targets.wheel.force-include]`),
  which `scripts/smoke_test.py` checks.
- Geo stack from wheels only: rasterio, pyogrio, shapely, pyproj, geopandas,
  rioxarray. Never import `osgeo`. The worker ignores a system
  `PROJ_LIB` / `PROJ_DATA` / `GDAL_DATA` (section 6, "Worker protocol").
- The user's own files are `trusted.json` (section 11), `autosave/`
  (section 8) and `settings.json` (`{"theme": "system"}`, section 8
  "Theme"), together in `~/.geoknit/`, or in the folder of
  `GEOKNIT_TRUST_FILE` / `create_app(trust_file=…)` (the tests use this). A
  missing or unreadable `settings.json` means the defaults; keys GeoKnit does
  not know are kept and written back.
- Screenshots: `docs/img/milan/` is made from the app by `npm run
  screenshots` (`frontend/docs-shots/milan.spec.ts`, on the real Milan data),
  in the light theme plus `01-opened-dark.png` and `06-map-viewer-dark.png`;
  the README shows the main canvas in both themes side by side.
- A component can declare `requires`; if a package is missing, GeoKnit offers
  to `pip install` it into its own environment.
- License: Apache-2.0.

---

## 13. Later versions

Earth Engine pack (GEE Image, GEE Extract, GEE Export, sign-in), working
assistant, list auto-iteration, data trees, environment picker, desktop
installer, translations, more models (gradient boosting, XGBoost/LightGBM),
deep learning pack.
