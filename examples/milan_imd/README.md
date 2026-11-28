# Milan imperviousness (IMD 2018)

This workflow maps imperviousness (0–100 %) over Milan with AlphaEarth embeddings.
It draws stratified sample points from the CLMS IMD 2018 layer and splits them
into training and test points. A random forest is trained on the training points,
and the predicted map is validated on the held-out test points.

```
Read Raster (CLMS IMD) ─┬─ Reclassify ─┐
                        └──────────────┴─ Stratified Sample ─ Split Points ─┬─ train ─ Extract Values ─ Random Forest
Read Vector (AOI) ─────────────────────────┘                                │                               │
Read Raster (AlphaEarth) ───────────────────────────────────────────────────┼───── Predict Raster ──────────┤
                                                                            │        ├─ Write Raster (outputs/imd_rf.tif)
                                                                            └─ test ─┴─ Regression Accuracy ─ Panel

Reclassify ─ Map Layer "IMD classes" ← Colormap (7 classes) ─┐
Split Points (test) ─────────────────────────────────────────┴─ Map Viewer
```

The Map Viewer only shows results: it never runs and does not change the metrics.

## 1. Copy the data

The data is not in the repository. Copy these three files into
`examples/milan_imd/data/` (the folder is git-ignored):

| File | Content |
|------|---------|
| `CLMS_2018_Milan_UTM32N.tif` | 1 band, CLMS IMD 2018 in %, float32, nodata 255 |
| `aoi_milan.gpkg` | one polygon, layer `milano_city_rect_UTM32N` |
| `AlphaEarth_2018_Milan_UTM32N.tif` | 64 bands, float32, nodata NaN, band descriptions `A00` … `A63` |

All rasters must be in **EPSG:32632** (UTM 32N) at 10 m. The band
descriptions of the AlphaEarth file must be `A00` … `A63`, because the model's
features are named after them. The AlphaEarth GeoTIFF is exported from Earth
Engine once, outside GeoKnit.

## 2. Run

```bash
geoknit run examples/milan_imd/milan_imd.geoknit
```

The metrics table (n, RMSE, MAE, R², bias) is printed under `--- Panel n22 ---`.
The predicted map is written to `examples/milan_imd/outputs/imd_rf.tif`. The
first run takes about a minute; later runs use the cache in
`examples/milan_imd/.geoknit/` and only recompute what you change.

## How it validates

Stratified Sample draws the same number of points from each IMD class inside
the AOI and stores each point's CLMS value in the field `IMD`. Split Points
keeps 30 % of them as test points, stratified by class. The training points
go to Extract Values and the Random Forest. Regression Accuracy compares the
predicted map at each test point with its `IMD`. The test points are never used for training.

Settings you may want to change, as Slider and Text values in the workflow or in
the components' settings: points per class (100), seed (42), number of trees (300),
the breaks (`0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100`), and Split
Points' `test_fraction` (0.3).
