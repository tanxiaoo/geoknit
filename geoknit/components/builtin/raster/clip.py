# geoknit: component
# name: Clip
# category: Raster
# group: Extent
# icon: gis:select-extent
# description: Cut a raster to the extent of polygons; pixels outside them become nodata.
# inputs:
#   raster: Raster
#   aoi: Vector
# outputs:
#   clipped: Raster
# requires: [rioxarray]

# --- settings ---
all_touched = False  # options: True | False

# --- code ---
from geoknit.helpers import raster_band_names

shapes = aoi.to_crs(raster.rio.crs).geometry if aoi.crs is not None else aoi.geometry
clipped = raster.rio.clip(shapes, all_touched=all_touched, drop=True)
clipped.attrs["long_name"] = tuple(raster_band_names(raster))
print(f"{clipped.sizes['x']} × {clipped.sizes['y']} px after clipping")
