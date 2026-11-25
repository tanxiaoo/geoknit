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
- Six data types: Number, Text, Raster, Vector, Table, Model.
- One component file format shared by built-ins, user Python components and
  community packs (section 4).
- Built-in components for the Milan IMD workflow and its close variants
  (section 7).
- Component window: Settings and Code tabs that edit the same component,
  Output log always visible.
- Panel component (inspect any output) and Map Viewer component.
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
  Stop kill a stuck run without killing the app. The one exception is the
  Map Viewer (section 8): `server/tiles.py` imports rasterio, rio-tiler and
  geopandas the first time a map is opened, to read cached results.
- `geoknit/core` (graph, types, component format, solver, serialization,
  export) has no dependency on the server or frontend and can run headless.
  `geoknit run file.geoknit` uses it with a worker process but no server, so
  it shares the disk cache and Stop behaviour with the app.

---

## 3. Data types

| Type   | Python object | Port colour | Panel summary (`describe()`) |
|--------|---------------|-------------|-------------------------------|
| Number | `int` or `float` | `#64748B` | the value |
| Text   | `str` | `#A16207` | the value (multi-line allowed) |
| Raster | `xarray.DataArray` opened with rioxarray, dims `(band, y, x)`, lazy (dask-backed) | `#0B7A7C` | bands, band names, width × height, resolution, dtype, CRS, nodata |
| Vector | `geopandas.GeoDataFrame` | `#C2410C` | feature count, geometry type, CRS, columns |
| Table  | `pandas.DataFrame` (not geographic) | `#7C3AED` | rows, columns, first 5 rows |
| Model  | `geoknit.types.ModelBundle` | `#BE185D` | estimator type, task, target, feature names, parameters |

`ModelBundle` is a dataclass: `estimator`, `task` (`"regression"` or
`"classification"`), `target: str`, `feature_names: list[str]`,
`info: dict`.

`Any` exists only as the input type of Panel and Map Viewer.

Connection rules:

- An output connects to an input of the same type, or to an `Any` input.
- One exception for convenience: Number → Text (converted with `str`).
- An `Any` output (Panel's pass-through) connects to any input; the value's
  type is checked when the receiving node runs (`input "x": expected
  Number, got Text`).
- Everything else is refused when the user drops the wire, with a tooltip
  such as "Raster can't connect to Number".
- An input has `access: item` (default, one wire) or `access: list`
  (several wires, collected into a Python list in wire order). Only Map
  Viewer uses `list` in v0.1. A second wire into an `item` input is refused
  ("input "x" of Reclassify is already connected"); remove the old wire first.
- Cycles are refused when the wire is created.
- Changing a component's code removes wires whose port disappeared or whose
  type no longer matches.

`describe()` must never read pixel data; it uses metadata only, so hovering
or a Panel on a 1 GB raster is instant.

---

## 4. Component format

One `.py` file is one component. The same format is used for built-ins,
the Python component on the canvas, components a user saves, and
community packs. This is the central idea of GeoKnit.

```python
# geoknit: component
# name: Reclassify
# category: Raster
# icon: reclassify
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
- Keys: `name`, `category` (ribbon tab), `icon` (built-in icon name or a
  relative `.svg` path), `description`, `inputs`, `outputs`,
  `requires` (pip package names), optional `access` per input:
  `layers: {type: Any, access: list}`.
- Optional `file: write` on a Text input that names a file the component
  writes, e.g. `path: {type: Text, file: write}`. Such paths are not
  fingerprinted for the cache (section 6), so writing the file does not make
  the node out of date again.

### Settings block

- Between `# --- settings ---` and `# --- code ---`.
- Only top-level assignments whose value is a literal: int, float, str,
  bool, None, or a list/tuple of those. Anything else is a parse error,
  shown in the component's Output.
- An optional trailing comment shapes the Settings form:
  `# options: a | b | c` → dropdown, `# range: 0..1000` → number field with
  limits, `# multiline` → text area. No comment → text field. Options that
  read as numbers, `True`/`False` or `None` are those values; others are text.
- Each name may be set only once.
- A setting whose name equals an input name is that input's default value.
  An input with no same-named setting is required.

### Code block

Plain Python after `# --- code ---`. Inputs are available as variables;
outputs are read back by name when the code ends.

### Running one component

1. Create a fresh namespace.
2. Execute the settings block.
3. For each wired input, assign its value, overriding the setting. A wired
   value of the wrong type → error naming expected and actual type.
4. A required input that is neither wired nor set → error
   `input "raster" is not connected`.
5. Execute the code block with the project folder as working directory (so
   relative paths in Text components work), capturing `print`, stderr,
   warnings and logging (INFO and above) into the component's Output, one
   entry per line.
6. Read each declared output from the namespace. Missing → error. Wrong
   type → error naming expected and actual type.
7. Exceptions show the traceback in Output, with line numbers relative to the
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
- Ports of a Script component (the Python component, or one saved from it)
  are edited in its Settings tab: add, remove, rename, set type. This
  rewrites only the header's `inputs:` and `outputs:` lines (other header
  lines, the settings block and the code stay byte-for-byte the same). Wires
  on a renamed port follow it; wires on a removed port, or a port whose new
  type no longer fits, are removed. A new port gets a free name (`x1`, `y1`)
  and type Number.

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
files starting with `_` are ignored):

