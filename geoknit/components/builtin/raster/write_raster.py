# geoknit: component
# name: Write Raster
# category: Raster
# icon: write-raster
# description: Save a raster as a Cloud Optimized GeoTIFF; band names become band descriptions.
# inputs:
#   map: Raster
#   path: {type: Text, file: write}
# outputs:
#   file: Text
# requires: [rioxarray]

# --- settings ---
compress = "deflate"  # options: deflate | lzw | zstd | none

# --- code ---
from geoknit.helpers import write_cog

written = write_cog(map, path, compress=compress)
file = str(path)
print(f"wrote {written.name} ({written.stat().st_size / 1e6:.1f} MB)")
