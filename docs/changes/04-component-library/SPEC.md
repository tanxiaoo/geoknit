# Change 04: Component library

Status: agreed (checked against the code, 26 Nov 2026) · Needs 01 (types,
`[A, B]`, `like:`, list values, editable ports and `INPUTS`, groups, icons);
the Display rows need 03 · Touches `docs/SPEC.md` sections 4 (`tags:`), 7

## Questions for Xiao

None open. Question 1 (XLSX needs `openpyxl`) was answered on 26 Nov 2026
with option (c): no XLSX. Read Table and Write Table handle CSV/TSV and
Parquet only, so no new dependency is needed.

---

All components are ordinary component files (SPEC 4), each with a test, as
in Phase 3, except the server-handled Params nodes (change 01, section 8)
and Map Layer (change 03). Tabs and groups follow change 01, section 7; their
order is `geoknit/components/builtin/_layout.yaml`.

New built-in folders follow the tab in lower case, so references read
`builtin/maths/add`, `builtin/sets/list_item`, `builtin/table/select_rows`,
`builtin/params/point`. Two components may share a display name in
different tabs (Raster › Clip `builtin/raster/clip`, Vector › Clip
`builtin/vector/clip`). The search popup shows "Tab › Group" next to each
name (change 01), so they can be told apart.

Each row is marked **0.1.0** (part of the release) or **0.1.x** (patch
releases after it). ✓ = exists today (possibly with a new tab, group, icon or
name). Icons follow the rule **Font-GIS (`gis:`) → Lucide (`lucide:`) →
Tabler (`tabler:`)**. Every name below was checked on 26 Nov 2026: Lucide
against the installed `lucide-react` 1.79, Font-GIS against `font-gis.json`
of release 1.0.6, Tabler against the current `@tabler/icons` outline set.
Server-handled nodes (Params, Map Layer, Map Viewer) take their icon from
the server's Params entries (change 01, section 7), not from a header.

---

## 1. Shared rules

**Expressions.** Maths › Expression, Raster Calculator, Table › Add Column
and Select Rows evaluate a short expression. One evaluator,
`geoknit.helpers.safe_eval`, parses it with `ast` and allows only: numbers,
strings, `True/False/None`, the declared input names, `+ - * / // % **`,
comparisons (also chained), `and or not`, `&` `|` `~` (element-wise for
rasters and columns), parentheses, subscripts on inputs (`a[1]`, `a["B8"]`),
and the functions `abs round min max sqrt exp log log10 sin cos tan floor
ceil clip where isnan` plus `pi`, `e`. Anything else (attributes, imports,
lambdas, other calls) is an error that names the offending part. Table
expressions also allow column names that are valid identifiers, and any
column in backticks (`` `land cover` ``). It is vendored on export with the
other helpers (`VENDOR_FILES` in `core/export.py` gains each new helper
module).

The names an expression can use are the component's inputs, which the
user adds and renames. The code gets them from `INPUTS` (change 01,
section 6) and calls `safe_eval(expression, INPUTS)`. Format calls
`template.format(**INPUTS)`.

**CRS.** Components that combine two Vectors (overlay, spatial join) or a
Vector and a Raster reproject the second input to the CRS of the first and
log one line saying so. Distances and areas (Buffer, Area & Length,
Points in Polygon `min_distance`, Simplify) are in CRS units; on a
geographic CRS (degrees) they stop with "reproject to a projected CRS first
(e.g. EPSG:32632)".

**Rows and ranges.** Delete Rows and similar take `"0, 3, 5-9"`: positions
counted from 0, `a-b` inclusive, negative counts from the end
(`geoknit.helpers.parse_positions`).

**Coordinates.** Polyline and Polygon take `"x y, x y, …"` (comma between
points, space or `;` inside a point), or WKT when the text starts with a
letter (`POLYGON((…))`) (`geoknit.helpers.parse_coords`).

**Vectors as tables.** Table tools that accept `[Table, Vector]` keep the
geometry column and the CRS of a Vector untouched; a column operation never
touches `geometry`, and selecting columns always keeps it.

---

## 2. Params

Params nodes (server-handled) come from change 01, section 8; listed here so
the tab is complete. The Geometry rows are component files in
`builtin/params/`.

| Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-------|-----------|--------|---------|------------------|------|---------|
| Input | Text ✓ | – | Text | | `lucide:type` | 0.1.0 |
| Input | Number | – | Number | integer mode | `lucide:hash` | 0.1.0 |
| Input | Number Slider ✓ | – | Number | + integer mode | `lucide:sliders-horizontal` | 0.1.0 |
| Input | Boolean Toggle | – | Boolean | | `lucide:toggle-left` | 0.1.0 |
| Input | Value List | – | Number \| Text | options | `lucide:list` | 0.1.0 |
| Geometry | Point | x, y: Number, crs: Text | point: Vector | crs="EPSG:4326"; one feature | `gis:point` | 0.1.0 |
| Geometry | Polyline | coords: Text, crs: Text | line: Vector | coordinates or WKT | `gis:polyline` | 0.1.0 |
| Geometry | Polygon | coords: Text, crs: Text | polygon: Vector | ring closed automatically; invalid ring → error | `gis:polygon` | 0.1.0 |
| Geometry | Bounding Box | xmin, ymin, xmax, ymax: Number, crs: Text | box: Vector | | `gis:bbox` | 0.1.x |
| Style | Color Swatch | – | Color | | `gis:color` | 0.1.0 |
| Style | Colormap | – | Colormap | editor in change 03 | `gis:map-legend` | 0.1.0 |
| Inspect | Panel ✓ | data: Any | data: Any | | `lucide:clipboard-list` | 0.1.0 |

## 3. Maths

All on Number (and Boolean where noted). Division by zero, `log` of ≤ 0 and
similar are errors naming the inputs, never `inf`/`nan` passed on silently.

| Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-------|-----------|--------|---------|------------------|------|---------|
| Operators | Add | a, b | result: Number | | `lucide:plus` | 0.1.0 |
| Operators | Subtract | a, b | result | | `lucide:minus` | 0.1.0 |
| Operators | Multiply | a, b | result | | `lucide:x` | 0.1.0 |
| Operators | Divide | a, b | result | | `lucide:divide` | 0.1.0 |
| Operators | Power | a, b | result | | `lucide:superscript` | 0.1.x |
| Operators | Modulo | a, b | result | | `lucide:percent` | 0.1.x |
| Compare | Greater Than | a, b | result: Boolean | or_equal=False | `tabler:math-greater` | 0.1.0 |
| Compare | Less Than | a, b | result: Boolean | or_equal=False | `tabler:math-lower` | 0.1.0 |
| Compare | Equal | a, b | result: Boolean | tolerance=0 | `lucide:equal` | 0.1.0 |
| Logic | And | a, b: Boolean | result: Boolean | | `tabler:logic-and` | 0.1.0 |
| Logic | Or | a, b: Boolean | result: Boolean | | `tabler:logic-or` | 0.1.0 |
| Logic | Not | a: Boolean | result: Boolean | | `tabler:logic-not` | 0.1.0 |
| Functions | Expression | editable (Number, Boolean); starts with a, b | result: Number | expression="a * 2 + b"; a Boolean result is an error ("use Greater Than / Equal") | `lucide:variable` | 0.1.0 |
| Functions | Round | x, digits | result | digits=0 | `tabler:number-123` | 0.1.x |
| Functions | Min / Max | values: Number (list) | min, max: Number | | `tabler:math-max-min` | 0.1.x |
| Functions | Remap | x, from_min, from_max, to_min, to_max | result | clamp=False | `lucide:scaling` | 0.1.x |

## 4. Sets

`items: Any (list)` takes wires of any one type. An output `like items`
then has that type, and wires of different types are refused (change 01,
section 4). Before anything is wired, such an output is `Any`.

| Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-------|-----------|--------|---------|------------------|------|---------|
| List | List Item | items: Any (list), index: Number | item: like items | negative index from the end; wrap=False; out of range → error | `tabler:list-search` | 0.1.0 |
| List | List Length | items: Any (list) | length: Number | | `lucide:tally-5` | 0.1.0 |
| List | Sort List | items: Any (list) | sorted: like items (list) | reverse=False; Numbers and Text only, else error | `lucide:arrow-down-wide-narrow` | 0.1.0 |
| List | Reverse List | items (list) | reversed: like items (list) | | `lucide:arrow-down-up` | 0.1.x |
| List | Series | start, step, count: Number | values: Number (list) | | `lucide:list-ordered` | 0.1.0 |
| List | Merge Lists | items: Any (list) | merged: like items (list) | the list input already merges; this names it for readability | `lucide:list-plus` | 0.1.x |
| Text | Concatenate | parts: Text (list) | text: Text | separator="" | `lucide:whole-word` | 0.1.x |
| Text | Format | editable (Text, Number); starts with a | text: Text | template="{a}_{b}.tif" | `lucide:text-cursor-input` | 0.1.0 |
| Text | Split Text | text: Text | parts: Text (list) | separator="," ; strip=True | `lucide:square-split-horizontal` | 0.1.x |

