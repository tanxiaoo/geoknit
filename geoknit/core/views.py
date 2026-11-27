"""Panel views of values (change 01, section 11): small, JSON-safe, per type.

The worker sends a ``view`` next to each output's ``describe()`` summary; the
Panel draws it (a value, a swatch, a gradient, list rows, a table grid). Table
and Vector views carry the first page of rows; later pages come from the disk
cache (``geoknit.server.tables``), encoded by the same ``encode_page``.

Shapes (``kind`` says which):

- ``{"kind": "value", "type": "Number" | "Text" | "Boolean", "value": …}``
- ``{"kind": "color", "type": "Color", "value": "#RRGGBB[AA]"}``
- ``{"kind": "colormap", "type": "Colormap", "value": <Colormap JSON>}``
- ``{"kind": "list", "type": <element type or None>, "count": N,
  "items": [<element view>, …]}`` (first ``LIST_SHOWN``)
- ``{"kind": "table", "type": "Table" | "Vector", <a page>}``, a page being
  ``{columns, rows, index, total_rows, offset, geometry}``
- ``{"kind": "summary", "type": <type or None>, "text": <describe()>}`` for
  Raster, Model and anything else (an element view: its first line).

pandas is never imported here; frames are handled through their own methods.
"""

from __future__ import annotations

import math
import numbers
from typing import Any

from geoknit.core import types

PAGE_ROWS = 200
"""Rows in a Table/Vector view, and the Panel's page size."""
MAX_PAGE_ROWS = 1000
"""Largest ``limit`` of ``GET /api/table/{key}``."""
CELL_TEXT_MAX = 1000
"""Longer text cells are cut to this many characters and end in ``…``."""


def view(value: Any) -> dict[str, Any]:
    """The Panel view of an output value."""
    kind = types.type_of(value)
    if kind in (types.VECTOR, types.TABLE):
        return {"kind": "table", "type": kind, **page_of(value, 0, PAGE_ROWS)}
    if isinstance(value, list):
        kinds = {types.type_of(v) for v in value}
        return {
            "kind": "list",
            "type": next(iter(kinds)) if len(kinds) == 1 else None,
            "count": len(value),
            "items": [element_view(v) for v in value[: types.LIST_SHOWN]],
        }
    return _simple_view(value, kind, first_line=False)


def element_view(value: Any) -> dict[str, Any]:
    """The one-line view of a list element: a simple value as in ``view``, else
    the first line of its ``describe()``."""
    return _simple_view(value, types.type_of(value), first_line=True)


def safe_view(value: Any, summary: str) -> dict[str, Any]:
    """``view(value)``; if that fails, a summary view of ``summary`` (never raises)."""
    try:
        return view(value)
    except Exception:  # noqa: BLE001  (a view must not fail a run)
        return {"kind": "summary", "type": types.type_of(value), "text": summary}


def _simple_view(value: Any, kind: str | None, *, first_line: bool) -> dict[str, Any]:
    if kind == types.NUMBER:
        return {"kind": "value", "type": kind, "value": number_value(value)}
    if kind == types.BOOLEAN:
        return {"kind": "value", "type": kind, "value": bool(value)}
    if kind == types.TEXT:
        return {"kind": "value", "type": kind, "value": str(value)}
    if kind == types.COLOR:
        return {"kind": "color", "type": kind, "value": value.to_json()}
    if kind == types.COLORMAP:
        return {"kind": "colormap", "type": kind, "value": value.to_json()}
    text = types.describe(value)
    if first_line:
        text = text.split("\n", 1)[0]
    return {"kind": "summary", "type": kind, "text": text}


def number_value(value: Any) -> int | float | str:
    """A Number as JSON: ``int`` / ``float``; NaN and infinities as ``"nan"``,
    ``"inf"``, ``"-inf"`` (as ``describe()`` prints them)."""
    if isinstance(value, numbers.Integral):
        return int(value)
    f = float(value)
    return f if math.isfinite(f) else str(f)


# ── table pages ──


def geometry_columns(df: Any) -> list[str]:
    """Names of the geometry columns of a frame (a GeoDataFrame's, by dtype)."""
    return [str(c) for c in df.columns if str(getattr(df[c], "dtype", "")) == "geometry"]


def page_of(df: Any, offset: int, limit: int) -> dict[str, Any]:
    """A page of an in-memory Table or Vector: rows ``offset`` … ``offset + limit - 1``."""
    part = df.iloc[offset : offset + limit]  # shapely geometries become type names in ``cell``
    return encode_page(part, offset=offset, total_rows=len(df), geometry=geometry_columns(df))


def encode_page(
    part: Any,
    *,
    offset: int,
    total_rows: int,
    geometry: list[str],
    index: list[Any] | None = None,
) -> dict[str, Any]:
    """``{columns, rows, index, total_rows, offset, geometry}`` from a slice of a frame.

    Geometry columns hold shapely geometries or their type names. ``index`` overrides
    the slice's own index labels (already JSON values).
    """
    columns = [str(c) for c in part.columns]
    data = part.to_numpy(dtype=object) if len(columns) else [[] for _ in range(len(part))]
    rows = [[cell(v) for v in row] for row in data]
    return {
        "columns": columns,
        "rows": rows,
        "index": index if index is not None else [cell(v) for v in part.index],
        "total_rows": int(total_rows),
        "offset": int(offset),
        "geometry": geometry,
    }


def cell(value: Any) -> Any:  # noqa: PLR0911  (one branch per kind of value)
    """A table cell (or index label) as JSON.

    Missing values (``None``, NaN, ``NaT``, ``pd.NA``) → ``null``; booleans,
    integers and finite floats as they are; infinities → ``"inf"`` / ``"-inf"``;
    dates and times → ISO 8601 text; bytes → ``"<N bytes>"``; a shapely
    geometry → its type name; anything else → its ``str()``. Text is cut to
    ``CELL_TEXT_MAX`` characters.
    """
    if value is None:
        return None
    if isinstance(value, bool) or types.type_of(value) == types.BOOLEAN:
        return bool(value)
    if isinstance(value, str):
        return _cut(value)
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        f = float(value)
        if math.isnan(f):
            return None
        return f if math.isfinite(f) else ("inf" if f > 0 else "-inf")
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(value)} bytes>"
    name = type(value).__name__
    if name in ("NAType", "NaTType"):
        return None
    if name == "datetime64" or name == "timedelta64":  # numpy scalars
        return None if value != value else str(value)  # noqa: PLR0124  (NaT test)
    if type(value).__module__.split(".")[0] == "shapely":
        return str(getattr(value, "geom_type", name))
    if isinstance(value, types.Color):
        return value.hex
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):  # datetime, date, time, pandas Timestamp
        return str(isoformat())
    if isinstance(value, numbers.Number):  # Decimal, complex
        return cell(float(value)) if not isinstance(value, complex) else str(value)
    return _cut(str(value))


def _cut(text: str) -> str:
    return text if len(text) <= CELL_TEXT_MAX else text[: CELL_TEXT_MAX - 1] + "…"
