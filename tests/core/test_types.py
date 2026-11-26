"""Data types, connection rules and describe() (SPEC 3, change 01)."""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
import rioxarray
from rasterio.transform import from_origin
from shapely.geometry import Point

from geoknit.core import types
from geoknit.core.types import (
    Color,
    Colormap,
    ModelBundle,
    can_connect,
    check_value,
    describe,
    type_of,
)


def _tif(path: Path) -> Path:
    data = np.arange(2 * 4 * 5, dtype="float32").reshape(2, 4, 5)
    with rasterio.open(
        path, "w", driver="GTiff", width=5, height=4, count=2, dtype="float32",
        crs="EPSG:32632", transform=from_origin(500000, 5000000, 10, 10), nodata=-9999,
    ) as dst:  # fmt: skip
        dst.write(data)
        dst.descriptions = ("A00", "A01")
    return path


def test_type_of_each_kind(tmp_path: Path) -> None:
    raster = rioxarray.open_rasterio(_tif(tmp_path / "r.tif"))
    gdf = gpd.GeoDataFrame({"v": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")
    assert type_of(3) == type_of(2.5) == type_of(np.float32(1)) == "Number"
    assert type_of(True) == type_of(np.bool_(False)) == "Boolean"
    assert type_of("x") == "Text"
    assert type_of(raster) == "Raster"
    assert type_of(gdf) == "Vector"
    assert type_of(pd.DataFrame({"a": [1]})) == "Table"
    assert type_of(ModelBundle(object(), "regression", "IMD", ["A00"])) == "Model"
    assert check_value("Vector", pd.DataFrame()) == "expected Vector, got Table"
    assert check_value("Number", [1]) == "expected Number, got list"
    assert check_value("Any", object()) is None


def test_connection_rules() -> None:
    assert can_connect("Raster", "Raster")
    assert can_connect("Number", "Text")
    assert can_connect("Table", "Any")
    assert not can_connect("Text", "Number")
    assert types.connection_error("Raster", "Number") == "Raster can't connect to Number"
    assert types.convert_for_input(300, "Text") == "300"
    assert can_connect("Boolean", "Text")
    assert not can_connect("Boolean", "Number") and not can_connect("Number", "Boolean")
    assert types.convert_for_input(True, "Text") == "True"
    assert types.convert_for_input(np.bool_(True), "Text") == "True"


def test_boolean_is_not_a_number() -> None:
    assert check_value("Number", True) == "expected Number, got Boolean"
    assert check_value("Boolean", 1) == "expected Boolean, got Number"
    assert check_value("Boolean", 0.0) == "expected Boolean, got Number"
    assert check_value("Boolean", np.float64(2) > 1) is None
    assert types.as_output(np.float64(2) > 1) is True
    assert describe(False) == "False" and describe(np.bool_(True)) == "True"


def test_color_parse() -> None:
    assert Color.parse("#0b7a7c") == Color("#0B7A7C")
    assert Color.parse("#0B7A7CFF").hex == "#0B7A7CFF"
    assert Color.parse("11,122,124") == Color("#0B7A7C")
    assert Color.parse(" 11, 122, 124, 128 ").hex == "#0B7A7C80"
    assert Color("#0b7a7c").rgba == (11, 122, 124, 255)
    for bad in ("teal", "#0B7A7", "0B7A7C", "11,122", "11,122,256", "-1,0,0", "#0B7A7C0"):
        with pytest.raises(ValueError, match="#RRGGBB"):
            Color.parse(bad)
    assert Color.from_json(Color.parse("#0b7a7c").to_json()) == Color("#0B7A7C")
    assert type_of(Color("#000000")) == "Color"
    assert describe(Color.parse("11,122,124")) == "Color #0B7A7C"


def test_colormap_json_round_trip() -> None:
    viridis = Colormap.named("viridis")
    assert len(viridis.stops) == 11 and viridis.stops[0] == (0.0, Color("#440154"))
    assert viridis.to_json() == {
        "kind": "continuous", "name": "viridis", "min": None, "max": None, "reverse": False,
    }  # fmt: skip
    custom = Colormap(
        "continuous", stops=((0, "#000000"), (0.5, Color("#808080")), (1, "255,255,255")),
        min=0, max=100, reverse=True,
    )  # fmt: skip
    classes = Colormap(
        "classes", classes=((1, "#FF0000", "built"), (2, "#00FF00", "green")), other="#00000080"
    )
    for cm in (viridis, Colormap.named("magma", reverse=True), custom, classes):
        data = json.loads(json.dumps(cm.to_json()))
        assert Colormap.from_json(data) == cm
        assert type_of(cm) == "Colormap"
    assert describe(viridis) == "Colormap · continuous · viridis · 2–98 % stretch"
    assert describe(custom) == "Colormap · continuous · custom, 3 stops, reversed · 0 to 100"
    assert describe(classes) == "Colormap · classes · 2 classes · other #00000080"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"kind": "steps"}, "kind must be"),
        ({"kind": "continuous", "name": "jet"}, 'unknown colormap "jet"'),
        ({"kind": "continuous", "stops": ((0, "#000000"),)}, "at least 2 stops"),
        ({"kind": "continuous", "stops": ((1, "#000000"), (0, "#FFFFFF"))}, "in order"),
        ({"kind": "continuous", "name": "viridis", "min": 5, "max": 1}, "less than max"),
        ({"kind": "classes"}, "at least one class"),
        ({"kind": "classes", "classes": ((True, "#000000", "x"),)}, "not a number"),
        ({"kind": "classes", "classes": ((1, "#000", "a"),)}, "not a colour"),
        ({"kind": "classes", "classes": ((1, "#000000", "a"), (1, "#FFFFFF", "b"))}, "twice"),
    ],
)
def test_colormap_refuses(kwargs: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Colormap(**kwargs)


def test_colormap_from_json_refuses_unknown_keys() -> None:
    with pytest.raises(ValueError, match='unknown colormap key "colour"'):
        Colormap.from_json({"kind": "continuous", "name": "viridis", "colour": 1})


def test_describe_raster_reads_no_pixels(tmp_path: Path) -> None:
    raster = rioxarray.open_rasterio(_tif(tmp_path / "r.tif"), masked=True)
    text = describe(raster)
    assert not raster.variable._in_memory
    assert "2 bands: A00, A01" in text
    assert "5 × 4 px" in text and "resolution 10 × 10" in text
    assert "EPSG:32632" in text and "nodata -9999" in text


def test_describe_vector_table_model_scalars() -> None:
    gdf = gpd.GeoDataFrame(
        {"IMD": [10.0, 20.0]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:32632"
    )
    assert describe(gdf).splitlines() == [
        "Vector · 2 features · Point",
        "CRS EPSG:32632",
        "columns: IMD",
    ]
    assert describe(pd.DataFrame({"a": range(10)})).startswith("Table · 10 rows × 1 columns")

    class Est:
        def get_params(self, deep: bool = False) -> dict[str, object]:
            return {"n_estimators": 300}

    model = describe(ModelBundle(Est(), "regression", "IMD", ["A00", "A01"]))
    assert "Model · Est · regression" in model and "n_estimators=300" in model
    assert describe(4.5) == "4.5" and describe("a\nb") == "a\nb"
    with pytest.raises(ValueError):
        ModelBundle(Est(), "clustering", "IMD", [])
