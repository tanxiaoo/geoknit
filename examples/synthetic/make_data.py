"""Create the small synthetic dataset used by tests, CI and `imd.geoknit`.

Everything is EPSG:32632 at 10 m and generated from a fixed seed, so the
files (and the metrics of the example workflow) are the same on every run:

- ``imd.tif``: 1 band, float32, imperviousness 0–100 %, nodata 255. A smooth
  field plus noise; clipping makes some pixels exactly 0 and 100. A block in
  the top-left corner is nodata.
- ``predictors.tif``: 8 bands named A00…A07 (band descriptions), float32,
  nodata NaN, each a different noisy function of the IMD field, so a model can
  learn IMD from them. Same nodata block.
- ``aoi.gpkg``: one polygon inside the rasters (layer ``aoi``).
- ``reference.gpkg``: 150 random points inside the AOI with ``imd_ref`` (the
  IMD at the point plus a little noise) and ``stratum`` (``IMD_Class_1``…).

Run ``python examples/synthetic/make_data.py`` to write them to
``examples/synthetic/data/`` (git-ignored).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

CRS = "EPSG:32632"
SIZE = 200
RES = 10.0
X0, Y0 = 510_000.0, 5_040_000.0  # top-left corner
BAND_NAMES = [f"A{i:02d}" for i in range(8)]
NODATA_BLOCK = (slice(0, 20), slice(0, 20))
"""Rows and columns that are nodata in both rasters."""
IMD_NODATA = 255.0
N_REFERENCE = 150


def _smooth_field(rng: np.random.Generator, size: int) -> np.ndarray:
    """A sum of Gaussian blobs scaled to roughly -15…115, so clipping makes 0 and 100."""
    yy, xx = np.mgrid[0:size, 0:size].astype("float64")
    field = np.zeros((size, size))
    for _ in range(12):
        cy, cx = rng.uniform(0, size, 2)
        sigma = rng.uniform(15, 45)
        weight = rng.uniform(-1, 1.5)
        field += weight * np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma**2))
    field = (field - field.min()) / (field.max() - field.min())
    return field * 130 - 15


def make_data(out_dir: Path, seed: int = 0) -> dict[str, Path]:
    """Write the four synthetic files into ``out_dir``; return their paths by name."""
    import geopandas as gpd
    import rasterio
    from rasterio.transform import from_origin
    from shapely.geometry import Point, Polygon

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    transform = from_origin(X0, Y0, RES, RES)
    profile = {
        "driver": "GTiff",
        "width": SIZE,
        "height": SIZE,
        "dtype": "float32",
        "crs": CRS,
        "transform": transform,
        "tiled": True,
        "blockxsize": 64,
        "blockysize": 64,
        "compress": "deflate",
    }

    imd = np.clip(_smooth_field(rng, SIZE) + rng.normal(0, 4, (SIZE, SIZE)), 0, 100)
    imd = imd.astype("float32")
    valid = np.ones((SIZE, SIZE), dtype=bool)
    valid[NODATA_BLOCK] = False

    paths = {
        "imd": out_dir / "imd.tif",
        "predictors": out_dir / "predictors.tif",
        "aoi": out_dir / "aoi.gpkg",
        "reference": out_dir / "reference.gpkg",
    }
    with rasterio.open(paths["imd"], "w", count=1, nodata=IMD_NODATA, **profile) as ds:
        ds.write(np.where(valid, imd, IMD_NODATA).astype("float32"), 1)
        ds.set_band_description(1, "IMD")

    x = imd / 100.0
    bands = []
    for i in range(len(BAND_NAMES)):
        a, b, c = rng.uniform(-1, 1, 3)
        band = a * x + b * x**2 + c * np.sin(3 * x + i) + rng.normal(0, 0.05, x.shape)
        bands.append(np.where(valid, band, np.nan).astype("float32"))
    with rasterio.open(
        paths["predictors"], "w", count=len(BAND_NAMES), nodata=float("nan"), **profile
    ) as ds:
        ds.write(np.stack(bands))
        for i, name in enumerate(BAND_NAMES, start=1):
            ds.set_band_description(i, name)

    # AOI: an irregular polygon 5 px inside the raster edge (it overlaps the nodata block).
    m = 5 * RES
    left, top, right, bottom = X0 + m, Y0 - m, X0 + SIZE * RES - m, Y0 - SIZE * RES + m
    aoi = Polygon(
        [
            (left, top),
            (right - 300, top),
            (right, top - 300),
            (right, bottom),
            (left + 400, bottom),
            (left, bottom + 400),
        ]
    )
    gpd.GeoDataFrame({"name": ["synthetic aoi"]}, geometry=[aoi], crs=CRS).to_file(
        paths["aoi"], layer="aoi", driver="GPKG"
    )

    points, refs = [], []
    minx, miny, maxx, maxy = aoi.bounds
    while len(points) < N_REFERENCE:
        px, py = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if not aoi.contains(Point(px, py)):
            continue
        row, col = int((Y0 - py) // RES), int((px - X0) // RES)
        if not valid[row, col]:
            continue
        points.append(Point(px, py))
        refs.append(float(np.clip(imd[row, col] + rng.normal(0, 3), 0, 100)))
    ref = np.round(np.array(refs), 1)
    stratum = [f"IMD_Class_{min(int(v // 20), 4) + 1}" for v in ref]
    gpd.GeoDataFrame(
        {"PLOTID": [f"P{i:03d}" for i in range(1, N_REFERENCE + 1)], "stratum": stratum,
         "imd_ref": ref},
        geometry=points,
        crs=CRS,
    ).to_file(paths["reference"], layer="reference", driver="GPKG")  # fmt: skip
    return paths


if __name__ == "__main__":
    from geoknit.runtime.geoenv import use_bundled_geo_data

    use_bundled_geo_data()  # ignore a system PROJ_LIB (e.g. from PostGIS)
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "data"
    for name, path in make_data(target).items():
        print(f"{name}: {path}")