| Source | Reference |
|--------|-----------|
| built-in | `builtin/<category>/<name>` |
| `~/.geoknit/components/` | `user/<category>/<name>` |
| pack (entry point `fake = …`) | `fake/<category>/<name>`, version = the package version |

The names `builtin`, `user`, `inline` and `param` are reserved for packs. A
file that does not parse, or a pack that fails to load, is skipped with a
warning and never stops GeoKnit from starting.

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
    {"id": "n5", "component": "param/slider", "min": 50, "max": 1000, "step": 50, "value": 300, "position": [16, 480]}
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
- Params nodes: `param/text` (`value`), `param/slider` (`min`, `max`, `step`,
  `value`), `param/panel` (optional `size: [width, height]` once resized),
  `param/map` (optional `map: {basemap, styles}`, section 8).
  Component nodes always have `display`.
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

Changing a setting, the code, a wire, or a Slider/Text value marks that node
and everything downstream `out_of_date`. On Run, components that read files
also check the file's size and modification time.

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
  - `run_node {node_id, source, inputs: {port: cache_key | [cache_key, …]}, cache_key}`.
    Settings are part of `source`. A `list` input gets its keys in wire order.
  - `put_value {cache_key, value}`: a Text or Slider value (or an empty
    Panel's `None`), sent before each run so the worker can look it up.
  - `clear_cache` (answered by `cleared {complete}`), `shutdown`.
- worker → server: `ready {pid}`, `started`, `log {line}`,
  `done {outputs: {port: {cache_key, summary}}, cached}`, `error {traceback}`,
  `cleared {complete}`. `cached` is true when the result came from worker
  memory or the disk cache without running the code.
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
- Text, Slider and Panel nodes are handled by the server; only components go
  to the worker.
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
  - Text: `sha256(value + file fingerprint)`; Slider: `sha256(value)`;
  - Panel: no key; its output reuses the key of the wire feeding it;
  - Map Viewer: no key and no outputs; it is `done` once its inputs are.
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
  GeoParquet, Table → Parquet (pickle if Parquet refuses the dtypes), Model →
  joblib, Number/Text → JSON. A Raster that is still an unchanged lazy view
  of a file (straight from `rioxarray.open_rasterio`) is not copied: the
  cache writes `<port>.ref.json` (path, size, mtime, band names), and a
  changed source file makes it a miss.
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
  computed raster output with the COG it just wrote, so downstream nodes
  read the file instead of computing it again. With the disk cache off
  (`--no-cache`) each downstream node computes the lazy raster itself.
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

| Tab | Component | Inputs | Outputs | Settings / notes |
|-----|-----------|--------|---------|------------------|
| Params | Number Slider | – | Number | min, max, step, value |
| Params | Text | – | Text | value; edit inline on double-click |
| Params | Panel | data: Any | data: Any (pass-through) | shows `describe()`; yellow, resizable |
| Params | Map Viewer | layers: Any (list) | – | double-click opens the map window (section 8); no code; styles saved with the node |
| Raster | Read Raster | path: Text | raster | bands="all", masked=True; lazy, 512 px chunks with all bands |
| Raster | Write Raster | map: Raster, path: Text (`file: write`) | file: Text | COG, compress="deflate" |
| Raster | Reclassify | raster, breaks: Text | classes: Raster | no_match, dtype |
| Raster | Clip | raster, aoi: Vector | clipped: Raster | all_touched=False; AOI reprojected to the raster CRS |
| Raster | Align Raster | source, reference: Raster | raster | resampling="nearest"; reads the whole source (the one built-in that is not lazy) |
| Raster | Band Select | raster, bands: Text | selected: Raster | bands as "1,2,3" or names |
| Vector | Read Vector | path: Text | vector | layer=None |
| Vector | Write Vector | vector, path: Text (`file: write`) | file: Text | format from extension: .gpkg, .shp, .geojson, .parquet |
| Vector | Reproject | vector, crs: Text | reprojected: Vector | |
| Sampling | Stratified Sample | classes: Raster, value: Raster, aoi: Vector, n: Number, seed: Number | points: Vector | equal n per class (warn if a class has fewer pixels); points at pixel centres; value_field="value", class_field="cls"; classes and value on one grid; reads band 1 of both inside the AOI's bounding box |
| Sampling | Random Sample | raster, aoi: Vector, n, seed | points: Vector | only valid (non-nodata) pixels of band 1; an `id` column |
| Sampling | Split Points | points: Vector | train: Vector, test: Vector | test_fraction=0.3, seed=42, stratify_by=None; holds out points for validation |
| Sampling | Extract Values | points: Vector, raster: Raster | table: Table | columns from band descriptions, else b01…; keeps point attributes; drops nodata rows with a warning; sets `table.attrs["feature_columns"]` |
| Sampling | Train/Test Split | table | train: Table, test: Table | test_fraction=0.3, seed=42, stratify_by=None |
| Model | Random Forest | table, target: Text, n_trees, max_depth, min_leaf, seed | model: Model | task="regression", max_features="sqrt", features="auto" (feature_columns attr, else numeric columns except target); trains on all cores, predicts on one thread so maps are repeatable |
| Model | SVM | table, target: Text | model: Model | task, kernel="rbf", C=1.0, gamma="scale", standardize=True |
| Model | Predict Raster | model, raster | map: Raster | window=512; band names must equal `model.feature_names`, else error listing the missing ones; float32 for regression, smallest int type for classes |
| Validation | Accuracy | map: Raster, reference: Vector, field: Text | metrics: Table | one row: n, dropped, RMSE, MAE, R², bias (observed − predicted); nearest pixel; points outside, on nodata or without a value dropped and counted |
| Validation | Confusion Matrix | map, reference: Vector, field: Text | matrix: Table, metrics: Table | matrix: reference classes as rows, map classes as columns; metrics: columns metric, class, value; overall accuracy and kappa first, then producer's/user's accuracy and F1 per class |
| Script | Python | user-defined | user-defined + out: Text | ports added/removed in the component window; the template has no inputs |

Random Forest and SVM inputs that also appear as settings (n_trees, max_depth,
min_leaf, seed) can be left unwired; the setting is then used.

### Reference workflow: Milan IMD (`examples/milan_imd/`)

```
Text data/CLMS_2018_Milan_UTM32N.tif ─ Read Raster ─┬─ Reclassify ← Text breaks ─┐
                                                    └──────────── value ─────────┤
Text data/aoi_milan.gpkg ── Read Vector ─────────────────────── aoi ─────────────┤
Slider n, Slider seed ───────────────────────────────────────────────────────────┴─ Stratified Sample ─ Split Points ─┬─ train
Text data/AlphaEarth_2018_Milan_UTM32N.tif ─ Read Raster ──┬─ Extract Values ← train points                           │
                                                           │        └─ Random Forest ← Text "IMD", Slider n_trees     │
                                                           └─ Predict Raster ← model ─┬─ Write Raster ← Text outputs/imd_rf.tif
                                                                                      └─ Accuracy ← test points, Text "IMD" ─ Panel
```

Validation uses held-out sample points, not separate reference data:
Stratified Sample stores the CLMS IMD of each point in the field `IMD`;
Split Points (stratified by class, 30 % test) sends the training points to
Extract Values and the test points to Accuracy, which compares the predicted
map at each test point with its `IMD`.

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
icons), `03`–`06` (component window), `07` (Map Viewer).

