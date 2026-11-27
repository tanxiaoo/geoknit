# geoknit: component
# name: Random Sample
# category: Sampling
# group: Draw
# icon: gis:multipoint
# description: Draw random points at the centres of valid (non-nodata) pixels inside the AOI.
# inputs:
#   raster: Raster
#   aoi: Vector
#   n: Number
#   seed: Number
# outputs:
#   points: Vector
# requires: [numpy, geopandas]

# --- code ---
# Validity is judged on the first band, inside the AOI's bounding box.
import warnings

import geopandas as gpd
import numpy as np
from rasterio.features import geometry_mask

from geoknit.helpers import invalid_mask, nodata_value

crs = raster.rio.crs
shapes = aoi.to_crs(crs).geometry if aoi.crs is not None and crs is not None else aoi.geometry
b = raster.isel(band=0).rio.clip_box(*shapes.total_bounds)
inside = ~geometry_mask(shapes, out_shape=b.shape, transform=b.rio.transform())
ok = np.flatnonzero(inside & ~invalid_mask(b.values, nodata_value(raster)))
wanted = int(n)
if len(ok) < wanted:
    warnings.warn(f"only {len(ok)} valid pixels; taking all of them")
chosen = np.random.default_rng(int(seed)).choice(ok, size=min(wanted, len(ok)), replace=False)
rows, cols = np.unravel_index(chosen, b.shape)
points = gpd.GeoDataFrame(
    {"id": np.arange(1, len(chosen) + 1)},
    geometry=gpd.points_from_xy(b.x.values[cols], b.y.values[rows]),
    crs=crs,
)
print(f"{len(points)} points")
