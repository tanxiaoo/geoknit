"""The six GeoKnit data types, ``ModelBundle``, ``describe()`` and connection rules.

SPEC section 3. Heavy libraries (xarray, geopandas, pandas) are never imported
at module level: type checks compare class names along the MRO, and
``describe()`` imports what it needs lazily. ``describe()`` never reads pixels.
"""

from __future__ import annotations

import numbers
from dataclasses import dataclass, field
from typing import Any

NUMBER = "Number"
TEXT = "Text"
RASTER = "Raster"
VECTOR = "Vector"
TABLE = "Table"
MODEL = "Model"
ANY = "Any"

DATA_TYPES: tuple[str, ...] = (NUMBER, TEXT, RASTER, VECTOR, TABLE, MODEL)
"""The six data types a port can carry (``Any`` is only for Panel / Map Viewer)."""

PORT_TYPES: tuple[str, ...] = (*DATA_TYPES, ANY)

PORT_COLOURS: dict[str, str] = {
    NUMBER: "#64748B",
    TEXT: "#A16207",
    RASTER: "#0B7A7C",
    VECTOR: "#C2410C",
    TABLE: "#7C3AED",
    MODEL: "#BE185D",
}

RASTER_CHUNKS: dict[str, int] = {"band": -1, "y": 512, "x": 512}
"""Dask chunks for rasters opened lazily: all bands together, 512 × 512 px windows."""


@dataclass
class ModelBundle:
    """A trained model plus what is needed to apply it."""

    estimator: Any
    task: str
    target: str
    feature_names: list[str]
    info: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.task not in ("regression", "classification"):
            raise ValueError(f'task must be "regression" or "classification", got "{self.task}"')


# ── Type checks ──────────────────────────────────────────────────────────────


def _has_class(value: object, module_prefix: str, name: str) -> bool:
    return any(
        c.__name__ == name and c.__module__.split(".")[0] == module_prefix
        for c in type(value).__mro__
    )


def type_of(value: object) -> str | None:
    """The GeoKnit type of ``value``, or ``None`` if it is not one of the six."""
    if isinstance(value, bool):
        return None
    if isinstance(value, numbers.Real):
        return NUMBER
    if isinstance(value, str):
        return TEXT
    if isinstance(value, ModelBundle):
        return MODEL
    if _has_class(value, "xarray", "DataArray"):
        return RASTER
    if _has_class(value, "geopandas", "GeoDataFrame"):
        return VECTOR
    if _has_class(value, "pandas", "DataFrame"):
        return TABLE
    return None


def python_type_name(value: object) -> str:
    """Readable class name for error messages, e.g. ``pandas.DataFrame``."""
    cls = type(value)
    module = cls.__module__.split(".")[0]
    return cls.__name__ if module == "builtins" else f"{module}.{cls.__name__}"


def check_value(expected: str, value: object) -> str | None:
    """``None`` if ``value`` fits a port of type ``expected``, else an error message."""
    if expected == ANY:
        return None
    actual = type_of(value)
    if actual == expected:
        return None
    shown = actual if actual is not None else python_type_name(value)
    return f"expected {expected}, got {shown}"


# ── Connection rules ─────────────────────────────────────────────────────────


def can_connect(out_type: str, in_type: str) -> bool:
    """Whether an output of ``out_type`` may be wired to an input of ``in_type``.

    Same type, an ``Any`` input, Number → Text, and an ``Any`` output (Panel's
    pass-through, checked when the node runs).
    """
    return (
        out_type == in_type
        or in_type == ANY
        or out_type == ANY
        or (out_type, in_type)
        == (
            NUMBER,
            TEXT,
        )
    )


def connection_error(out_type: str, in_type: str) -> str | None:
    """``None`` if the wire is allowed, else the tooltip text for refusing it."""
    if can_connect(out_type, in_type):
        return None
    return f"{out_type} can't connect to {in_type}"


