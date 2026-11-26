"""GeoKnit data types, ``ModelBundle``, ``Color``, ``Colormap``, ``describe()``
and connection rules.

SPEC section 3. Heavy libraries (xarray, geopandas, pandas) are never imported
at module level: type checks compare class names along the MRO, and
``describe()`` imports what it needs lazily. ``describe()`` never reads pixels.
"""

from __future__ import annotations

import numbers
import re
from dataclasses import dataclass, field
from typing import Any

NUMBER = "Number"
TEXT = "Text"
RASTER = "Raster"
VECTOR = "Vector"
TABLE = "Table"
MODEL = "Model"
BOOLEAN = "Boolean"
COLOR = "Color"
COLORMAP = "Colormap"
LAYER = "Layer"
ANY = "Any"

DATA_TYPES: tuple[str, ...] = (
    NUMBER,
    TEXT,
    RASTER,
    VECTOR,
    TABLE,
    MODEL,
    BOOLEAN,
    COLOR,
    COLORMAP,
    LAYER,
)
"""The data types a port can carry (``Any`` is only an input type, e.g. Panel's).

``Layer`` is only a name until change 03 defines its Python object."""

PORT_TYPES: tuple[str, ...] = (*DATA_TYPES, ANY)

PORT_COLOURS: dict[str, str] = {
    NUMBER: "#64748B",
    TEXT: "#A16207",
    RASTER: "#0B7A7C",
    VECTOR: "#C2410C",
    TABLE: "#7C3AED",
    MODEL: "#BE185D",
    BOOLEAN: "#0369A1",
    COLOR: "#4D7C0F",
    COLORMAP: "#4338CA",
    LAYER: "#A21CAF",
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


# ── Color and Colormap ───────────────────────────────────────────────────────

_HEX = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})")
_COLOR_FORMS = '"#RRGGBB", "#RRGGBBAA", "r,g,b" or "r,g,b,a" with values 0-255'


@dataclass(frozen=True)
class Color:
    """A colour; ``hex`` is ``#RRGGBB`` or ``#RRGGBBAA``, stored upper case."""

    hex: str

    def __post_init__(self) -> None:
        if not isinstance(self.hex, str) or not _HEX.fullmatch(self.hex):
            raise ValueError(f"not a colour: {self.hex!r} (use {_COLOR_FORMS})")
        object.__setattr__(self, "hex", self.hex.upper())

    @classmethod
    def parse(cls, text: str) -> Color:
        """``#0b7a7c``, ``#0B7A7CFF``, ``11,122,124`` or ``11,122,124,255``."""
        s = text.strip() if isinstance(text, str) else ""
        if _HEX.fullmatch(s):
            return cls(s)
        parts = [p.strip() for p in s.split(",")]
        if len(parts) in (3, 4) and all(p.isdigit() and int(p) <= 255 for p in parts):
            return cls("#" + "".join(f"{int(p):02X}" for p in parts))
        raise ValueError(f"not a colour: {text!r} (use {_COLOR_FORMS})")

    @property
    def rgba(self) -> tuple[int, int, int, int]:
        """The four channels, 0-255; alpha is 255 when the hex has none."""
        h = self.hex[1:] + ("" if len(self.hex) == 9 else "FF")
        r, g, b, a = (int(h[i : i + 2], 16) for i in (0, 2, 4, 6))
        return r, g, b, a

    def to_json(self) -> str:
        return self.hex

    @classmethod
    def from_json(cls, data: Any) -> Color:
        if not isinstance(data, str):
            raise ValueError(f"not a colour: {data!r} (use {_COLOR_FORMS})")
        return cls(data)


