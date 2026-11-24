"""Data types, connection rules and describe() (SPEC 3)."""

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
from geoknit.core.types import ModelBundle, can_connect, check_value, describe, type_of


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
    assert type_of(True) is None
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
