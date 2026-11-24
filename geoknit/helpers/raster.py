"""Raster utilities shared by the built-in components.

Everything here keeps rasters lazy: band selection and masks work on the
dask-backed array, and ``write_cog`` writes window by window.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from geoknit.core.cache import RASTER_CHUNKS
from geoknit.core.types import raster_band_names

__all__ = [
    "RASTER_CHUNKS",
    "band_indices",
    "invalid_mask",
    "nodata_value",
    "raster_band_names",
    "select_bands",
    "write_cog",
]


def band_indices(raster: Any, bands: str | list[Any]) -> list[int]:
    """0-based indices for ``"1,2,3"``, ``"A00,A05"`` or a list of numbers or names.

    Raises ``ValueError`` naming every band that is not in the raster.
    """
    names = raster_band_names(raster)
    items = [b.strip() for b in bands.split(",")] if isinstance(bands, str) else list(bands)
    items = [b for b in items if b != ""]
    if not items:
        raise ValueError("no bands given; write numbers like 1,2,3 or names like A00,A01")
    out: list[int] = []
    missing: list[str] = []
    for item in items:
        text = str(item)
        if text in names:
            out.append(names.index(text))
        elif text.isdigit() and 1 <= int(text) <= len(names):
            out.append(int(text) - 1)
        else:
            missing.append(text)
    if missing:
        raise ValueError(
            f"the raster has no band {', '.join(missing)} (it has {len(names)}: {', '.join(names)})"
        )
    return out


def select_bands(raster: Any, bands: str | list[Any]) -> Any:
    """The chosen bands, in the given order, with their names kept."""
    idx = band_indices(raster, bands)
    names = raster_band_names(raster)
    out = raster.isel(band=idx)
    out = out.assign_coords(band=list(range(1, len(idx) + 1)))
    out.attrs["long_name"] = tuple(names[i] for i in idx)
    return out


def nodata_value(raster: Any) -> Any:
    """The nodata value still present in the data (``None`` when masked to NaN)."""
    import rioxarray  # noqa: F401  (registers .rio)

    if raster.rio.encoded_nodata is not None:
        return None  # masked=True: nodata already became NaN
    return raster.rio.nodata


def invalid_mask(values: Any, nodata: Any) -> Any:
    """True where ``values`` is NaN or equal to ``nodata``."""
    import numpy as np

    v = np.asarray(values)
    bad = np.isnan(v) if np.issubdtype(v.dtype, np.floating) else np.zeros(v.shape, dtype=bool)
    if nodata is not None and not (isinstance(nodata, float) and np.isnan(nodata)):
        bad = bad | (v == nodata)
    return bad


def write_cog(raster: Any, path: str | Path, compress: str = "deflate") -> Path:
    """Write ``raster`` as a Cloud Optimized GeoTIFF, window by window.

    A tiled GeoTIFF is written first (so a lazy raster is computed one window
    at a time), then copied to a COG with overviews. Band names become band
    descriptions.
    """
    import threading

    import rasterio.shutil
    import rioxarray  # noqa: F401  (registers .rio)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.tmp{path.suffix or '.tif'}")
    method = "NONE" if compress.lower() == "none" else compress.upper()
    out = raster.copy()
    out.attrs["long_name"] = tuple(raster_band_names(raster))
    chunked = hasattr(raster.data, "dask")
    try:
        out.rio.to_raster(
            tmp,
            driver="GTiff",
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress=method,
            lock=threading.Lock() if chunked else None,
        )
        rasterio.shutil.copy(tmp, path, driver="COG", COMPRESS=method)
    finally:
        tmp.unlink(missing_ok=True)
    return path