## 5. Table

`data` is `{type: [Table, Vector]}` and outputs are `{like: data}` unless
stated.

| Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-------|-----------|--------|---------|------------------|------|---------|
| Files | Read Table | path: Text | table: Table | CSV/TSV (separator sniffed) and Parquet; another extension → error naming them (no XLSX: it would need `openpyxl`) | `tabler:table-import` | 0.1.0 |
| Files | Write Table | table: [Table, Vector], path: Text (`file: write`) | file: Text | format from extension (.csv, .tsv, .parquet); a Vector writes its attributes plus WKT `geometry` to CSV/TSV, and GeoParquet to .parquet | `tabler:table-export` | 0.1.0 |
| Rows | Add Row | data, values: Text, geometry: Vector (optional) | added | values as `name=value; name=value`; types follow the columns; a Vector needs `geometry` (its first feature) | `tabler:row-insert-bottom` | 0.1.0 |
| Rows | Delete Rows | data, rows: Text | remaining | positions/ranges (section 1) | `tabler:row-remove` | 0.1.0 |
| Rows | Select Rows | data, where: Text | selected | expression, e.g. `cls == 3 and IMD > 50`; invert=False; logs kept/total | `gis:search-attribtues` | 0.1.0 |
| Rows | Sort Rows | data, by: Text | sorted | `"IMD, -area"` (`-` = descending) | `lucide:arrow-up-narrow-wide` | 0.1.0 |
| Rows | Sample Rows | data, n, seed | sampled | fraction=None overrides n | `lucide:dice-5` | 0.1.x |
| Columns | Select Columns | data, columns: Text | selected | `"a, b"`; geometry always kept | `lucide:columns-3` | 0.1.0 |
| Columns | Add Column | data, name: Text, expression: Text | added | expression over columns; replaces a column of the same name only with replace=True | `tabler:column-insert-right` | 0.1.0 |
| Columns | Rename Columns | data, mapping: Text | renamed | `"old=new, old2=new2"` | `lucide:replace` | 0.1.x |
| Columns | Delete Columns | data, columns: Text | remaining | | `tabler:column-remove` | 0.1.x |
| Combine | Join | data, other: Table, on: Text | joined | how="left" (left \| inner); `"id"` or `"left_id=right_id"`; duplicate names get `_other` | `lucide:merge` | 0.1.0 |
| Combine | Merge Rows | tables: [Table, Vector] (list) | merged: like tables | same type required; Vectors reprojected to the first CRS | `lucide:between-horizontal-end` | 0.1.x |
| Combine | Group & Summarize | data, by: Text, summary: Text | table: Table | `"IMD=mean, n=count"`; functions count sum mean median min max std | `lucide:group` | 0.1.x |
| Convert | Attributes | vector: Vector | table: Table | add_xy=False (centroid x/y columns) | `lucide:table` | 0.1.0 |
| Convert | Table to Points | table: Table, x: Text, y: Text, crs: Text | points: Vector | rows with missing x/y dropped and counted | `gis:pois` | 0.1.x |

## 6. Vector

| Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-------|-----------|--------|---------|------------------|------|---------|
| Files | Read Vector ✓ | path | vector | | `gis:shape-file` | 0.1.0 |
| Files | Write Vector ✓ | vector, path | file | | `gis:layer-upload` | 0.1.0 |
| CRS | Reproject ✓ | vector, crs | reprojected | | `gis:proj-geo` | 0.1.0 |
| Points | Centroid | vector | centroids: Vector | inside=False (True = a point guaranteed inside, `representative_point`); attributes kept | `lucide:locate-fixed` | 0.1.0 |
| Points | Random Points in Polygon | polygons: Vector, n: Number, seed: Number | points: Vector | per="polygon" (n each) \| "total" (n spread by area); min_distance=0; `id` and the polygon's attributes kept | `gis:multipoint` | 0.1.0 |
| Points | Vertices | vector | points: Vector | | `gis:polygon-pt` | 0.1.x |
| Geometry | Buffer | vector, distance: Number | buffered | resolution=16, cap="round" (round \| flat \| square), dissolve=False | `gis:buffer` | 0.1.0 |
| Geometry | Dissolve | vector, by: Text | dissolved | empty `by` → one feature | `lucide:combine` | 0.1.x |
| Geometry | Simplify | vector, tolerance: Number | simplified | preserve_topology=True | `gis:simplify` | 0.1.x |
| Geometry | Convex Hull | vector | hulls | per_feature=True | `gis:convex-hull` | 0.1.x |
| Geometry | Area & Length | vector | measured | adds `area`, `length` in CRS units | `gis:measure-area` | 0.1.x |
| Overlay | Clip | vector, mask: Vector | clipped | keeps only the parts inside the mask | `lucide:scissors` | 0.1.0 |
| Overlay | Difference | vector, other: Vector | difference | parts of `vector` not in `other` | `gis:difference` | 0.1.0 |
| Overlay | Intersection | vector, other: Vector | intersection | attributes of both, `_other` suffix on clashes | `gis:intersection` | 0.1.0 |
| Overlay | Union | vector, other: Vector | union | | `gis:union` | 0.1.x |
| Overlay | Spatial Join | vector, other: Vector | joined | predicate="intersects" (intersects \| within \| contains \| nearest) | `gis:search-feature` | 0.1.x |

Select by attribute is **Table › Select Rows** (it takes a Vector); the
search box finds it under "select", "filter" and "attribute" too (search
tags, section 8).

## 7. Raster

| Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-------|-----------|--------|---------|------------------|------|---------|
| Files | Read Raster ✓ | path | raster | | `gis:layer-download` | 0.1.0 |
| Files | Write Raster ✓ | map, path | file | | `gis:layer-upload` | 0.1.0 |
| Bands | Build Multiband | rasters: Raster (list) | stacked: Raster | same grid required, else error suggesting Align Raster; band names kept, duplicates get `_2`, `_3`; names="" renames all (`"B4, B8"`) | `gis:layer-stack` | 0.1.0 |
| Bands | Band Select ✓ | raster, bands | selected | by numbers `"1,2"` or names `"A00,A05"` | `gis:layer-alt` | 0.1.0 |
| Bands | Rename Bands | raster, names: Text | renamed | count must match | `gis:tags` | 0.1.0 |
| Calculate | Raster Calculator | editable (Raster, Number); starts with a: Raster | result: Raster | expression="a"; `a` = band 1 of a single-band raster, `a[2]` / `a["B8"]` pick a band (a multi-band `a` used bare → error listing its bands); all rasters on one grid; nodata in any input → nodata out; dtype="float32"; nodata=-9999; lazy (dask), never loads whole rasters | `lucide:calculator` | 0.1.0 |
| Calculate | Reclassify ✓ | raster, breaks | classes | | `gis:layer-landcover` | 0.1.0 |
| Extent | Clip ✓ | raster, aoi | clipped | | `gis:select-extent` | 0.1.0 |
| Extent | Align Raster ✓ | source, reference | raster | | `gis:snap` | 0.1.0 |
| Extent | Reproject Raster | raster, crs: Text | reprojected | resolution=None, resampling="nearest" | `gis:coord-system` | 0.1.x |
| Convert | Zonal Statistics | raster, zones: Vector | stats: Vector (the zones with the new columns; an output cannot be named like an input) | stats="mean, min, max, count"; band=1; all_touched=False; columns `<band>_<stat>` | `gis:layer-stat` | 0.1.x |
| Convert | Rasterize | vector, reference: Raster, field: Text | raster | all_touched=False; fill=0 | `gis:grid` | 0.1.x |
| Convert | Polygonize | raster | polygons: Vector | band=1; a `value` column; nodata skipped | `gis:hex-map` | 0.1.x |