NAMED_RAMPS: dict[str, tuple[str, ...]] = {
    "viridis": ("440154", "472575", "404387", "345E8D", "29788E", "20908C",
                "22A784", "42BE71", "79D151", "BDDE26", "FDE724"),
    "magma": ("000003", "150E38", "3B0F6F", "63197F", "8C2980", "B63679",
              "DD4968", "F66E5B", "FD9F6C", "FDCF92", "FBFCBF"),
    "plasma": ("0C0786", "42039D", "6A00A7", "8F0DA3", "B02A8F", "CB4777",
               "E06461", "F1824C", "FCA635", "FCCE25", "EFF821"),
    "cividis": ("00224D", "0B3370", "35456C", "4E566C", "666970", "7C7B78",
                "948E77", "ADA271", "C8B765", "E4CE51", "FDE737"),
    "turbo": ("30123B", "455BCE", "3E9BFE", "18D5CC", "46F783", "A4FC3B",
              "E1DC37", "FDA631", "EF5A11", "C32402", "7A0402"),
    "greys_r": ("000000", "1E1E1E", "404040", "5E5E5E", "7A7A7A", "969696",
                "B5B5B5", "CDCDCD", "E2E2E2", "F3F3F3", "FFFFFF"),
    "terrain": ("333399", "1078DE", "00B2B2", "31D56F", "99EA84", "FEFD98",
                "CCBD7D", "9A7D62", "997C76", "CDBFBB", "FFFFFF"),
    "rdylgn": ("A50026", "D73127", "F46D43", "FCAC60", "FEE08B", "FEFEBD",
               "D9EF8B", "A7D96A", "66BD63", "19974F", "006837"),
    "spectral": ("9E0142", "D53E4E", "F46D43", "FCAC60", "FEE08B", "FEFEBE",
                 "E6F598", "ACDDA3", "66C2A5", "3286BC", "5E4FA2"),
    "blues": ("F7FBFF", "E2EDF8", "CFE1F2", "B6D4E9", "93C4DE", "6AADD5",
              "4A97C9", "2E7EBC", "1764AB", "084991", "08306B"),
}  # fmt: skip
"""The Map Viewer's named ramps (rio-tiler's tables), 11 evenly spaced stops each.

Kept as plain data so exported scripts need neither matplotlib nor rio-tiler;
a test checks them against rio-tiler."""

CONTINUOUS = "continuous"
CLASSES = "classes"


def _named_stops(name: str) -> tuple[tuple[float, Color], ...]:
    ramp = NAMED_RAMPS[name]
    return tuple((i / (len(ramp) - 1), Color("#" + c)) for i, c in enumerate(ramp))


def _as_color(value: Any) -> Color:
    return value if isinstance(value, Color) else Color.parse(value)


def _is_real(value: Any) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


