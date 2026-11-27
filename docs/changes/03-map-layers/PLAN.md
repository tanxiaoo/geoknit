# Change 03 plan: Map layers and colormaps

Needs change 01 steps 1–3 and 6 (types, union inputs, list values, Colormap
and Color nodes) and change 02 step 4 (basemap `auto`). Read `CLAUDE.md`,
`docs/SPEC.md` and `docs/changes/03-map-layers/SPEC.md` before each step.

---

## Step 1: Colormaps in tiles

- [x] Colormap → 256-entry LUT (continuous, rescaled by min/max) and a
      value → RGBA lookup (classes, `other`, alpha), in the colour step of
      `tiles.render_tile` next to `_lut` and the categorical palette
- [x] `/tiles/...?cmap=` (compact JSON); `_check_style` accepts a Colormap
      object as `colormap`
- [x] Legend data from a Colormap in `GET /api/map/{id}` and `legendFor`

**Done when** (pytest, `tests/server/test_map_viewer.py`):
- a classes Colormap `{1: red, 2: blue}` on the synthetic class raster
  (Reclassify of `imd.tif`) gives tiles whose pixels at class 1 and class 2
  are exactly those colours, and transparent elsewhere with `other: None`
- a continuous custom map with fixed min/max gives the stop colour at the
  stop's value (± 1 in each channel)
- a named ramp without customisation renders the same bytes as today

## Step 2: Colormap editor

- [x] Window for `param/colormap`: kind, named ramp, reverse, min/max,
      custom stops, class table, fill from ramp, paste table
- [x] Each change one `PATCH {value}`, so one undo step

**Done when** (Playwright):
- build a 3-class map in the editor, save the workflow, reopen: identical
- paste `1, #FF0000, Built\n2, #00FF00, Green` → two classes with labels

## Step 3: Map Layer node and view-node rule

- [ ] `param/layer` with `data: [Raster, Vector]`, colormap, color, opacity,
      bands, name; `style` saved on the node; its window for unwired values;
      `field` for vectors
- [ ] MapLayer built by the server; style values from Params nodes, or from
      a component's cache entry
- [ ] `compute_keys` branch for Map Layer; value sent with `put_value`
- [ ] Solver: no out-of-date along wires into Map Layer style inputs; Map
      Layer and Map Viewer are view nodes (not in run plans, not counted in
      the banner, `done` when their sources are)
- [ ] Display tab with Style and Map groups; Map Viewer moved there
      (`_layout.yaml`)

**Done when** (pytest + Playwright):
- a Map Layer fed by Read Raster and a Colormap node is `done` as soon as
  Read Raster is, without a worker run; its port key changes when the
  Colormap changes, and the banner count does not
- changing the Colormap marks only the Colormap node out of date, not Read
  Raster's downstream components
- Panel on the Layer shows name, source and style

## Step 4: Map Viewer with Layers

- [ ] `layers: [Raster, Vector, Layer]` list input; list wires give one
      layer per element (`<id>.<port>[i]`, key pattern extended)
- [ ] Locked style fields with "from Map Layer …", Go to Map Layer
- [ ] Live redraw when a Map Layer or Colormap changes (`map_changed` event,
      no Run)
- [ ] Vector colour by field (MapLibre `match` / `interpolate`)
- [ ] Legends for continuous, classes and vector colours

**Done when** (Playwright, synthetic example):
- two layers (classed raster via Map Layer, sample points raw) show in the
  right order; the raster legend lists the class labels
- changing a class colour in the Colormap editor recolours the open map
  without any node running (no `started` WebSocket event)
- the clicked-pixel test in `e2e/map.spec.ts` still passes

## Step 5: Examples, docs, merge

- [ ] `examples/synthetic/imd.geoknit` and `examples/milan_imd/` get a Map
      Viewer with a Map Layer and an IMD class Colormap. Neither example has
      a Map Viewer today, so this adds one, kept off the metrics path.
- [ ] Milan walkthrough screenshots updated (`npm run screenshots`, light
      and dark from change 02)
- [ ] Export comments for Map Layer
- [ ] Merge this SPEC into `docs/SPEC.md`; mark change 03 done

**Done when:**
- `geoknit run` prints the same metrics on the examples, and the export
  equivalence test still passes
- save → load → save byte-identical with Map Layers and Colormaps
