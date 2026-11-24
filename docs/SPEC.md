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
  Stop kill a stuck run without killing the app.
- `geoknit/core` (graph, types, component format, solver, serialization,
  export) has no dependency on the server or frontend and can run headless.
  `geoknit run file.geoknit` uses it directly.

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
- Everything else is refused when the user drops the wire, with a tooltip
  such as "Raster can't connect to Number".
- An input has `access: item` (default, one wire) or `access: list`
  (several wires, collected into a Python list in wire order). Only Map
  Viewer uses `list` in v0.1.
- Cycles are refused when the wire is created.

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

### Settings block

- Between `# --- settings ---` and `# --- code ---`.
- Only top-level assignments whose value is a literal: int, float, str,
  bool, None, or a list/tuple of those. Anything else is a parse error,
  shown in the component's Output.
- An optional trailing comment shapes the Settings form:
  `# options: a | b | c` → dropdown, `# range: 0..1000` → number field with
  limits, `# multiline` → text area. No comment → text field.
- A setting whose name equals an input name is that input's default value.
  An input with no same-named setting is required.

### Code block

Plain Python after `# --- code ---`. Inputs are available as variables;
outputs are read back by name when the code ends.

### Running one component

1. Create a fresh namespace.
2. Execute the settings block.
3. For each wired input, assign its value, overriding the setting.
4. A required input that is neither wired nor set → error
   `input "raster" is not connected`.
5. Execute the code block, capturing `print`, warnings and logging into the
   component's Output.
6. Read each declared output from the namespace. Missing → error. Wrong
   type → error naming expected and actual type.
7. Exceptions show the traceback in Output, with line numbers relative to the
   component file.

The Python component on the canvas additionally has an `out` Text output
holding everything printed, as in GHPython.

### Settings ↔ Code sync

- The Settings tab edits the settings block in place: parse with `ast`,
  replace only the source span of the changed literal, keep comments and
  formatting. A round-trip test must prove this.
- The Code tab edits the whole file (Monaco). On apply, the file is
  re-parsed; the Settings tab and the node's ports update from the header.
- If the header or settings block fails to parse, the Settings tab shows the
  error and is disabled until the code is fixed.

### Where component code is stored

- Unmodified library component: the workflow stores a reference
  (`builtin/raster/reclassify`, version) plus the current settings values.
- Modified code (anything outside the settings block differs from the
  library source): the workflow stores the full source and
  `based_on: builtin/raster/reclassify@<version>`. The node shows a small
  "modified" mark.
- "Save as component…" writes the file to
  `~/.geoknit/components/<category>/<name>.py`. It appears in the ribbon
  under its category, marked as a user component.

### Community packs

A pip package declares an entry point in group `geoknit.components` that
returns a folder path. Every component file in that folder is loaded at
startup. New categories become new ribbon tabs.

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
  `.geoknit` file when they point inside it.
- `format` is bumped on breaking changes, with a migration function.

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

- **Run**: every out-of-date node, in topological order.
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

- server → worker: `run_node {node_id, source, settings, inputs: {port: cache_key}, cache_key}`
- worker → server: `started`, `log {line}`, `done {outputs: {port: {cache_key, summary}}}`,
  `error {traceback}`.

The server forwards these as WebSocket events to the browser.

### Cache

- `cache_key = sha256(component source with settings + sorted input cache
  keys + for file-reading components: absolute path, size, mtime)`.
- Lookup order: worker memory → disk → run.
- Disk cache: `<project>/.geoknit/cache/<key>/`. Raster → COG, Vector →
  GeoParquet, Table → Parquet, Model → joblib, Number/Text → JSON.
  Read Raster results are not copied (they are lazy views of the source
  file).
- Default limit 10 GB, least-recently-used eviction, "Clear cache" in the
  menu.

### Large rasters (city scale, ~2 Sentinel-2 tiles, 64 bands)

- Built-ins never call `.load()` on a whole raster unless they must.
- Extract Values samples at point locations without loading the raster.
- Predict Raster works in windows (default 512 px), writes a COG into the
  cache and returns it opened lazily.
- `describe()` uses metadata only.

---

## 7. Built-in components (v0.1)

