# geoknit: component
# name: Read Raster
# category: Raster
# icon: read-raster
# description: Open a raster file (e.g. a GeoTIFF) lazily; pixels are read only when needed.
# inputs:
#   path: Text
# outputs:
#   raster: Raster
# requires: [rioxarray]

# --- settings ---
bands = "all"  # "all", or numbers / names such as 1,2,3 or A00,A01
masked = True  # options: True | False

# --- code ---
import rioxarray

from geoknit.helpers import RASTER_CHUNKS, raster_band_names, select_bands

raster = rioxarray.open_rasterio(path, chunks=dict(RASTER_CHUNKS), masked=masked)
if str(bands).strip().lower() != "all":
    raster = select_bands(raster, bands)
names = raster_band_names(raster)
print(f"{len(names)} band(s), {raster.sizes['x']} × {raster.sizes['y']} px")