@dataclass(frozen=True)
class Colormap:
    """A continuous ramp (``stops`` at positions 0…1) or a set of classes.

    Continuous: ``min``/``max`` ``None`` means the layer's 2–98 % stretch;
    ``Colormap.named("viridis")`` fills ``stops`` from ``NAMED_RAMPS``.
    Classes: ``(value, colour, label)`` triples; ``other`` colours the values
    not listed (``None`` = transparent).
    """

    kind: str
    name: str | None = None
    stops: tuple[tuple[float, Color], ...] = ()
    min: float | None = None
    max: float | None = None
    reverse: bool = False
    classes: tuple[tuple[int | float, Color, str], ...] = ()
    other: Color | None = None

    def __post_init__(self) -> None:
        if self.kind == CONTINUOUS:
            self._check_continuous()
        elif self.kind == CLASSES:
            self._check_classes()
        else:
            raise ValueError(f'colormap kind must be "{CONTINUOUS}" or "{CLASSES}"')

    def _check_continuous(self) -> None:
        if self.classes or self.other is not None:
            raise ValueError("a continuous colormap has no classes")
        if self.name is not None and self.name not in NAMED_RAMPS:
            raise ValueError(
                f'unknown colormap "{self.name}" (use one of {", ".join(NAMED_RAMPS)})'
            )
        stops = tuple((float(p), _as_color(c)) for p, c in self.stops)
        if not stops and self.name is not None:
            stops = _named_stops(self.name)
        if len(stops) < 2:
            raise ValueError("a continuous colormap needs at least 2 stops")
        positions = [p for p, _ in stops]
        if not all(0 <= p <= 1 for p in positions) or positions != sorted(positions):
            raise ValueError("colormap stop positions must be 0…1, in order")
        for bound in (self.min, self.max):
            if bound is not None and not _is_real(bound):
                raise ValueError("colormap min and max must be numbers")
        if self.min is not None and self.max is not None and self.min >= self.max:
            raise ValueError("colormap min must be less than max")
        if not isinstance(self.reverse, bool):
            raise ValueError("colormap reverse must be true or false")
        object.__setattr__(self, "stops", stops)

    def _check_classes(self) -> None:
        if self.name is not None or self.stops or self.reverse:
            raise ValueError("a classes colormap has no name, stops or reverse")
        if self.min is not None or self.max is not None:
            raise ValueError("a classes colormap has no min or max")
        classes: list[tuple[int | float, Color, str]] = []
        for item in self.classes:
            if len(item) != 3:
                raise ValueError("a class is (value, colour, label)")
            value, color, label = item
            if not _is_real(value):
                raise ValueError(f"class value {value!r} is not a number")
            classes.append((value, _as_color(color), str(label)))
        if not classes:
            raise ValueError("a classes colormap needs at least one class")
        values = [v for v, _, _ in classes]
        if len(set(values)) != len(values):
            raise ValueError("a class value is listed twice")
        object.__setattr__(self, "classes", tuple(classes))
        if self.other is not None:
            object.__setattr__(self, "other", _as_color(self.other))

    @classmethod
    def named(cls, name: str, reverse: bool = False) -> Colormap:
        """One of the Map Viewer's ramps (``NAMED_RAMPS``), on the 2–98 % stretch."""
        return cls(CONTINUOUS, name=name, reverse=reverse)

    @property
    def is_named(self) -> bool:
        """A named ramp whose stops were not edited."""
        return self.name is not None and self.stops == _named_stops(self.name)

    def to_json(self) -> dict[str, Any]:
        """The form used in the workflow file, the cache and the API."""
        if self.kind == CLASSES:
            return {
                "kind": CLASSES,
                "classes": [[v, c.hex, label] for v, c, label in self.classes],
                "other": self.other.hex if self.other is not None else None,
            }
        out: dict[str, Any] = {"kind": CONTINUOUS, "name": self.name}
        if not self.is_named:  # a named ramp's stops follow from its name
            out["stops"] = [[p, c.hex] for p, c in self.stops]
        out.update(min=self.min, max=self.max, reverse=self.reverse)
        return out

    @classmethod
    def from_json(cls, data: Any) -> Colormap:
        if not isinstance(data, dict):
            raise ValueError("a colormap is an object with a kind")
        known = {"kind", "name", "stops", "min", "max", "reverse", "classes", "other"}
        unknown = sorted(set(data) - known)
        if unknown:
            raise ValueError(f'unknown colormap key "{unknown[0]}"')
        if "kind" not in data:
            raise ValueError("a colormap is an object with a kind")
        args = dict(data)
        for key in ("stops", "classes"):
            if key in args:
                args[key] = tuple(tuple(item) for item in args[key])
        return cls(**args)


def to_json_value(value: Any) -> Any:
    """``value`` as plain JSON data: Color and Colormap by their ``to_json()``."""
    if isinstance(value, Color | Colormap):
        return value.to_json()
    return value


def from_json_value(type_name: str, data: Any) -> Any:
    """Rebuild a value of port type ``type_name`` from ``to_json_value`` data."""
    if type_name == COLOR:
        return Color.from_json(data)
    if type_name == COLORMAP:
        return Colormap.from_json(data)
    return data


# ── Type checks ──────────────────────────────────────────────────────────────


def _has_class(value: object, module_prefix: str, name: str) -> bool:
    return any(
        c.__name__ == name and c.__module__.split(".")[0] == module_prefix
        for c in type(value).__mro__
    )


