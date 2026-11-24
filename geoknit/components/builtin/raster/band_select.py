# geoknit: component
# name: Band Select
# category: Raster
# icon: bands
# description: Keep some bands of a raster, by number (1,2,3) or by name (A00,A05).
# inputs:
#   raster: Raster
#   bands: Text
# outputs:
#   selected: Raster

# --- code ---
from geoknit.helpers import raster_band_names, select_bands

selected = select_bands(raster, bands)
print("bands: " + ", ".join(raster_band_names(selected)))
