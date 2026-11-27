# geoknit: component
# name: Read Vector
# category: Vector
# group: Files
# icon: gis:polygon-pt
# description: Read a vector file (GeoPackage, Shapefile, GeoJSON, GeoParquet).
# inputs:
#   path: Text
# outputs:
#   vector: Vector
# requires: [geopandas, pyogrio]

# --- settings ---
layer = None  # layer name inside a GeoPackage; None = the first layer

# --- code ---
from pathlib import Path

import geopandas as gpd

if Path(path).suffix.lower() == ".parquet":
    vector = gpd.read_parquet(path)
else:
    vector = gpd.read_file(path, layer=layer or None, engine="pyogrio")
print(f"{len(vector)} features, CRS {vector.crs.to_string() if vector.crs else 'none'}")
