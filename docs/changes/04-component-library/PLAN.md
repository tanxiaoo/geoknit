# Change 04 plan: Component library

Needs change 01 done (types, union inputs, `like:`, list values, editable
ports and `INPUTS`, groups, icons). Read `CLAUDE.md`, `docs/SPEC.md` and
`docs/changes/04-component-library/SPEC.md` before each step.

Every component follows Phase 3's rule: a component file plus a test, on
small synthetic data (`examples/synthetic/make_data.py` gets whatever extra
layers the tests need, still with a fixed seed). Each step adds its rows to
`_layout.yaml` and ticks them in the SPEC tables (✓).

Steps 1–6 are the **0.1.0** set; steps 7–8 are **0.1.x** and can be released
one tab at a time.

---

## Step 1: Shared helpers and search tags

- [ ] `geoknit.helpers.safe_eval` (allowed syntax from SPEC section 1, numbers,
      xarray and pandas operands), `parse_positions`, `parse_coords`,
      `parse_mapping` (`a=b, c=d`)
- [ ] Header key `tags:` (parser, `GET /api/components`); ribbon search
      matches name, tags, tab, group
- [ ] Helpers vendored on export (existing mechanism: add each new module
      to `VENDOR_FILES` in `core/export.py`)

**Done when** (pytest):
- `safe_eval("a * 2 + b", a=1, b=2) == 4`; `__import__`, attribute access,
  lambdas and unknown names are refused with a message naming the part
- `parse_positions("0, 3, 5-7, -1", n=10) == [0, 3, 5, 6, 7, 9]`
- `parse_coords("0 0, 10 0, 10 10")` and the same as WKT give equal geometry
- an exported script that uses `safe_eval` runs with `import geoknit` blocked

## Step 2: Params geometry, Maths, Sets (0.1.0 rows)

- [ ] Point, Polyline, Polygon
- [ ] Add, Subtract, Multiply, Divide; Greater Than, Less Than, Equal; And,
      Or, Not; Expression (editable ports)
- [ ] List Item, List Length, Sort List, Series; Format (editable ports)

**Done when:**
- pytest per component, including: Divide by 0 errors; Expression with a
  Boolean result errors; Expression and Format see inputs the user added
  (through `INPUTS`); List Item `-1` returns the last element and keeps
  its type (a Raster stays a Raster for wiring)
- Playwright: Slider → Multiply → Greater Than → Panel shows `True`, and
  moving the slider below the threshold shows `False` after Run

## Step 3: Table (0.1.0 rows)

- [ ] Read Table, Write Table (CSV/TSV and Parquet; no XLSX); Add Row,
      Delete Rows, Select Rows, Sort Rows; Select Columns, Add Column; Join;
      Attributes

**Done when** (pytest):
- each tool on a Table returns a Table and on a Vector returns a Vector with
  the same CRS and geometry (one parametrised test over all of them)
- Select Rows `cls == 3 and IMD > 50` on the sample points of the
  synthetic workflow (Stratified Sample with `class_field="cls"`,
  `value_field="IMD"`, as in `imd.geoknit`; `reference.gpkg` has
  `imd_ref` and `stratum` instead) keeps exactly the rows pandas `query`
  keeps
- Write Table of a Vector to CSV writes a WKT `geometry` column

## Step 4: Vector (0.1.0 rows)

- [ ] Centroid, Random Points in Polygon, Buffer, Clip, Difference,
      Intersection
- [ ] CRS rule: second input reprojected with a log line; geographic CRS
      refused for distances

**Done when** (pytest):
- Random Points in Polygon with `n=50, per="polygon"` on 3 polygons (the
  synthetic AOI cut in three; `aoi.gpkg` has one polygon) gives 150 points,
  all inside their polygon, identical for the same seed
- Buffer on EPSG:4326 errors with the reproject message
- Difference of a polygon and itself is empty without an error

## Step 5: Raster (0.1.0 rows)

- [ ] Build Multiband, Rename Bands, Raster Calculator (editable ports,
      `a[2]` / `a["B8"]`, nodata propagation, lazy)

**Done when** (pytest):
- Build Multiband of two 1-band rasters on different grids errors naming
  Align Raster; on the same grid gives 2 bands with both names
- Raster Calculator NDVI-style `(a["A07"] - a["A03"]) / (a["A07"] + a["A03"])`
  on the 8-band synthetic `predictors.tif` (bands A00…A07) equals numpy
  computed on the loaded arrays (to 1e-6), and the nodata block of the
  synthetic rasters is nodata in the result
- Raster Calculator's result is still dask-backed (`hasattr(result.data,
  "dask")`, as the Predict Raster test in `tests/components/test_model.py`
  checks); there is no 64-band test raster, and none is needed
- `where(a > t, 1, 0)` with `t` from a Number Slider re-runs when the slider
  moves

## Step 6: Reorganise existing tabs, examples, docs

- [ ] Sampling, Model, Validation groups and icons; Display tab with change 03
- [ ] `examples/synthetic/imd.geoknit` uses a few new components (e.g.
      Raster Calculator, Select Rows, Buffer) on side branches that end in
      Panels, so the metrics path and its numbers stay the same
- [ ] `docs/writing-components.md`: a worked example using `[Table, Vector]`
      + `like:`, and one with editable ports
- [ ] `docs/icons.md` regenerated

**Done when:**
- `geoknit run examples/synthetic/imd.geoknit` prints the same metrics table
  as before change 04; export equivalence test passes
- every component in the ribbon has an icon from the registry (no category
  fallback): the vitest icon test from change 01 step 7, which reads the
  built-in headers and the Params entries
- the 0.1.0 rows of the SPEC are all ✓; release 0.1.0 can go ahead

---

## Step 7 (0.1.x): Params, Maths, Sets, Table, Vector rest

- [ ] Bounding Box; Power, Modulo, Round, Min/Max, Remap; Reverse List,
      Merge Lists, Concatenate, Split Text
- [ ] Sample Rows, Rename Columns, Delete Columns, Merge Rows, Group &
      Summarize, Table to Points
- [ ] Vertices, Dissolve, Simplify, Convex Hull, Area & Length, Union,
      Spatial Join

**Done when:** a test per component; release as 0.1.1.

## Step 8 (0.1.x): Raster, Sampling, Model, Validation rest

- [ ] Reproject Raster, Zonal Statistics, Rasterize, Polygonize
- [ ] Stratified Sample `allocation="proportional"`
- [ ] k-NN, Gradient Boosting, Predict Table, Feature Importance
- [ ] Area-adjusted Accuracy

**Done when:**
- a test per component
- Area-adjusted Accuracy reproduces the worked numerical example in
  Olofsson et al. (2014) to the published precision
- Zonal Statistics mean equals rasterstats-style mean computed with numpy on
  the synthetic data
- release as 0.1.2; merge the SPEC into `docs/SPEC.md`; mark change 04 done