- **Top bar**: GeoKnit logo, workflow file name and save state, worker
  status, Export .py, Stop, Run.
- **Ribbon**: one tab per category (Params, Raster, Vector, Sampling,
  Model, Validation, Script, plus pack categories); component buttons;
  search box. Double-clicking empty canvas opens the same search as a
  popup at the cursor.
- **Project folder (left)**: just the file tree of the project folder.
  No buttons or info box. Hides `.geoknit/`. Dragging a file onto the canvas
  creates a Text component with its relative path. Refreshes after each run
  and on window focus.
- **Canvas (centre)**: grid background. Grasshopper-style nodes: input
  names on the left, a coloured centre strip with the vertical name or the
  icon, output names on the right. Port dots and wires coloured by type.
  Out-of-date nodes and their incoming wires are faded with an orange dot.
  Errors red. Selected nodes outlined green. Groups are labelled boxes.
  The centre strip is coloured by category: Raster `#0B7A7C`, Vector
  `#C2410C`, Sampling `#7C3AED`, Model `#BE185D`, Validation `#15803D`,
  Params, Script and pack categories `#475569`. A Text node is a pill with a
  "T" badge; a Number Slider is a track with its value; a Panel is a yellow
  box with its input on the left and its pass-through output on the right.
- **Canvas toolbar**: zoom − / % / +, Fit, "Show as Text | Icon" (saved in
  the workflow's `view`), a hint, and the banner "<what changed> · N
  components out of date · Run". Right-clicking a node offers Run to here.
- **Status bar (bottom)**: data-type colour legend, state legend.
- **Assistant (right)**: collapsible placeholder marked "Next version".

Component window (double-click a node): floating and draggable, header with
category and name (and the "modified" mark); tabs **Settings** (inputs with
their wired source or an editable default, the component's settings, "show
on canvas as"; ports too for Script components) and **Code** (Monaco editor
with the full component file, Open in VS Code); **Output** always visible
below both tabs (state, log lines of the last run, the traceback of an
error); buttons Save as component…, Test and OK. Settings fields apply on
change (dropdowns) or on Enter / leaving the field; each change is one undo
step. Test runs this component only, using cached inputs (`POST /api/run`
`mode: test`). OK applies the code and closes. Monaco is bundled with the
frontend (no CDN) and loaded the first time a Code tab opens.
Number Slider opens a small window with min/max/step/value. Text is edited
inline.

Map Viewer window: MapLibre map with a light basemap, a layer list from the
wired inputs, per-layer colormap / min / max / band(s) / opacity, a legend,
and click-to-inspect pixel values of every layer.

Map Viewer details:

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
  with the disk cache off. Rasters and Vectors are shown; other types are
  listed as "cannot be shown on a map". Vectors are drawn above rasters;
  otherwise the first wire is drawn on top.
- **Rasters**: 256 px Web Mercator PNG tiles rendered by rio-tiler from
  overviews, transparent outside the raster and on nodata. Defaults:
  exactly 3 bands → RGB; an integer band with at most 32 distinct values →
  classes in a fixed palette (class `v` gets colour `v mod 20`); otherwise
  band 1 with `viridis`. Min/max default to the 2–98 % percentiles of the
  shown bands, read from an overview. Colormaps: viridis, magma, plasma,
  cividis, turbo, greys_r, terrain, rdylgn, spectral, blues.
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
- **Styles** (basemap `light` | `none`, per-layer `colormap`, `bands`, `min`,
  `max`, `opacity`, `visible`, and `color` for vectors) are saved in the
  workflow under the node's `map` key. Each change is one undo step and never
  makes anything out of date. The `light` basemap is OpenStreetMap's own
  raster tiles (`tile.openstreetmap.org`, no API key, attribution shown),
  greyed in the map so the layers stand out; it needs the internet. `none`
  works offline and never contacts the tile server.

Interactions: drag port to port to wire; drag from a port into empty space
opens search filtered to compatible types; Delete; Ctrl+Z / Ctrl+Y;
Ctrl+C / Ctrl+V; Ctrl+G group; Ctrl+S save; wheel zoom; middle-drag or
space-drag pan; Fit. Hovering a port or wire shows its `describe()` summary
after a run.

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
| GET | `/api/components` | library for the ribbon (header metadata) |
| GET | `/api/graph` | current workflow |
| POST | `/api/nodes` | add a node `{component, position}` |
| PATCH | `/api/nodes/{id}` | change settings, source, ports, position, display, value, Panel size, Map Viewer `map` |
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
| GET | `/api/nodes/{id}/output` | Output log and per-port summaries |
| GET | `/api/files` | project folder tree |
| POST | `/api/workflow/save`, `/api/workflow/open` | file operations |
| POST | `/api/workflow/trust` | trust the open workflow (section 11) |
| POST | `/api/workflow/recover` | `{restore}`: restore or discard the autosave (section 8) |
| POST | `/api/export/py` | returns the exported script |
| GET | `/api/map/{id}` | Map Viewer layers: status, bounds, bands, statistics, style (section 8) |
| GET | `/api/map/{id}/inspect?lon&lat` | band values of every raster layer at a point |
| GET | `/api/raster/{key}/stats?bands` | 2–98 % stretch of bands, classes of a small-integer band |
| GET | `/tiles/{key}/{z}/{x}/{y}.png?bands&colormap&min&max` | raster tiles for Map Viewer (rio-tiler) |
| GET | `/api/vector/{key}.geojson` | vector layer in EPSG:4326, max 50 000 features; total in `X-GeoKnit-Features` |
| WS | `/ws` | events: node state changes, log lines, run finished |

The server binds to `127.0.0.1` only.

Details:

- One server holds one project folder and one open workflow. Relative paths
  resolve against the workflow's folder (the project folder while it is
  unsaved), as in `geoknit run`. Save and open take a `.geoknit` path
  relative to the project folder; paths outside it are refused.
