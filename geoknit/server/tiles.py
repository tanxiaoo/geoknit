"""Map Viewer data (SPEC 8, 9): layer descriptions, raster tiles, GeoJSON, inspect.

Everything is read from the disk cache by port key (``<node key>.<port>``, or
``<node key>.<port>[i]`` for element ``i`` of a list output, change 03):
a raster is the cached COG, or the source file a ``.ref.json`` names; a vector
is the cached GeoParquet. Cache entries never change under a key, so
descriptions and statistics are memoised by key.

Tiles come from overviews, never from full-resolution reads of a whole raster.
Cached COGs carry overviews already. A source file without overviews (a
raster straight from Read Raster) gets a VRT with external overviews built
inside its cache entry the first time it is viewed; the user's file is never
touched.

Open rasters are kept in a small pool between tile requests: GDAL's block
cache belongs to an open dataset, and neighbouring tiles share blocks. On
Windows an open file cannot be replaced or deleted, so the pool closes files
idle for ``POOL_IDLE`` seconds, and all of them when a run starts or the cache
is cleared (``release_files``).

This is the one server module that imports the geo stack (lazily, the first
time a map is opened).
"""

from __future__ import annotations

import contextlib
import functools
import json
import re
import threading
import time
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from geoknit.core import types
from geoknit.core.cache import CacheMiss, DiskCache
from geoknit.runtime.geoenv import use_bundled_geo_data

use_bundled_geo_data()  # before rasterio builds a CRS: a system PROJ_LIB breaks it

TILE_SIZE = 256
SAMPLE_SIZE = 1024
"""Longest side of the decimated read used for statistics (comes from overviews)."""
OVERVIEW_MIN = 1024
"""Rasters larger than this (px, either side) need overviews to be viewed smoothly."""
MAX_FEATURES = 50_000
CATEGORICAL_MAX = 32
"""An integer band with at most this many distinct values is shown as classes."""

CATEGORICAL = "categorical"
COLORMAPS = (
    "viridis",
    "magma",
    "plasma",
    "cividis",
    "turbo",
    "greys_r",
    "terrain",
    "rdylgn",
    "spectral",
    "blues",
)
# "auto" follows the UI theme (light or dark) and is the default (SPEC 8)
BASEMAPS = ("auto", "light", "dark", "none")
DEFAULT_BASEMAP = "auto"
PALETTE = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
    "#aec7e8",
    "#ffbb78",
    "#98df8a",
    "#ff9896",
    "#c5b0d5",
    "#c49c94",
    "#f7b6d2",
    "#c7c7c7",
    "#dbdb8d",
    "#9edae5",
)
"""Class colours; a class value always gets ``PALETTE[value % len(PALETTE)]``."""

POOL_IDLE = 20.0
"""Seconds an unused raster stays open for the next tile."""

