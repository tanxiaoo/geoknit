# GeoKnit build plan (v0.1)

Goal of v0.1: the Milan IMD workflow can be built on the canvas, run end to
end, show its accuracy metrics in a Panel, be saved and reopened, and be
exported to a `.py` script that gives the same result. `pip install geoknit`
works on Windows.

Each phase ends with **Done when** checks. Do not start the next phase until
they pass. Details of every behaviour are in `docs/SPEC.md`.

Suggested way to work with Claude Code: one phase step per session, start in
plan mode, ask it to read `CLAUDE.md`, `docs/SPEC.md` and the step below, and
review its plan before it writes code.

---

## Phase 0: Repository setup

- [x] GitHub repo `tanxiaoo/geoknit`, Apache-2.0 `LICENSE`, short `README.md`
- [x] `pyproject.toml` (hatchling), package skeleton as in CLAUDE.md, extras `[dev]`
- [x] `geoknit --version` CLI entry point
- [x] `frontend/` with Vite + React + TypeScript (strict), empty app
- [x] ruff config, pytest config, `.gitignore` (`data/`, `.geoknit/`, `geoknit/server/static/`, `node_modules/`)
- [x] GitHub Actions: lint + tests on `ubuntu-latest` and `windows-latest`, Python 3.11 and 3.12; frontend build + `npm test`

**Done when:** on your Windows machine `pip install -e ".[dev]"` and
`geoknit --version` work, and CI is green on both platforms.

---

## Phase 1: Headless engine (`geoknit/core`)

- [x] `types.py`: the six types, `ModelBundle`, `describe()` for each (metadata only), connection rules
- [x] `component.py`: parse header (YAML in comments), settings block (literals only, `options` / `range` / `multiline` hints), code block; run one component following SPEC 4 "Running one component", capturing print/warnings/tracebacks with correct line numbers
- [x] `settings_edit.py`: change one setting in the source text without touching comments or formatting
- [x] `graph.py`: nodes, ports, wires; type check, `item`/`list` access, cycle refusal
- [x] `solver.py`: topological order, out-of-date propagation, plans for Run / Run to here / Test
- [x] `workflow.py`: `.geoknit` save/load (SPEC 5), relative paths, `format` field
- [x] In-process executor (no worker yet) used by tests

**Done when** (pytest):
- a 3-node graph (Text → component → component) loaded from JSON runs and gives the expected output
- changing a setting marks only that node and downstream out of date
- settings round-trip: edit each setting kind via `settings_edit`, re-parse, all comments and other lines unchanged
- a component with an error reports the traceback with the line number inside the component file
- wiring Raster → Number and creating a cycle are both refused with clear messages
- save → load → save produces an identical file

---

## Phase 2: Worker and cache (`geoknit/runtime`, `core/cache.py`)

- [ ] Worker process (spawn) holding results in memory; message protocol from SPEC 6
- [ ] Cache keys (source + settings + input keys + file size/mtime for file readers)
- [ ] Disk cache in `<project>/.geoknit/cache/` with the formats from SPEC 6, LRU limit, clear
- [ ] Stop: terminate worker, mark node `error: stopped`, restart worker
- [ ] `geoknit run file.geoknit` headless command, printing Panel contents

**Done when** (pytest):
- running the same graph twice: second run executes nothing (all cache hits)
- after restarting the worker, results come back from the disk cache
- a component that sleeps 60 s is stopped within 2 s, and the next run works
- all of the above pass on Windows CI

---

## Phase 3: Built-in components and synthetic example

- [ ] `examples/synthetic/make_data.py`: small (e.g. 200 × 200) "IMD" raster 0–100, 8-band predictor raster with band names, AOI polygon, reference points with a field — all in EPSG:32632, generated with a fixed seed
- [ ] `geoknit/helpers/parse_breaks` and tests for the breaks syntax (exact values first, `a-b` = a < x ≤ b)
- [ ] All built-ins from SPEC 7 except Map Viewer (frontend phase), each as a component file with a test
- [ ] Python component template (empty component with editable ports, `out` output)
- [ ] Registry: built-ins, `~/.geoknit/components/`, entry-point packs (test with a tiny fake pack)
- [ ] `examples/synthetic/imd.geoknit`: the Milan-shaped workflow on synthetic data
- [ ] `examples/milan_imd/prepare_reference.py`: EarthLabel CSV → `earthlabel_2018.gpkg` (SPEC 7)
- [ ] `examples/milan_imd/milan_imd.geoknit` + README (which four files to copy into `data/`, expected CRS and band names)