Example expressions: NDVI `(a["B8"] - a["B4"]) / (a["B8"] + a["B4"])` on a
Sentinel-2 stack with band names B4, B8; threshold from a slider
`where(a > t, 1, 0)` with input `t: Number`. Rasters are opened with
`masked=True` (Read Raster's default), so nodata arrives as NaN. A pixel that
is NaN in any input gets the `nodata` setting in the output, and the output
declares that value as its nodata (`rio.write_nodata`), so the cache's COG
and the Map Viewer treat it as nodata.

## 8. Sampling, Model, Validation (renamed and reorganised)

| Tab | Group | Component | Inputs | Outputs | Settings / notes | Icon | Release |
|-----|-------|-----------|--------|---------|------------------|------|---------|
| Sampling | Draw | Random Sample ✓ | raster, aoi, n, seed | points | | `lucide:dices` | 0.1.0 |
| Sampling | Draw | Stratified Sample ✓ | classes, value, aoi, n, seed | points | + allocation="equal" (equal \| proportional) | `gis:layers-poi` | 0.1.0 (allocation 0.1.x) |
| Sampling | Split | Split Points ✓ (merged, change 01) | data: [Table, Vector] | train, test: like data | test_fraction, seed, stratify_by | `lucide:split` | 0.1.0 |
| Sampling | Extract | Extract Values ✓ | points, raster | table | | `gis:search-coord` | 0.1.0 |
| Model | Train | Random Forest ✓ | | model | | `lucide:tree-pine` | 0.1.0 |
| Model | Train | SVM ✓ | | model | | `lucide:sigma` | 0.1.0 |
| Model | Train | k-NN | table, target: Text, k: Number | model | task, weights="uniform", standardize=True | `tabler:chart-dots` | 0.1.x |
| Model | Train | Gradient Boosting | table, target, n_iter, learning_rate, seed | model | sklearn `HistGradientBoosting*` (no new dependency); task | `lucide:chart-no-axes-column` | 0.1.x |
| Model | Apply | Predict Raster ✓ | model, raster | map | | `lucide:wand-sparkles` | 0.1.0 |
| Model | Apply | Predict Table | model, table | predicted: Table | column `prediction`; missing feature columns → error listing them | `lucide:table-properties` | 0.1.x |
| Model | Inspect | Feature Importance | model, table: Table (optional) | importance: Table | built-in importances when the estimator has them; otherwise permutation importance on `table` (required then) | `lucide:chart-column` | 0.1.x |
| Validation | Classification | Confusion Matrix ✓ | map, reference, field | matrix, metrics | | `lucide:table-2` | 0.1.0 |
| Validation | Classification | Area-adjusted Accuracy | map: Raster, reference: Vector, field: Text | metrics: Table, areas: Table | Olofsson et al. (2014): stratified estimators of overall, user's and producer's accuracy and class areas with 95 % confidence intervals; class areas from map pixel counts inside the reference points' AOI (optional `aoi: Vector`) | `gis:statistic-map` | 0.1.x |
| Validation | Regression | Regression Accuracy ✓ (renamed, change 01) | map, reference, field | metrics | | `lucide:target` | 0.1.0 |

## 9. Display and Script

| Tab | Group | Component | Notes | Icon | Release |
|-----|-------|-----------|-------|------|---------|
| Display | Style | Map Layer | change 03; server-handled `param/layer` | `gis:layer-edit` | 0.1.0 |
| Display | Map | Map Viewer ✓ | change 03; `param/map` | `gis:map` | 0.1.0 |
| Script | Python | Python ✓ | `ports: {inputs: editable, outputs: editable}` (change 01) | `lucide:code` | 0.1.0 |

## 10. Search tags

New optional header key `tags: [select, filter, attribute]` (a list of
strings; anything else is a parse error). It is part of the component format
(SPEC 4), and `GET /api/components` returns it. The ribbon search
(`matches()` in `frontend/src/catalog.ts`) matches the name, category,
description and reference today. It gains tags and group. Built-ins get tags where a GIS
user would search with another word (Select Rows: select, filter, attribute,
query; Buffer: offset; Build Multiband: stack, composite; Raster Calculator:
band math, ndvi, map algebra; Centroid: center, point on surface).

## 11. Counts

| | 0.1.0 | 0.1.x |
|-|------:|------:|
| New components (including Map Layer) | 39 | 32 |
| New Params nodes (change 01) | 5 | – |
| Existing, regrouped, re-iconed or renamed | 23 | – |

---

## Not in this change

- Plot / chart components (Display › Plot, later).
- Map export to PNG/PDF.
- Earth Engine pack (v0.2).
- Raster focal/neighbourhood filters, terrain (slope, aspect), and
  time-series stacks: candidates for a later "Raster+" pack.
