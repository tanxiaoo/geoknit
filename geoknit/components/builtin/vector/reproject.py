# geoknit: component
# name: Reproject
# category: Vector
# icon: reproject
# description: Transform a vector layer to another CRS, e.g. EPSG:32632.
# inputs:
#   vector: Vector
#   crs: Text
# outputs:
#   reprojected: Vector
# requires: [geopandas, pyproj]

# --- code ---
if vector.crs is None:
    raise ValueError("the vector layer has no CRS, so it cannot be reprojected")
reprojected = vector.to_crs(crs)
print(f"{vector.crs.to_string()} → {reprojected.crs.to_string()}")