def _is_numpy_bool(value: object) -> bool:
    # numpy.bool_ is called "bool" from numpy 2 on.
    return _has_class(value, "numpy", "bool_") or _has_class(value, "numpy", "bool")


def type_of(value: object) -> str | None:
    """The GeoKnit type of ``value``, or ``None`` if it has none.

    ``bool`` and ``numpy.bool_`` are Boolean, never Number.
    """
    if isinstance(value, bool) or _is_numpy_bool(value):
        return BOOLEAN
    if isinstance(value, numbers.Real):
        return NUMBER
    if isinstance(value, str):
        return TEXT
    if isinstance(value, ModelBundle):
        return MODEL
    if isinstance(value, Color):
        return COLOR
    if isinstance(value, Colormap):
        return COLORMAP
    if _has_class(value, "xarray", "DataArray"):
        return RASTER
    if _has_class(value, "geopandas", "GeoDataFrame"):
        return VECTOR
    if _has_class(value, "pandas", "DataFrame"):
        return TABLE
    return None


def as_output(value: object) -> object:
    """An output value as GeoKnit keeps it: ``numpy.bool_`` becomes ``bool``."""
    if _is_numpy_bool(value):
        return bool(value)  # type: ignore[call-overload]
    return value


def python_type_name(value: object) -> str:
    """Readable class name for error messages, e.g. ``pandas.DataFrame``."""
    cls = type(value)
    module = cls.__module__.split(".")[0]
    return cls.__name__ if module == "builtins" else f"{module}.{cls.__name__}"


def check_value(expected: str, value: object) -> str | None:
    """``None`` if ``value`` fits a port of type ``expected``, else an error message.

    No conversions: a ``bool`` is not a Number and ``0``/``1`` is not a Boolean.
    """
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

    Same type, an ``Any`` input, Number → Text, Boolean → Text, and an ``Any``
    output (Panel's pass-through, checked when the node runs).
    """
    return (
        out_type == in_type
        or in_type == ANY
        or out_type == ANY
        or (in_type == TEXT and out_type in TO_TEXT)
    )


TO_TEXT: tuple[str, ...] = (NUMBER, BOOLEAN)
"""Output types converted with ``str`` when wired into a Text input."""


def connection_error(out_type: str, in_type: str) -> str | None:
    """``None`` if the wire is allowed, else the tooltip text for refusing it."""
    if can_connect(out_type, in_type):
        return None
    return f"{out_type} can't connect to {in_type}"


def convert_for_input(value: object, in_type: str) -> object:
    """Apply the Number → Text and Boolean → Text conversions."""
    if in_type == TEXT and type_of(value) in TO_TEXT:
        return str(value)
    return value


# ── describe() ───────────────────────────────────────────────────────────────


def describe(value: object) -> str:
    """A short, metadata-only summary of ``value`` for Panels and tooltips."""
    kind = type_of(value)
    if kind in (NUMBER, TEXT, BOOLEAN):
        return str(as_output(value))
    if kind == COLOR:
        assert isinstance(value, Color)
        return f"Color {value.hex}"
    if kind == COLORMAP:
        assert isinstance(value, Colormap)
        return _describe_colormap(value)
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


def _describe_colormap(cm: Colormap) -> str:
    if cm.kind == CLASSES:
        n = len(cm.classes)
        other = f" · other {cm.other.hex}" if cm.other is not None else ""
        return f"Colormap · classes · {n} class{'es' if n != 1 else ''}{other}"
    name = cm.name if cm.is_named and cm.name else f"custom, {len(cm.stops)} stops"
    if cm.reverse:
        name += ", reversed"
    if cm.min is None and cm.max is None:
        span = "2–98 % stretch"
    else:
        lo = "2 %" if cm.min is None else f"{cm.min:g}"
        hi = "98 %" if cm.max is None else f"{cm.max:g}"
        span = f"{lo} to {hi}"
    return f"Colormap · continuous · {name} · {span}"


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