**Done when:**
- `geoknit run examples/synthetic/imd.geoknit` prints the metrics table
- Reclassify with `0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100` returns one raster with classes 1–7 (test checks values at 0, 20, 20.5, 100)
- Predict Raster on a raster with a missing band fails with a message naming it
- you run `geoknit run examples/milan_imd/milan_imd.geoknit` on your Milan data and the metrics look plausible next to your notebook results

---

## Phase 4: Server API

- [ ] FastAPI app with all endpoints in SPEC 9, WebSocket events from the worker
- [ ] Project folder tree endpoint (hides `.geoknit/`)
- [ ] `geoknit [folder]`: start on a free port on 127.0.0.1, open the browser
- [ ] Trust check when opening a workflow (SPEC 11)

**Done when** (pytest with FastAPI TestClient):
- the synthetic workflow can be built entirely through the API (add nodes, wire, set values), run, and its Panel output read back
- WebSocket receives started/log/done events in order
- `/docs` shows the OpenAPI page

---

## Phase 5: Canvas

- [ ] Layout from SPEC 8: top bar, ribbon with tabs and search, project folder tree, canvas, status bar, Assistant placeholder
- [ ] Grasshopper-style node renderer (inputs left, centre strip with name or icon, outputs right), port and wire colours by type, Show as Text | Icon switch
- [ ] Number Slider, Text (inline edit), Panel (yellow, resizable) nodes
- [ ] Wiring with type check feedback; drag from port to empty space → filtered search
- [ ] Out-of-date / running / error / selected visuals, "N components out of date · Run" banner, Run / Stop
- [ ] Drag a file from the folder tree → Text node with its relative path
- [ ] Save / open, undo / redo, copy / paste, groups, autosave
- [ ] Hover tooltip with `describe()` summary

**Done when** (Playwright on the synthetic example):
- build the workflow from scratch with drag and drop, run it, and the metrics Panel fills in
- change a slider: exactly the downstream nodes turn out of date; Run recomputes only those
- reload the page: the workflow comes back identical

---

## Phase 6: Component window

- [ ] Double-click opens the floating window: Settings tab, Code tab (Monaco), Output always visible below, Test and OK
- [ ] Settings ↔ Code sync through `settings_edit` (SPEC 4)
- [ ] Python component: add / remove / rename ports and set their type from the window
- [ ] Modified built-ins stored inline with `based_on`, "modified" mark on the node
- [ ] "Save as component…" into `~/.geoknit/components/`, shows up in the ribbon
- [ ] Open in VS Code (writes a temp file, watches it, applies changes)

**Done when** (Playwright):
- change `n_trees` in Settings → the Code tab shows the new value, and the reverse
- break the code on purpose → Output shows the traceback with the right line; Settings tab shows the parse error if the settings block is broken
- edit Reclassify's code, save the workflow, reopen: the edit is still there and the node shows "modified"

---

## Phase 7: Map Viewer

- [ ] Map Viewer component with a `list` input, double-click opens a MapLibre window
- [ ] Raster tiles via rio-tiler from cached COGs (overviews built when cached), default 2–98 % stretch, categorical palette for small integer rasters, RGB for 3 bands
- [ ] Vector layers as GeoJSON (EPSG:4326, feature limit)
- [ ] Layer list, colormap / min / max / band / opacity, legend, click to inspect values

**Done when:**
- the synthetic predicted raster and the reference points show in the right place over the basemap
- the clicked pixel value equals the value read with rasterio at that coordinate (test)
- panning a Milan AlphaEarth layer stays smooth (tiles from overviews, not full reads)

---

## Phase 8: Export, packaging, release

- [ ] Export .py (SPEC 10)
- [ ] Release build: frontend built into `geoknit/server/static`, included in the wheel
- [ ] Docs: `docs/writing-components.md` (the component format with examples), Milan example walkthrough with screenshots
- [ ] Publish `geoknit` 0.1.0 to PyPI, GitHub release

**Done when:**
- exported synthetic script run with plain Python gives exactly the same metrics as GeoKnit (CI)
- on a clean Windows machine: `pip install geoknit`, `geoknit`, open `examples/milan_imd`, Run, see metrics
- a colleague can follow the README without your help

---

## After v0.1

Earth Engine pack (sign-in, GEE Image, GEE Extract, GEE Export); assistant
panel driven by Claude Code or another LLM through the API; list
auto-iteration; environment picker; desktop installer; translations.