def convert_for_input(value: object, in_type: str) -> object:
    """Apply the Number → Text convenience conversion."""
    if in_type == TEXT and type_of(value) == NUMBER:
        return str(value)
    return value


# ── describe() ───────────────────────────────────────────────────────────────


def describe(value: object) -> str:
    """A short, metadata-only summary of ``value`` for Panels and tooltips."""
    kind = type_of(value)
    if kind == NUMBER or kind == TEXT:
        return str(value)
    if kind == RASTER:
        return _describe_raster(value)
    if kind == VECTOR:
        return _describe_vector(value)
    if kind == TABLE:
        return _describe_table(value)
    if kind == MODEL:
        assert isinstance(value, ModelBundle)
        return _describe_model(value)
    if isinstance(value, list):
        return "\n".join(
            [f"list of {len(value)}"] + [f"[{i}] {describe(v)}" for i, v in enumerate(value)]
        )
    return f"{python_type_name(value)}: {value!r}"[:500]


def raster_band_names(da: Any) -> list[str]:
    """Band names from the band descriptions, else ``b01, b02, …``."""
    n = int(da.sizes.get("band", 1))
    names = da.attrs.get("long_name")
    if isinstance(names, str):
        names = [names] if n == 1 else None
    if names is not None and len(names) == n and all(names):
        return [str(x) for x in names]
    return [f"b{i:02d}" for i in range(1, n + 1)]


def _shorten(items: list[str], limit: int = 8) -> str:
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:3]) + f", … , {', '.join(items[-2:])}"


def _describe_raster(da: Any) -> str:
    import rioxarray  # noqa: F401  (registers the .rio accessor)

    names = raster_band_names(da)
    width = int(da.sizes.get("x", 0))
    height = int(da.sizes.get("y", 0))
    try:
        rx, ry = da.rio.resolution()
        res = f"{abs(rx):g} × {abs(ry):g}"
    except Exception:  # noqa: BLE001  (no transform)
        res = "unknown"
    crs = da.rio.crs
    crs_text = crs.to_string() if crs is not None else "none"
    nodata: object = da.rio.nodata
    if da.rio.encoded_nodata is not None:  # opened with masked=True
        nodata = f"{da.rio.encoded_nodata:g} (masked)"
    return "\n".join(
        [
            f"Raster · {len(names)} band{'s' if len(names) != 1 else ''}: {_shorten(names)}",
            f"{width} × {height} px · resolution {res}",
            f"dtype {da.dtype} · CRS {crs_text} · nodata {nodata}",
        ]
    )


def _describe_vector(gdf: Any) -> str:
    geom_types = sorted({str(t) for t in gdf.geom_type.dropna().unique()}) if len(gdf) else []
    crs = gdf.crs.to_string() if gdf.crs is not None else "none"
    cols = [str(c) for c in gdf.columns if c != gdf.geometry.name]
    return "\n".join(
        [
            f"Vector · {len(gdf)} features · {', '.join(geom_types) or 'no geometry'}",
            f"CRS {crs}",
            f"columns: {_shorten(cols) or '(none)'}",
        ]
    )


def _describe_table(df: Any) -> str:
    head = df.head(5).to_string(max_cols=10, max_colwidth=20)
    return f"Table · {len(df)} rows × {len(df.columns)} columns\n{head}"


def _describe_model(m: ModelBundle) -> str:
    params: dict[str, Any] = {}
    get_params = getattr(m.estimator, "get_params", None)
    if callable(get_params):
        params = {k: v for k, v in get_params(deep=False).items() if not callable(v)}
    shown = ", ".join(f"{k}={v!r}" for k, v in sorted(params.items()))
    return "\n".join(
        [
            f"Model · {type(m.estimator).__name__} · {m.task}",
            f"target {m.target} · {len(m.feature_names)} features: {_shorten(m.feature_names)}",
            f"parameters: {shown or '(none)'}",
        ]
    )
