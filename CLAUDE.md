# GeoKnit

Local, open-source visual programming for geospatial analysis, in the style
of Grasshopper for Rhino. Components are small Python scripts (like GHPython)
with typed inputs and outputs, wired on a browser canvas served by a local
Python backend. First target workflow: sample → extract → train → predict →
validate (Milan imperviousness example).

- **Read `docs/SPEC.md` before changing behaviour.** It is the source of
  truth. If you change behaviour, update the spec in the same change.
- **`PLAN.md` tracks progress.** Work on one phase step at a time, tick its
  boxes when its "Done when" checks pass, and do not start the next phase
  before the current one is done.

## Repository layout

```
geoknit/                  Python package
  core/                   headless engine: no server/frontend imports
    types.py              data types, describe(), ModelBundle
    component.py          component file format: header, settings block, run
    settings_edit.py      ast-based in-place editing of settings literals
    graph.py              nodes, ports, wires, type + cycle checks
    solver.py             topological order, out-of-date propagation, run plans
    executor.py           in-process executor (fast engine tests; no cache)
    cache.py              cache keys, disk cache read/write, eviction
    workflow.py           .geoknit load/save, migrations
    export.py             export workflow to a .py script
  runtime/
    worker.py             worker process: runs components, holds results
    protocol.py           message types between server and worker
    client.py             WorkerExecutor: spawns the worker, runs plans, Stop
  components/
    registry.py           loads built-ins, user folder, entry-point packs
    builtin/<category>/*.py   one component file each
  helpers/                small utilities components may import (parse_breaks, ...)
  server/
    app.py                FastAPI app, routes, WebSocket
    files.py              project folder tree
    tiles.py              rio-tiler endpoints for Map Viewer
    static/               built frontend (generated, git-ignored)
  cli.py                  `geoknit`, `geoknit run`
frontend/                 React + TypeScript + Vite
  src/strings.ts          ALL user-facing text lives here
examples/
  synthetic/              make_data.py + imd.geoknit (used by tests and CI)
  milan_imd/              milan_imd.geoknit + README; data/ is git-ignored
tests/
docs/SPEC.md
```

## Commands

```bash
pip install -e ".[dev]"            # backend + dev tools
pytest                             # all Python tests
pytest tests/core -q               # engine only
ruff check . && ruff format .      # lint + format
python examples/synthetic/make_data.py   # create small test rasters/vectors
geoknit run examples/synthetic/imd.geoknit   # headless run

cd frontend && npm install
npm run dev                        # Vite dev server, proxies /api to the backend
npm run build                      # builds into geoknit/server/static
npm test                           # Vitest
npx playwright test                # end-to-end
```

## Rules

- **Windows first-class.** Use `pathlib`, no shell-specific commands in code,
  `multiprocessing` with the spawn start method everywhere. CI runs on
  `windows-latest` and `ubuntu-latest`.
- **Geo stack from wheels only**: rasterio, pyogrio, shapely, pyproj,
  geopandas, rioxarray. Never `import osgeo`.
- **`geoknit/core` stays headless**: it must not import from `server`,
  `runtime` or anything web-related.
- **Rasters stay lazy.** No `.load()` on a whole raster unless unavoidable;
  `describe()` never reads pixels; prediction is windowed.
- **The component file format is a public contract** (SPEC section 4).
  Community packs will depend on it. Changes need a spec update and must stay
  backward compatible or bump the format with a migration.
- **Every built-in component has a test** using the synthetic data from
  `examples/synthetic/make_data.py` (small rasters generated in the test
  session). Never commit real data; `data/` folders are git-ignored.
- **API first.** Every UI action goes through a REST endpoint (SPEC section
  9), so an AI agent can later do the same things.
- **All UI text in `frontend/src/strings.ts`**, so translations can be added
  later.
- **No new dependency** without adding it to `pyproject.toml` or
  `package.json` with a lower bound and a one-line reason in the PR.
- Type hints on all Python functions; `ruff` clean; TypeScript `strict`.

## Definition of done for any change

1. Tests for the new behaviour pass locally (`pytest`, and `npm test` if the
   frontend changed).
2. `ruff check .` passes.
3. SPEC.md updated if behaviour changed; PLAN.md boxes ticked.
4. Works on Windows (CI green on both platforms).