- `GET /api/graph` returns `{workflow, nodes, out_of_date, path, trusted,
  running, dirty, can_undo, can_redo, recovery}`: `workflow` is the `.geoknit` document, `nodes` maps each id to
  its title, state, ports, and (components) settings with their form hints,
  source, `modified` and `parse_error`.
- `PATCH /api/nodes/{id}` changes only the fields sent: `settings`
  (`{name: value}`), `source`, `ports` (`{inputs, outputs}`, each a list of
  `{name, type, access?, file?, was?}` where `was` is the old name of a
  renamed port), `value`, `min`/`max`/`step`, `position`, `display`, and for
  a Map Viewer `map` (`{basemap?, styles?: {layer id: style | null}}`, merged
  into the saved settings; `null` resets a layer to its defaults).
- `{key}` in the map routes is a port key `<node key>.<port>` from
  `GET /api/map/{id}`; a key that is not in the disk cache answers `404`.
- `POST /api/run` starts the run in the background and answers `202
  {plan}` at once; progress arrives on `/ws`. While a run is active, a second
  run and every edit that changes results answer `409` ("stop the run
  first"); position, display and group changes are still allowed, undo and
  redo are not.
- Errors answer `{"detail": message}`: `400` for refused edits (the
  messages of section 3), `403` for a read-only workflow (section 11), `404`
  for an unknown node.
- `/ws` sends JSON events: `states {states, out_of_date}` on connect, after
  every edit and after each run; `started`, `log {line}`, `done {outputs,
  cached}`, `error {traceback}`, `skipped {traceback}` per node, each with
  `node`; `run_finished {report: {ran, cached, failed, skipped, ok}}`;
  `workflow_opened {path}`; `worker {python, worker, pid}` when a run starts
  and ends; `node_changed {node}` when a file open in VS Code was applied to
  its node.
- Until export (section 10) is built, `/api/export/py` answers `501`.

---

## 10. Export to Python

`Export .py` writes one script that runs without GeoKnit installed (except
`geoknit.helpers`, which is vendored into the script if used):

- Slider and Text values become constants at the top, so the script stays
  easy to tweak.
- Each component becomes a function `def n07_reclassify(raster, breaks): ...`
  containing its settings block and code and returning its outputs.
- `main()` calls the functions in topological order.

The exported script must give the same results as GeoKnit for the same
inputs and seeds; CI checks this on the synthetic example.

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
- The wheel contains the built frontend in `geoknit/server/static/`; users
  never need Node.
- Geo stack from wheels only: rasterio, pyogrio, shapely, pyproj, geopandas,
  rioxarray. Never import `osgeo`. The worker ignores a system
  `PROJ_LIB` / `PROJ_DATA` / `GDAL_DATA` (section 6, "Worker protocol").
- A component can declare `requires`; if a package is missing, GeoKnit offers
  to `pip install` it into its own environment.
- License: Apache-2.0.

---

## 13. Later versions

Earth Engine pack (GEE Image, GEE Extract, GEE Export, sign-in), working
assistant, list auto-iteration, environment picker, desktop installer,
translations, more models (gradient boosting, XGBoost/LightGBM), deep
learning pack.
