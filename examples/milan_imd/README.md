# Milan imperviousness (IMD 2018)

This workflow maps imperviousness (0–100 %) over Milan with AlphaEarth embeddings.
It samples training points from the CLMS IMD 2018 layer, trains a random forest
and checks the map against the EarthLabel reference plots.

```
Read Raster (CLMS IMD) ─┬─ Reclassify ─┐
                        └──────────────┴─ Stratified Sample ─ Extract Values ─ Random Forest
Read Vector (AOI) ─────────────────────────┘                  │                     │
Read Raster (AlphaEarth) ─────────────────────────────────────┴─── Predict Raster ──┤
                                                                     ├─ Write Raster (outputs/imd_rf.tif)
Read Vector (EarthLabel) ─────────────────────────────────────────── Accuracy ─ Panel
```

## 1. Copy the data

The data is not in the repository. Copy these four files into
`examples/milan_imd/data/` (the folder is git-ignored):

| File | Content |
|------|---------|
| `CLMS_2018_Milan_UTM32N.tif` | 1 band, CLMS IMD 2018 in %, float32, nodata 255 |
| `aoi_milan.gpkg` | one polygon, layer `milano_city_rect_UTM32N` |
| `AlphaEarth_2018_Milan_UTM32N.tif` | 64 bands, float32, nodata NaN, band descriptions `A00` … `A63` |
| `milan_imd_2018_results_cells.csv` | 450 EarthLabel plots: `PLOTID`, `LAT`/`LON` (WGS84), `ref_label`, `cells_json` |

All rasters must be in **EPSG:32632** (UTM 32N) at 10 m. The band
descriptions of the AlphaEarth file must be `A00` … `A63`, because the model's
features are named after them. The AlphaEarth GeoTIFF is exported from Earth
Engine once, outside GeoKnit.

## 2. Make the reference points

```bash
python examples/milan_imd/prepare_reference.py
```

This writes `data/earthlabel_2018.gpkg`: one point per plot in EPSG:32632 with
`PLOTID`, `stratum` (from `ref_label`) and `imd_ref`. `imd_ref` is the
impervious share in % of the plot's resolvable sub-cells: sub-cells labelled
"Impervious …" count as impervious, "Pervious …" as not, and any other label
is left out.

## 3. Run

```bash
geoknit run examples/milan_imd/milan_imd.geoknit
```

The metrics table (n, RMSE, MAE, R², bias) is printed under `--- Panel n23 ---`.
The predicted map is written to `examples/milan_imd/outputs/imd_rf.tif`. The
first run takes about a minute; later runs use the cache in
`examples/milan_imd/.geoknit/` and only recompute what you change.

Settings you may want to change, as Slider and Text values in the workflow:
points per class (100), seed (42), number of trees (300) and the breaks
(`0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100`).

Only reference plots inside the AlphaEarth raster are used for validation. The
others are dropped, and Accuracy counts them under `dropped`. With the city
rectangle that is 29 of the 450 plots, because the plots cover the whole CLMS
extent.
