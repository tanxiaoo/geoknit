# geoknit: component
# name: Stratified Sample
# category: Sampling
# group: Draw
# icon: gis:layers-poi
# description: Draw the same number of random points per class, at pixel centres inside the AOI.
# inputs:
#   classes: Raster
#   value: Raster
#   aoi: Vector
#   n: Number
#   seed: Number
# outputs:
#   points: Vector
# requires: [numpy, geopandas]

# --- settings ---
value_field = "value"
class_field = "cls"

# --- code ---
# Reads one band of the class and value rasters inside the AOI's bounding
# box: sampling has to look at every pixel there.
import warnings

import geopandas as gpd
import numpy as np
from rasterio.features import geometry_mask

from geoknit.helpers import invalid_mask, nodata_value

same_grid = (
    classes.sizes["x"] == value.sizes["x"]
    and classes.sizes["y"] == value.sizes["y"]
    and classes.rio.transform() == value.rio.transform()
)
if not same_grid:
    raise ValueError("classes and value must be on the same grid; use Align Raster first")
crs = classes.rio.crs
shapes = aoi.to_crs(crs).geometry if aoi.crs is not None and crs is not None else aoi.geometry
c = classes.isel(band=0).rio.clip_box(*shapes.total_bounds)
v = value.isel(band=0).rio.clip_box(*shapes.total_bounds)
inside = ~geometry_mask(shapes, out_shape=c.shape, transform=c.rio.transform())
c_vals, v_vals = c.values, v.values
ok = inside & ~invalid_mask(c_vals, nodata_value(classes))
ok &= ~invalid_mask(v_vals, nodata_value(value))

rng = np.random.default_rng(int(seed))
n_per_class = int(n)
chosen_parts = []
for cls in np.unique(c_vals[ok]):
    idx = np.flatnonzero(ok & (c_vals == cls))
    if len(idx) < n_per_class:
        warnings.warn(f"class {cls:g} has only {len(idx)} pixels; taking all of them")
    chosen_parts.append(rng.choice(idx, size=min(n_per_class, len(idx)), replace=False))
chosen = np.concatenate(chosen_parts) if chosen_parts else np.array([], dtype="int64")
rows, cols = np.unravel_index(chosen, c_vals.shape)
cls_values = c_vals[rows, cols]
if np.issubdtype(cls_values.dtype, np.floating) and np.all(cls_values == np.round(cls_values)):
    cls_values = cls_values.astype("int64")
points = gpd.GeoDataFrame(
    {class_field: cls_values, value_field: v_vals[rows, cols].astype("float64")},
    geometry=gpd.points_from_xy(c.x.values[cols], c.y.values[rows]),  # pixel centres
    crs=crs,
)
counts = points[class_field].value_counts().sort_index()
shown = ", ".join(f"{k}: {count}" for k, count in counts.items())
print(f"{len(points)} points in {len(counts)} classes ({shown})")
