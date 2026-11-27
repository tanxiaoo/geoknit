"""Table pages for the Panel (change 01, section 11): ``GET /api/table/{key}``.

A page of a cached Table or Vector, read from the disk cache by port key
(``<node key>.<port>``, or ``<node key>.<port>[i]`` for an element of a list
output). Parquet entries are read by row group, so one page never loads a
large table whole; the cache writes Tables and Vectors in row groups of
``ROW_GROUP_ROWS`` rows. A pickle fallback entry is loaded once and memoised.
Geometry columns are sent as their geometry type names.

After the Map Viewer (``tiles.py``) this is the second place where the server
reads a result itself. pandas and pyarrow are imported the first time a page
is asked for (shapely too, for a Vector).
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path
from typing import Any

from geoknit.core import types, views
from geoknit.core.cache import CacheMiss, DiskCache, list_element_info

_KEY = re.compile(r"^([0-9a-f]{64}\.[A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?$")

_GEOMETRY_NAMES = (
    "Point",
    "LineString",
    "LinearRing",
    "Polygon",
    "MultiPoint",
    "MultiLineString",
    "MultiPolygon",
    "GeometryCollection",
)
"""shapely's geometry type ids 0…7, by name."""


class TableError(Exception):
    """A page request that cannot be answered; ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _entry(cache: DiskCache, key: str) -> tuple[Path, dict[str, Any]]:
    """``(folder, port info)`` of a port key or a list element ``<key>[i]``."""
    m = _KEY.match(key)
    if m is None:
        raise TableError(f'"{key}" is not a port key')
    entry, info = cache.port_info(m.group(1))
    if m.group(2) is not None:
        entry, info = list_element_info(entry, info, int(m.group(2)))
    if info.get("access") == "list" or info.get("type") not in (types.TABLE, types.VECTOR):
        raise TableError(f"{key} is not a Table or a Vector")
    return entry, info


def table_page(cache: DiskCache, key: str, offset: int, limit: int) -> dict[str, Any]:
    """``{columns, rows, index, total_rows, offset, geometry}`` (see ``core.views``)."""
    if offset < 0 or not 0 <= limit <= views.MAX_PAGE_ROWS:
        raise TableError(f"offset must be 0 or more and limit 0 to {views.MAX_PAGE_ROWS}", 400)
    entry, info = _entry(cache, key)
    path = entry / info["file"]
    try:
        if info["format"] in ("parquet", "geoparquet"):
            return _parquet_page(path, offset, limit)
        if info["format"] == "pickle":
            return views.page_of(_pickled(str(path)), offset, limit)
    except OSError:
        raise CacheMiss(key) from None
    raise TableError(f"{key} is not stored as a table")


@functools.lru_cache(maxsize=4)
def _pickled(path: str) -> Any:
    """A pickle fallback entry, loaded once (entries never change under a key)."""
    import pandas

    return pandas.read_pickle(path)


def _parquet_page(path: Path, offset: int, limit: int) -> dict[str, Any]:
    import pyarrow.parquet as pq

    with path.open("rb") as fh:  # closed at once: Windows must be able to delete it
        pf = pq.ParquetFile(fh)
        meta = pf.schema_arrow.metadata or {}
        total = pf.metadata.num_rows
        stop = min(offset + limit, total)
        groups: list[int] = []
        first = start = 0
        for g in range(pf.metadata.num_row_groups):
            n = pf.metadata.row_group(g).num_rows
            if start < stop and start + n > offset:
                if not groups:
                    first = start
                groups.append(g)
            start += n
        if groups:
            table = pf.read_row_groups(groups).slice(offset - first, stop - offset)
        else:
            table = pf.schema_arrow.empty_table()
    geo = json.loads(meta.get(b"geo", b"null")) or {}
    geometry = [str(c) for c in geo.get("columns", {})]
    for name in geometry:
        i = table.schema.get_field_index(name)
        if i >= 0:
            table = table.set_column(i, name, _geometry_names(table.column(name), geo, name))
    part = table.to_pandas()
    index = None
    pandas_meta = json.loads(meta.get(b"pandas", b"null")) or {}
    levels = pandas_meta.get("index_columns", [])
    if not levels or (len(levels) == 1 and isinstance(levels[0], dict)):
        # A RangeIndex is stored as metadata only, and lost on a slice: rebuild it.
        r = levels[0] if levels else {"start": 0, "step": 1}
        index = [r["start"] + r["step"] * (offset + i) for i in range(len(part))]
    return views.encode_page(
        part,
        offset=offset,
        total_rows=total,
        geometry=[str(c) for c in part.columns if str(c) in geometry],
        index=index,
    )


def _geometry_names(column: Any, geo: dict[str, Any], name: str) -> Any:
    """A GeoParquet geometry column as an arrow column of type names (null when missing)."""
    import pyarrow

    encoding = str(geo["columns"][name].get("encoding", "WKB")).upper()
    if encoding != "WKB":  # GeoArrow: not written by the cache; name the encoding
        return pyarrow.array([None if v is None else encoding for v in column.to_pylist()])
    import shapely

    geoms = shapely.from_wkb(column.to_numpy())
    ids = shapely.get_type_id(geoms)
    return pyarrow.array([_GEOMETRY_NAMES[t] if t >= 0 else None for t in ids.tolist()])