Breaks syntax used by Reclassify: rules separated by `|`. A single number is
an exact match; `a-b` means a < x ≤ b. Exact rules are checked first.
Classes are numbered 1…N in rule order; 0 means no rule matched.
Example: `0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100` gives one raster
with 7 classes.

| Tab | Component | Inputs | Outputs | Settings / notes |
|-----|-----------|--------|---------|------------------|
| Params | Number Slider | – | Number | min, max, step, value |
| Params | Text | – | Text | value; edit inline on double-click |
| Params | Panel | data: Any | data: Any (pass-through) | shows `describe()`; yellow, resizable |
| Params | Map Viewer | layers: Any (list) | – | double-click opens map window (section 8) |
| Raster | Read Raster | path: Text | raster | bands="all", masked=True |
| Raster | Write Raster | map: Raster, path: Text | file: Text | COG, compress="deflate" |
| Raster | Reclassify | raster, breaks: Text | classes: Raster | no_match, dtype |
| Raster | Clip | raster, aoi: Vector | raster | all_touched=False |
| Raster | Align Raster | source, reference: Raster | raster | resampling="nearest" |
| Raster | Band Select | raster, bands: Text | raster | bands as "1,2,3" or names |
| Vector | Read Vector | path: Text | vector | layer=None |
| Vector | Write Vector | vector, path: Text | file: Text | format from extension |
| Vector | Reproject | vector, crs: Text | vector | |
| Sampling | Stratified Sample | classes: Raster, value: Raster, aoi: Vector, n: Number, seed: Number | points: Vector | equal n per class (warn if a class has fewer pixels); points at pixel centres; value_field="value", class_field="cls" |
| Sampling | Random Sample | raster, aoi: Vector, n, seed | points: Vector | only valid (non-nodata) pixels |
| Sampling | Extract Values | points: Vector, raster: Raster | table: Table | columns from band descriptions, else b01…; keeps point attributes; drops nodata rows with a warning; sets `table.attrs["feature_columns"]` |
| Sampling | Train/Test Split | table | train: Table, test: Table | test_fraction=0.3, seed=42, stratify_by=None |
| Model | Random Forest | table, target: Text, n_trees, max_depth, min_leaf, seed | model: Model | task="regression", max_features="sqrt", features="auto" (feature_columns attr, else numeric columns except target) |
| Model | SVM | table, target: Text | model: Model | task, kernel="rbf", C=1.0, gamma="scale", standardize=True |
| Model | Predict Raster | model, raster | map: Raster | window=512; band names must equal `model.feature_names`, else error listing the missing ones; float32 for regression, smallest int type for classes |
| Validation | Accuracy | map: Raster, reference: Vector, field: Text | metrics: Table | n, RMSE, MAE, R², bias (observed − predicted); nearest pixel; points outside or on nodata dropped and counted |
| Validation | Confusion Matrix | map, reference: Vector, field: Text | matrix: Table, metrics: Table | overall accuracy, kappa, producer's/user's accuracy and F1 per class |
| Script | Python | user-defined | user-defined + out: Text | ports added/removed in the component window |

Random Forest and SVM inputs that also appear as settings (n_trees, max_depth,
min_leaf, seed) can be left unwired; the setting is then used.

### Reference workflow: Milan IMD (`examples/milan_imd/`)

```
Text data/CLMS_2018_Milan_UTM32N.tif ─ Read Raster ─┬─ Reclassify ← Text breaks ─┐
                                                    └──────────── value ─────────┤
Text data/aoi_milan.gpkg ── Read Vector ─────────────────────── aoi ─────────────┤
Slider n, Slider seed ───────────────────────────────────────────────────────────┴─ Stratified Sample
Text data/AlphaEarth_2018_Milan_UTM32N.tif ─ Read Raster ──┬─ Extract Values ← points
                                                           │        └─ Random Forest ← Text "IMD", Slider n_trees
                                                           └─ Predict Raster ← model ─┬─ Write Raster ← Text outputs/imd_rf.tif
Text data/earthlabel_2018.gpkg ─ Read Vector ─────────────────────── reference ───────┴─ Accuracy ← Text "imd_ref" ─ Panel
```

The data files are copied into `examples/milan_imd/data/` by the user and are
git-ignored:

| File | Content |
|------|---------|
| `CLMS_2018_Milan_UTM32N.tif` | 1 band, CLMS IMD 2018 in %, float32, nodata 255 |
| `aoi_milan.gpkg` | one polygon (layer `milano_city_rect_UTM32N`) |
| `AlphaEarth_2018_Milan_UTM32N.tif` | 64 bands named A00…A63, float32, nodata NaN |
| `milan_imd_2018_results_cells.csv` | 450 EarthLabel plots (`LAT`/`LON` in WGS84, `ref_label`, `cells_json`) |

All rasters are EPSG:32632, 10 m. The AlphaEarth GeoTIFF is exported from
Earth Engine once, outside GeoKnit. The EarthLabel CSV is turned into
`earthlabel_2018.gpkg` once, also outside GeoKnit, by
`examples/milan_imd/prepare_reference.py`: points in EPSG:32632 with fields
`PLOTID`, `stratum` (from `ref_label`) and `imd_ref`, the impervious share in %
of the plot's resolvable sub-cells in `cells_json`.

---

## 8. User interface

Layout, top to bottom and left to right (see the design mockup):

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
- **Status bar (bottom)**: data-type colour legend, state legend.
- **Assistant (right)**: collapsible placeholder marked "Next version".

Component window (double-click a node): floating and draggable, header with
category and name; tabs **Settings** (inputs with their wired source or an
editable default, the component's settings, "show on canvas as") and
**Code** (Monaco editor with the full component file, Open in VS Code);
**Output** always visible below both tabs; buttons Test and OK.
Number Slider opens a small window with min/max/step/value. Text is edited
inline.

Map Viewer window: MapLibre map with a light basemap, a layer list from the
wired inputs, per-layer colormap / min / max / band(s) / opacity, a legend,
and click-to-inspect pixel values of every layer.

Interactions: drag port to port to wire; drag from a port into empty space
opens search filtered to compatible types; Delete; Ctrl+Z / Ctrl+Y;
Ctrl+C / Ctrl+V; Ctrl+G group; Ctrl+S save; wheel zoom; middle-drag or
space-drag pan; Fit. Hovering a port or wire shows its `describe()` summary
after a run.

---

## 9. Server API

Every UI change goes through this API, so an AI agent can later do anything
the user can. FastAPI publishes the OpenAPI schema at `/docs`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/components` | library for the ribbon (header metadata) |
| GET | `/api/graph` | current workflow |
| POST | `/api/nodes` | add a node `{component, position}` |
| PATCH | `/api/nodes/{id}` | change settings, source, position, display, value |
| DELETE | `/api/nodes/{id}` | remove |
| POST | `/api/wires` / DELETE `/api/wires` | connect / disconnect (type and cycle checks) |
| POST | `/api/run` | `{mode: all | to_node | test, node_id?}` |
| POST | `/api/stop` | stop the worker |
| GET | `/api/nodes/{id}/output` | Output log and per-port summaries |
| GET | `/api/files` | project folder tree |
| POST | `/api/workflow/save`, `/api/workflow/open` | file operations |
| POST | `/api/export/py` | returns the exported script |
| GET | `/tiles/{key}/{z}/{x}/{y}.png` | raster tiles for Map Viewer (rio-tiler) |
| GET | `/api/vector/{key}.geojson` | vector layer in EPSG:4326, max 50 000 features |
| WS | `/ws` | events: node state changes, log lines, run finished |

The server binds to `127.0.0.1` only.

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

---

## 12. Packaging and platform

- Python ≥ 3.11. Install with `pip install geoknit`. Windows is a
  first-class platform.
- `geoknit [folder]` starts the server on a free local port and opens the
  browser. `geoknit run file.geoknit` runs headless and prints Panel
  contents.
- The wheel contains the built frontend in `geoknit/server/static/`; users
  never need Node.
- Geo stack from wheels only: rasterio, pyogrio, shapely, pyproj, geopandas,
  rioxarray. Never import `osgeo`.
- A component can declare `requires`; if a package is missing, GeoKnit offers
  to `pip install` it into its own environment.
- License: Apache-2.0.

---

## 13. Later versions

Earth Engine pack (GEE Image, GEE Extract, GEE Export, sign-in), working
assistant, list auto-iteration, environment picker, desktop installer,
translations, more models (gradient boosting, XGBoost/LightGBM), deep
learning pack.
