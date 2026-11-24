"""Read raster values at point locations without loading the raster.

Used by Extract Values, Accuracy and Confusion Matrix. A point takes the value
of the pixel it falls in (nearest pixel centre). Only the chunks that hold
points are read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geoknit.helpers.raster import invalid_mask, nodata_value


@dataclass
class PointValues:
    """Values of every band at every point."""

    values: Any
    """``(n_points, n_bands)`` float array; NaN outside the raster or on nodata."""
    outside: Any
    """Bool per point: the point is outside the raster."""
    nodata: Any
    """Bool per point: inside, but at least one band is nodata there."""

    @property
    def valid(self) -> Any:
        return ~(self.outside | self.nodata)


def pixel_of(raster: Any, xs: Any, ys: Any) -> tuple[Any, Any, Any]:
    """``(rows, cols, inside)`` of the pixels holding the points ``xs, ys``."""
    import numpy as np
    import rioxarray  # noqa: F401  (registers .rio)

    inv = ~raster.rio.transform()
    cols_f, rows_f = inv * (np.asarray(xs, dtype="float64"), np.asarray(ys, dtype="float64"))
    rows = np.floor(rows_f).astype("int64")
    cols = np.floor(cols_f).astype("int64")
    height, width = int(raster.sizes["y"]), int(raster.sizes["x"])
    inside = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)
    return rows, cols, inside


def values_at_points(raster: Any, points: Any) -> PointValues:
    """Sample every band of ``raster`` at the points of a GeoDataFrame."""
    import numpy as np
    import xarray as xr

    if raster.rio.crs is not None and points.crs is not None and points.crs != raster.rio.crs:
        points = points.to_crs(raster.rio.crs)
    geom = points.geometry
    if len(geom) and not (geom.geom_type == "Point").all():
        geom = geom.representative_point()
    xs, ys = geom.x.to_numpy(), geom.y.to_numpy()
    rows, cols, inside = pixel_of(raster, xs, ys)
    n_bands = int(raster.sizes.get("band", 1))
    values = np.full((len(xs), n_bands), np.nan, dtype="float64")
    nodata = np.zeros(len(xs), dtype=bool)
    if inside.any():
        picked = raster.isel(
            y=xr.DataArray(rows[inside], dims="point"),
            x=xr.DataArray(cols[inside], dims="point"),
        )
        if "band" not in picked.dims:
            picked = picked.expand_dims("band")
        raw = np.asarray(picked.transpose("point", "band").values)
        bad = invalid_mask(raw, nodata_value(raster)).any(axis=1)
        values[inside] = raw.astype("float64")
        values[np.flatnonzero(inside)[bad]] = np.nan
        nodata[np.flatnonzero(inside)[bad]] = True
    return PointValues(values=values, outside=~inside, nodata=nodata)
