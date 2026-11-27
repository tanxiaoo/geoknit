# geoknit: component
# name: Extract Values
# category: Sampling
# group: Extract
# icon: gis:poi-info
# description: Read all bands of a raster at each point (one column per band, attributes kept).
# inputs:
#   points: Vector
#   raster: Raster
# outputs:
#   table: Table
# requires: [pandas]

# --- code ---
# Columns are named after the band descriptions (else b01, b02, …). Only the
# raster windows that hold points are read.
import warnings

import pandas as pd

from geoknit.helpers import raster_band_names, values_at_points

names = raster_band_names(raster)
clash = [name for name in names if name in points.columns]
if clash:
    raise ValueError(f"the points already have columns named like bands: {', '.join(clash)}")
sampled = values_at_points(raster, points)
attributes = pd.DataFrame(points.drop(columns=points.geometry.name)).reset_index(drop=True)
table = pd.concat([attributes, pd.DataFrame(sampled.values, columns=names)], axis=1)
if not sampled.valid.all():
    warnings.warn(
        f"dropped {int(sampled.outside.sum())} points outside the raster and "
        f"{int(sampled.nodata.sum())} on nodata"
    )
table = table[sampled.valid].reset_index(drop=True)
table.attrs["feature_columns"] = list(names)
print(f"{len(table)} rows × {len(names)} band columns")