_KEY = re.compile(r"^[0-9a-f]{64}\.[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?$")
"""A port key, or ``<port key>[i]`` for element ``i`` of a list output (change 03)."""
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class MapError(Exception):
    """A request the Map Viewer cannot answer; ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def check_key(key: str) -> str:
    if not _KEY.match(key):
        raise MapError(f'"{key}" is not a port key', 404)
    return key


def class_color(value: int) -> str:
    return PALETTE[int(value) % len(PALETTE)]


# ── map settings saved in the workflow (node.extra["map"]) ──


def _style_error(layer: str, message: str) -> MapError:
    return MapError(f"layer {layer}: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_style(layer: str, style: Any) -> dict[str, Any]:
    if not isinstance(style, dict):
        raise _style_error(layer, "a style is an object")
    out: dict[str, Any] = {}
    for name, value in style.items():
        if name == "colormap":
            if isinstance(value, dict):  # a Colormap (change 03), saved in its normal form
                try:
                    value = types.Colormap.from_json(value).to_json()
                except (ValueError, TypeError) as exc:
                    raise _style_error(layer, f"colormap: {exc}") from None
            elif value not in (*COLORMAPS, CATEGORICAL):
                raise _style_error(layer, f'unknown colormap "{value}"')
        elif name == "bands":
            if (
                not isinstance(value, list)
                or len(value) not in (1, 3)
                or not all(isinstance(b, int) and not isinstance(b, bool) and b >= 1 for b in value)
            ):
                raise _style_error(layer, "bands is a list of 1 or 3 band numbers (from 1)")
        elif name in ("min", "max"):
            if value is not None and not _is_number(value):
                raise _style_error(layer, f"{name} is a number or null")
        elif name == "opacity":
            if not _is_number(value) or not 0 <= value <= 1:
                raise _style_error(layer, "opacity is between 0 and 1")
        elif name == "visible":
            if not isinstance(value, bool):
                raise _style_error(layer, "visible is true or false")
        elif name == "color":
            if not isinstance(value, str) or not _HEX.match(value):
                raise _style_error(layer, "color is #rrggbb")
        else:
            raise _style_error(layer, f'unknown style field "{name}"')
        out[name] = value
    return out


def merge_settings(current: dict[str, Any] | None, change: dict[str, Any]) -> dict[str, Any]:
    """Apply a ``map`` patch: ``basemap`` and per-layer ``styles`` (``null`` resets one)."""
    merged = json.loads(json.dumps(current or {}))
    unknown = set(change) - {"basemap", "styles"}
    if unknown:
        raise MapError(f"unknown map field {sorted(unknown)[0]}")
    if "basemap" in change:
        if change["basemap"] not in BASEMAPS:
            raise MapError(f"basemap is one of {', '.join(BASEMAPS)}")
        merged["basemap"] = change["basemap"]
    styles = change.get("styles") or {}
    if not isinstance(styles, dict):
        raise MapError("styles maps a layer id to a style")
    saved = merged.setdefault("styles", {})
    for layer, style in styles.items():
        if style is None:
            saved.pop(layer, None)
        else:
            saved[layer] = {**saved.get(layer, {}), **_check_style(layer, style)}
    if not saved:
        merged.pop("styles")
    return merged


# ── rasters ──


def raster_path(cache: DiskCache, key: str) -> Path:
    """The file to read tiles and statistics from (with overviews when it is large)."""
    return _raster_file(cache, key)[1]


def _raster_file(cache: DiskCache, key: str) -> tuple[Path, Path]:
    """``(cache entry folder, file with overviews)``: the cached COG, the source
    file, or a viewing VRT of the source (``viewable``)."""
    entry, info = cache.port_info(check_key(key))
    if info.get("type") != types.RASTER or info.get("access") == "list":
        raise MapError(f"{key} is not a raster", 404)
    if info["format"] == "cog":
        return entry, entry / info["file"]
    ref = json.loads((entry / info["file"]).read_text(encoding="utf-8"))
    src = Path(ref["path"])
    try:
        st = src.stat()
    except OSError:
        raise CacheMiss(f"{src} is gone") from None
    if (st.st_size, st.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
        raise CacheMiss(f"{src} has changed")
    return entry, viewable(entry, str(info["file"]).removesuffix(".ref.json"), src)


_build_locks: dict[Path, threading.Lock] = {}
_build_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _build_locks_guard:
        return _build_locks.setdefault(path, threading.Lock())


def viewable(entry: Path, port: str, src: Path) -> Path:
    """``src``, or a VRT of it with external overviews in the cache entry.

    The VRT and its ``.ovr`` are built under temporary names and renamed, so
    a crash never leaves a half-built overview behind.
    """
    import numpy as np
    import rasterio
    import rasterio.shutil
    from rasterio.enums import Resampling

    with rasterio.open(src) as ds:
        if ds.overviews(1) or max(ds.width, ds.height) <= OVERVIEW_MIN:
            return src
        integer = np.issubdtype(np.dtype(ds.dtypes[0]), np.integer)
        longest = max(ds.width, ds.height)
    vrt = entry / f"{port}.view.vrt"
    ovr = entry / f"{port}.view.vrt.ovr"
    with _lock_for(vrt):
        if vrt.is_file() and ovr.is_file():
            return vrt
        tmp = entry / f"{port}.view.tmp.vrt"
        tmp_ovr = entry / f"{port}.view.tmp.vrt.ovr"
        for f in (tmp, tmp_ovr, vrt, ovr):
            f.unlink(missing_ok=True)
        rasterio.shutil.copy(src, tmp, driver="VRT")
        factors = []
        f = 2
        while longest / f >= TILE_SIZE / 2:
            factors.append(f)
            f *= 2
        with (
            rasterio.Env(
                COMPRESS_OVERVIEW="DEFLATE",
                INTERLEAVE_OVERVIEW="BAND",  # tiles read one band (or three) at a time
                BIGTIFF_OVERVIEW="IF_SAFER",
            ),
            rasterio.open(tmp, "r+") as ds,
        ):
            ds.build_overviews(factors, Resampling.nearest if integer else Resampling.average)
        tmp_ovr.replace(ovr)
        tmp.replace(vrt)
    return vrt


_GDAL_TYPES = {
    "uint8": "Byte",
    "int8": "Int8",
    "uint16": "UInt16",
    "int16": "Int16",
    "uint32": "UInt32",
    "int32": "Int32",
    "uint64": "UInt64",
    "int64": "Int64",
    "float32": "Float32",
    "float64": "Float64",
}


def band_view(entry: Path, base: Path, bands: tuple[int, ...]) -> tuple[Path, tuple[int, ...]]:
    """``(file, band indexes in it)`` for drawing ``bands`` of ``base``.

    GDAL reprojects every band of the file it reads, even when one is asked
    for: a tile of a 64-band raster would warp 64 bands. A raster with more
    than three bands is therefore read through a small VRT of just the shown
    bands, written next to it in the cache entry; it keeps ``base``'s
    overviews (GDAL's implicit VRT overviews).
    """
    from xml.sax.saxutils import escape

    import rasterio

    with rasterio.open(base) as ds:
        if any(not 1 <= b <= ds.count for b in bands):
            raise MapError(f"the raster has {ds.count} bands")
        if ds.count <= 3:
            return base, bands
        width, height = ds.width, ds.height
        block_y, block_x = ds.block_shapes[0]
        gdal_type = _GDAL_TYPES.get(ds.dtypes[0])
        nodata = ds.nodata
        crs = ds.crs.to_wkt() if ds.crs else ""
        transform = ",".join(repr(v) for v in ds.transform.to_gdal())
    if gdal_type is None:
        return base, bands
    path = entry / f"{base.name}.bands-{'-'.join(map(str, bands))}.vrt"
    if path.is_file():
        return path, tuple(range(1, len(bands) + 1))
    nodata_xml = f"<NoDataValue>{nodata!r}</NoDataValue>" if nodata is not None else ""
    source = escape(str(base.resolve()))
    rect = f'xOff="0" yOff="0" xSize="{width}" ySize="{height}"'
    band_xml = "".join(
        f'<VRTRasterBand dataType="{gdal_type}" band="{i}">{nodata_xml}<SimpleSource>'
        f'<SourceFilename relativeToVRT="0">{source}</SourceFilename><SourceBand>{b}</SourceBand>'
        f'<SourceProperties RasterXSize="{width}" RasterYSize="{height}" DataType="{gdal_type}" '
        f'BlockXSize="{block_x}" BlockYSize="{block_y}"/>'
        f"<SrcRect {rect}/><DstRect {rect}/></SimpleSource></VRTRasterBand>"
        for i, b in enumerate(bands, start=1)
    )
    text = (
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">'
        f"<SRS>{escape(crs)}</SRS><GeoTransform>{transform}</GeoTransform>{band_xml}</VRTDataset>"
    )
    tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path, tuple(range(1, len(bands) + 1))


class _ReaderPool:
    """Open rio-tiler Readers by path; each is used by one request at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._idle: dict[str, list[tuple[Any, float]]] = {}
        self._generation = 0
        self._timer: threading.Timer | None = None

    @contextlib.contextmanager
    def reader(self, path: str) -> Iterator[Any]:
        from rio_tiler.io import Reader

        with self._lock:
            self._sweep(time.monotonic())
            idle = self._idle.get(path)
            reader = idle.pop()[0] if idle else None
            generation = self._generation
        if reader is None:
            import rasterio

            # Opened inside an Env, the dataset does not carry a thread-local Env of
            # its own, so the pool may close it from another thread (run start, timer).
            with rasterio.Env():
                dataset = rasterio.open(path)
            reader = Reader(path, dataset=dataset)
        try:
            yield reader
        finally:
            with self._lock:
                keep = generation == self._generation
                if keep:
                    self._idle.setdefault(path, []).append((reader, time.monotonic()))
                    self._schedule()
            if not keep:
                _close(reader)

    def _sweep(self, now: float) -> None:
        for path in list(self._idle):
            fresh = []
            for reader, used in self._idle[path]:
                if now - used > POOL_IDLE:
                    _close(reader)
                else:
                    fresh.append((reader, used))
            if fresh:
                self._idle[path] = fresh
            else:
                del self._idle[path]

    def _schedule(self) -> None:
        if self._timer is None:
            self._timer = threading.Timer(POOL_IDLE + 1, self._on_timer)
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
            self._sweep(time.monotonic())
            if self._idle:
                self._schedule()

    def close_all(self) -> int:
        """Close every idle reader; readers in use close when their request ends."""
        with self._lock:
            self._generation += 1
            readers = [r for items in self._idle.values() for r, _ in items]
            self._idle.clear()
        for reader in readers:
            _close(reader)
        return len(readers)

    @property
    def open_files(self) -> int:
        with self._lock:
            return sum(len(items) for items in self._idle.values())


def _close(reader: Any) -> None:
    reader.close()
    reader.dataset.close()


_pool = _ReaderPool()


def release_files() -> int:
    """Close the rasters kept open for tiles (before a run or a cache clear)."""
    return _pool.close_all()


def _version(path: Path | str) -> int:
    """Part of every memo key, so a source file changed in place is read again."""
    return Path(path).stat().st_mtime_ns


@functools.lru_cache(maxsize=256)
def _describe_raster(path: str, version: int) -> dict[str, Any]:
    import rasterio
    from rasterio.warp import transform_bounds

    with rasterio.open(path) as ds:
        if ds.crs is None:
            raise MapError("the raster has no CRS, so it cannot be placed on the map")
        west, south, east, north = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
        names = [d or f"band {i}" for i, d in enumerate(ds.descriptions, start=1)]
        return {
            "bands": names,
            "dtype": ds.dtypes[0],
            "width": ds.width,
            "height": ds.height,
            "nodata": ds.nodata,
            "crs": ds.crs.to_string(),
            "bounds": [west, south, east, north],
        }


@functools.lru_cache(maxsize=256)
def _stats(path: str, version: int, bands: tuple[int, ...]) -> dict[str, Any]:
    """2–98 % stretch of ``bands`` together, and classes for a small-integer band."""
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    with rasterio.open(path) as ds:
        bad = [b for b in bands if not 1 <= b <= ds.count]
        if bad:
            raise MapError(f"band {bad[0]} does not exist (the raster has {ds.count})")
        scale = min(1.0, SAMPLE_SIZE / max(ds.width, ds.height))
        shape = (len(bands), max(1, round(ds.height * scale)), max(1, round(ds.width * scale)))
        sample = ds.read(list(bands), out_shape=shape, masked=True, resampling=Resampling.nearest)
        integer = np.issubdtype(np.dtype(ds.dtypes[0]), np.integer)
    values = sample.compressed()
    if values.dtype.kind == "f":
        values = values[np.isfinite(values)]
    if values.size == 0:
        return {"min": 0.0, "max": 1.0, "classes": None}
    lo, hi = (float(v) for v in np.percentile(values, [2, 98]))
    if hi <= lo:
        lo, hi = float(values.min()), float(values.max())
        if hi <= lo:
            hi = lo + 1
    classes = None
    if integer and len(bands) == 1:
        unique = np.unique(values)
        if len(unique) <= CATEGORICAL_MAX:
            classes = [{"value": int(v), "color": class_color(int(v))} for v in unique]
    return {"min": lo, "max": hi, "classes": classes}


def raster_stats(cache: DiskCache, key: str, bands: tuple[int, ...]) -> dict[str, Any]:
    path = raster_path(cache, key)
    return _stats(str(path), _version(path), bands)


def default_style(desc: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    if len(desc["bands"]) == 3:
        bands, colormap = [1, 2, 3], "viridis"
    elif stats["classes"] is not None:
        bands, colormap = [1], CATEGORICAL
    else:
        bands, colormap = [1], "viridis"
    return {
        "bands": bands,
        "colormap": colormap,
        "min": stats["min"],
        "max": stats["max"],
        "opacity": 1.0,
        "visible": True,
    }


def describe_raster(cache: DiskCache, key: str) -> dict[str, Any]:
    """Metadata, statistics of the default bands, and the default style."""
    path = str(raster_path(cache, key))
    desc = dict(_describe_raster(path, _version(path)))
    default_bands = (1, 2, 3) if len(desc["bands"]) == 3 else (1,)
    stats = _stats(path, _version(path), default_bands)
    desc["stats"] = stats
    desc["default_style"] = default_style(desc, stats)
    return desc


@functools.lru_cache(maxsize=32)
def _lut(colormap: str) -> Any:
    import numpy as np
    from rio_tiler.colormap import cmap

    table = cmap.get(colormap)
    return np.array([table[i] for i in range(256)], dtype="uint8")


@functools.lru_cache(maxsize=1)
def _palette() -> Any:
    import numpy as np

    return np.array([[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in PALETTE], dtype="uint8")


def colormap_lut(cm: types.Colormap) -> Any:
    """``(256, 4)`` uint8 RGBA table of a continuous Colormap, low to high.

    A named ramp that was not customised is rio-tiler's table (``_lut``), so it
    draws exactly as the plain ``colormap=<name>`` does; its alpha is not used.
    Other ramps are interpolated linearly between their stops.
    """
    if cm.is_named and cm.name is not None:
        lut = _lut(cm.name)
    else:
        lut = _stops_lut(tuple((p, c.rgba) for p, c in cm.stops))
    return lut[::-1] if cm.reverse else lut


@functools.lru_cache(maxsize=64)
def _stops_lut(stops: tuple[tuple[float, tuple[int, int, int, int]], ...]) -> Any:
    import numpy as np

    positions = np.array([p for p, _ in stops], dtype="float64")
    colours = np.array([c for _, c in stops], dtype="float64")
    at = np.arange(256, dtype="float64") / 255
    channels = [np.interp(at, positions, colours[:, i]) for i in range(4)]
    return np.round(np.stack(channels, axis=-1)).astype("uint8")


def colormap_from_query(text: str) -> types.Colormap:
    """The ``cmap`` tile parameter: a Colormap as compact JSON."""
    try:
        return types.Colormap.from_json(json.loads(text))
    except (ValueError, TypeError) as exc:
        raise MapError(f"cmap: {exc}") from None


def _classes_rgba(cm: types.Colormap, values: Any) -> Any:
    """``(4, h, w)`` uint8: each class value its colour, the rest ``other`` or transparent."""
    import numpy as np

    rgba = np.zeros((*values.shape, 4), dtype="uint8")
    if cm.other is not None:
        rgba[...] = cm.other.rgba
    for value, color, _ in cm.classes:
        rgba[values == value] = color.rgba
    return np.moveaxis(rgba, -1, 0)


def colormap_stops(n: int = 9) -> dict[str, list[str]]:
    """A few colours of each colormap, for legends and the colormap picker."""
    out: dict[str, list[str]] = {}
    for name in COLORMAPS:
        lut = _lut(name)
        idx = [round(i * 255 / (n - 1)) for i in range(n)]
        out[name] = ["#{:02x}{:02x}{:02x}".format(*lut[i][:3]) for i in idx]
    return out


@functools.lru_cache(maxsize=1)
def _empty_png() -> bytes:
    import numpy as np
    from rio_tiler.utils import render

    blank = np.zeros((3, TILE_SIZE, TILE_SIZE), dtype="uint8")
    return render(blank, mask=np.zeros((TILE_SIZE, TILE_SIZE), dtype="uint8"), img_format="PNG")


def render_tile(
    cache: DiskCache,
    key: str,
    z: int,
    x: int,
    y: int,
    *,
    bands: tuple[int, ...] = (1,),
    colormap: str | types.Colormap = "viridis",
    vmin: float | None = None,
    vmax: float | None = None,
) -> bytes:
    """A 256 px PNG in Web Mercator; transparent outside the raster and on nodata.

    ``colormap`` is a ramp name, ``categorical``, or a Colormap (change 03): a
    continuous one's own min/max win over ``vmin``/``vmax``; a classes one
    colours listed values only (``other`` the rest, transparent when ``None``),
    and a colour's alpha multiplies the tile's. Three bands ignore the colormap.
    """
    import numpy as np
    from rio_tiler.errors import TileOutsideBounds
    from rio_tiler.utils import render

    if len(bands) not in (1, 3):
        raise MapError("bands is 1 or 3 band numbers")
    if isinstance(colormap, types.Colormap):
        if colormap.kind == types.CONTINUOUS:
            vmin = colormap.min if colormap.min is not None else vmin
            vmax = colormap.max if colormap.max is not None else vmax
    elif colormap not in (*COLORMAPS, CATEGORICAL):
        raise MapError(f'unknown colormap "{colormap}"')
    entry, path = _raster_file(cache, key)
    if vmin is None or vmax is None:
        stats = _stats(str(path), _version(path), bands)
        vmin = stats["min"] if vmin is None else vmin
        vmax = stats["max"] if vmax is None else vmax
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # NoOverviewWarning for small rasters
            view, indexes = band_view(entry, path, bands)
            with _pool.reader(str(view)) as reader:
                img = reader.tile(x, y, z, indexes=indexes, tilesize=TILE_SIZE)
    except TileOutsideBounds:
        return _empty_png()
    data = np.ma.getdata(img.array).astype("float64")
    alpha = np.where(np.asarray(img.mask) > 0, 255, 0).astype("uint8")
    alpha[~np.isfinite(data).all(axis=0)] = 0
    cm = colormap if isinstance(colormap, types.Colormap) and len(bands) == 1 else None
    if cm is not None and cm.kind == types.CLASSES:
        rgba = _classes_rgba(cm, data[0])
        rgb = rgba[:3]
        alpha = _times_alpha(alpha, rgba[3])
    elif len(bands) == 1 and colormap == CATEGORICAL:
        values = np.nan_to_num(data[0]).astype("int64")
        rgb = np.moveaxis(_palette()[values % len(PALETTE)], -1, 0)
    else:
        span = (vmax - vmin) or 1.0
        scaled = np.clip((np.nan_to_num(data) - vmin) / span, 0, 1)
        index = np.round(scaled * 255).astype("uint8")
        if cm is not None:
            rgba = np.moveaxis(colormap_lut(cm)[index[0]], -1, 0)
            rgb = rgba[:3]
            if not cm.is_named:  # rio-tiler's tables are opaque: same bytes as by name
                alpha = _times_alpha(alpha, rgba[3])
        elif len(bands) == 1:
            rgb = np.moveaxis(_lut(str(colormap))[index[0]][..., :3], -1, 0)
        else:
            rgb = index
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # NotGeoreferencedWarning: a PNG tile has no transform
        return render(np.ascontiguousarray(rgb, dtype="uint8"), mask=alpha, img_format="PNG")


def _times_alpha(alpha: Any, colour_alpha: Any) -> Any:
    """The tile's alpha times a colour's (both 0-255)."""
    import numpy as np

    out = np.round(alpha.astype("uint16") * colour_alpha.astype("uint16") / 255)
    return out.astype("uint8")


# ── vectors ──


def _vector(cache: DiskCache, key: str) -> Any:
    _, info = cache.port_info(check_key(key))
    if info.get("type") != types.VECTOR or info.get("access") == "list":
        raise MapError(f"{key} is not a vector", 404)
    gdf = cache.read_port(key)
    if gdf.crs is None:
        raise MapError("the vector has no CRS, so it cannot be placed on the map")
    return gdf


@functools.lru_cache(maxsize=64)
def _describe_vector(cache_root: str, key: str) -> dict[str, Any]:
    gdf = _vector(DiskCache(Path(cache_root)), key)
    shown = gdf.head(MAX_FEATURES).to_crs("EPSG:4326")
    valid = shown[~shown.geometry.is_empty & shown.geometry.notna()]
    bounds = [float(v) for v in valid.total_bounds] if len(valid) else None
    return {
        "features": len(gdf),
        "shown": len(shown),
        "geometry": sorted({str(t) for t in valid.geom_type.unique()}),
        "columns": [str(c) for c in gdf.columns if c != gdf.geometry.name],
        "crs": gdf.crs.to_string(),
        "bounds": bounds,
    }


def describe_vector(cache: DiskCache, key: str) -> dict[str, Any]:
    desc = dict(_describe_vector(str(cache.root), key))
    desc["default_style"] = {"color": PALETTE[3], "opacity": 1.0, "visible": True}
    return desc


@functools.lru_cache(maxsize=64)
def _vector_field(cache_root: str, key: str, name: str) -> dict[str, Any]:
    gdf = _vector(DiskCache(Path(cache_root)), key)
    if name not in gdf.columns or name == gdf.geometry.name:
        raise MapError(f'the vector has no field "{name}"')
    import pandas as pd

    column = gdf[name].head(MAX_FEATURES)
    numeric = pd.api.types.is_numeric_dtype(column) and not pd.api.types.is_bool_dtype(column)
    values = pd.to_numeric(column, errors="coerce") if numeric else None
    finite = values[values.notna()] if values is not None else None
    if finite is None or finite.empty:
        return {"name": name, "numeric": numeric, "min": None, "max": None}
    return {"name": name, "numeric": True, "min": float(finite.min()), "max": float(finite.max())}


def vector_field(cache: DiskCache, key: str, name: str) -> dict[str, Any]:
    """``{name, numeric, min, max}`` of a vector's field over the features the GeoJSON
    carries (at most MAX_FEATURES): the "auto" range of a continuous Colormap that
    colours the vector by that field (change 03, section 4)."""
    return dict(_vector_field(str(cache.root), key, name))


def vector_geojson(cache: DiskCache, key: str) -> tuple[str, int]:
    """``(GeoJSON in EPSG:4326 of at most MAX_FEATURES features, total feature count)``."""
    gdf = _vector(cache, key)
    shown = gdf.head(MAX_FEATURES).to_crs("EPSG:4326")
    return shown.to_json(drop_id=True, default=str), len(gdf)


# ── inspect ──


def inspect_raster(cache: DiskCache, key: str, lon: float, lat: float) -> dict[str, Any]:
    """Every band's value at ``lon, lat`` (the pixel it falls in, as Extract Values reads)."""
    import geopandas
    from shapely.geometry import Point

    from geoknit.helpers.sampling import values_at_points

    _, info = cache.port_info(check_key(key))
    if info.get("type") != types.RASTER or info.get("access") == "list":
        raise MapError(f"{key} is not a raster", 404)
    raster = cache.read_port(key)
    point = geopandas.GeoDataFrame(geometry=[Point(lon, lat)], crs="EPSG:4326")
    found = values_at_points(raster, point)
    names = types.raster_band_names(raster)
    row = found.values[0]
    return {
        "outside": bool(found.outside[0]),
        "values": [
            {"band": str(name), "value": None if v != v else _plain(v)}  # NaN → null
            for name, v in zip(names, row, strict=True)
        ],
    }


def _plain(value: float) -> float | int:
    return int(value) if float(value).is_integer() else float(value)
