"""Shared test setup."""

import os

# A system PROJ/GDAL install (e.g. PostGIS) can point these at old data files
# that the rasterio/pyproj wheels cannot use; the wheels ship their own.
for _var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
    os.environ.pop(_var, None)
