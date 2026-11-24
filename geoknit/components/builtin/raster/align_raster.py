# geoknit: component
# name: Align Raster
# category: Raster
# icon: align
# description: Resample a raster onto the grid (CRS, resolution, extent) of a reference raster.
# inputs:
#   source: Raster
#   reference: Raster
# outputs:
#   raster: Raster
# requires: [rioxarray]

# --- settings ---
resampling = "nearest"  # options: nearest | bilinear | cubic | average | mode

# --- code ---
# Note: reprojecting reads the whole source raster into memory.
from rasterio.enums import Resampling

from geoknit.helpers import raster_band_names

raster = source.rio.reproject_match(reference, resampling=Resampling[resampling])
raster.attrs["long_name"] = tuple(raster_band_names(source))
print(f"aligned to {reference.sizes['x']} × {reference.sizes['y']} px, {reference.rio.crs}")
