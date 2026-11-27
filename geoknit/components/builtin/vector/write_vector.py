# geoknit: component
# name: Write Vector
# category: Vector
# group: Files
# icon: gis:layer-download
# description: Save a vector layer; the extension picks the format (.gpkg .shp .geojson .parquet).
# inputs:
#   vector: Vector
#   path: {type: Text, file: write}
# outputs:
#   file: Text
# requires: [geopandas, pyogrio]

# --- settings ---
layer = None  # layer name for a GeoPackage; None = the file name

# --- code ---
from pathlib import Path

drivers = {".gpkg": "GPKG", ".shp": "ESRI Shapefile", ".geojson": "GeoJSON", ".json": "GeoJSON"}
target = Path(path)
suffix = target.suffix.lower()
if suffix != ".parquet" and suffix not in drivers:
    raise ValueError(
        f'cannot tell the format from "{target.name}"; use .gpkg, .shp, .geojson or .parquet'
    )
target.parent.mkdir(parents=True, exist_ok=True)
if suffix == ".parquet":
    vector.to_parquet(target)
else:
    if target.exists():
        target.unlink()  # replace the file instead of adding a layer to it
    vector.to_file(target, driver=drivers[suffix], layer=layer or target.stem, engine="pyogrio")
file = str(path)
print(f"wrote {len(vector)} features to {target.name}")
