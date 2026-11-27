"""Sampling tab: Stratified Sample, Random Sample, Extract Values, Split Points."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rioxarray
from shapely.geometry import Point

from geoknit.helpers import RASTER_CHUNKS
from tests.components.util import ok, run_builtin

IMD_BREAKS = "0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100"


@pytest.fixture(scope="module")
def layers(synthetic_data: dict[str, Path]) -> dict[str, object]:
    imd = rioxarray.open_rasterio(synthetic_data["imd"], chunks=dict(RASTER_CHUNKS), masked=True)
    classes = ok("raster/reclassify", raster=imd, breaks=IMD_BREAKS)["classes"]
    return {
        "imd": imd,
        "classes": classes,
        "predictors": rioxarray.open_rasterio(
            synthetic_data["predictors"], chunks=dict(RASTER_CHUNKS)
        ),
        "aoi": gpd.read_file(synthetic_data["aoi"]),
    }


def test_stratified_sample(layers: dict) -> None:
    out = ok(
        "sampling/stratified_sample",
        classes=layers["classes"],
        value=layers["imd"],
        aoi=layers["aoi"],
        n=10,
        seed=1,
    )
    points = out["points"]
    counts = points["cls"].value_counts().to_dict()
    assert set(counts) == {1, 2, 3, 4, 5, 6, 7}
    assert all(c == 10 for c in counts.values())
    assert points.crs.to_epsg() == 32632
    assert points.within(layers["aoi"].union_all()).all()
    # Pixel centres: x = 510000 + 10 k + 5.
    assert np.allclose((points.geometry.x - 510_005) % 10, 0)
    # The value is the IMD at that pixel; classes agree with the breaks.
    assert points.loc[points["cls"] == 1, "value"].eq(0).all()
    assert points.loc[points["cls"] == 7, "value"].eq(100).all()
    again = ok(
        "sampling/stratified_sample",
        classes=layers["classes"], value=layers["imd"], aoi=layers["aoi"], n=10, seed=1,
    )["points"]  # fmt: skip
    assert again.geometry.equals(points.geometry)  # same seed, same points


def test_stratified_sample_warns_for_small_classes(layers: dict) -> None:
    result = run_builtin(
        "sampling/stratified_sample",
        classes=layers["classes"], value=layers["imd"], aoi=layers["aoi"], n=5000, seed=0,
        value_field="IMD", class_field="klass",
    )  # fmt: skip
    assert result.ok, result.error
    assert any("has only" in line for line in result.log)
    assert {"IMD", "klass"} <= set(result.outputs["points"].columns)


def test_stratified_sample_needs_one_grid(layers: dict) -> None:
    coarse = layers["imd"].rio.reproject(layers["imd"].rio.crs, resolution=20)
    result = run_builtin(
        "sampling/stratified_sample",
        classes=layers["classes"], value=coarse, aoi=layers["aoi"], n=5, seed=0,
    )  # fmt: skip
    assert "same grid" in (result.error or "")


def test_random_sample_only_valid_pixels(layers: dict) -> None:
    points = ok("sampling/random_sample", raster=layers["imd"], aoi=layers["aoi"], n=300, seed=3)[
        "points"
    ]
    assert len(points) == 300
    assert points.within(layers["aoi"].union_all()).all()
    # None in the nodata block (top-left 20 × 20 px).
    in_block = (points.geometry.x < 510_200) & (points.geometry.y > 5_039_800)
    assert not in_block.any()


def test_extract_values(layers: dict, synthetic_data: dict[str, Path]) -> None:
    ref = gpd.read_file(synthetic_data["reference"])
    extra = gpd.GeoDataFrame(
        {"PLOTID": ["outside", "nodata"], "stratum": ["x", "x"], "imd_ref": [1.0, 1.0]},
        geometry=[Point(400_000, 5_000_000), Point(510_015, 5_039_985)],
        crs=32632,
    )
    points = pd.concat([ref, extra], ignore_index=True)
    result = run_builtin("sampling/extract_values", points=points, raster=layers["predictors"])
    assert result.ok, result.error
    table = result.outputs["table"]
    assert len(table) == 150
    assert list(table.columns) == ["PLOTID", "stratum", "imd_ref"] + [f"A{i:02d}" for i in range(8)]
    assert table.attrs["feature_columns"] == [f"A{i:02d}" for i in range(8)]
    assert any("1 points outside the raster and 1 on nodata" in line for line in result.log)
    # Value check against a direct read of the first point.
    p = ref.geometry.iloc[0]
    direct = layers["predictors"].sel(x=p.x, y=p.y, method="nearest").values
    assert np.allclose(table.loc[0, [f"A{i:02d}" for i in range(8)]].to_numpy(float), direct)


def test_split_points_splits_a_table_and_keeps_attrs() -> None:
    table = pd.DataFrame({"a": range(100), "cls": [i % 4 for i in range(100)]})
    table.attrs["feature_columns"] = ["a"]
    out = ok("sampling/split_points", data=table, test_fraction=0.25, stratify_by="cls")
    train, test = out["train"], out["test"]
    assert type(train) is pd.DataFrame and type(test) is pd.DataFrame
    assert (len(train), len(test)) == (75, 25)
    assert set(train["a"]).isdisjoint(test["a"])
    assert test["cls"].value_counts().tolist() == [7, 6, 6, 6] or test["cls"].nunique() == 4
    assert train.attrs["feature_columns"] == ["a"]
    assert test.attrs["feature_columns"] == ["a"]
    again = ok("sampling/split_points", data=table, test_fraction=0.25, stratify_by="cls")
    assert again["test"].equals(test)
    bad = run_builtin("sampling/split_points", data=table, stratify_by="nope")
    assert 'no column "nope"' in (bad.error or "")


def test_split_points_table_feeds_random_forest_auto_features() -> None:
    rng = np.random.default_rng(0)
    table = pd.DataFrame({"A00": rng.random(60), "A01": rng.random(60), "other": range(60)})
    table["IMD"] = 100 * table["A00"]
    table.attrs["feature_columns"] = ["A00", "A01"]
    train = ok("sampling/split_points", data=table)["train"]
    model = ok("model/random_forest", table=train, target="IMD", n_trees=10)["model"]
    assert model.feature_names == ["A00", "A01"]  # from attrs, not every numeric column


def test_split_points_holds_out_test_points(layers: dict) -> None:
    points = ok(
        "sampling/stratified_sample",
        classes=layers["classes"], value=layers["imd"], aoi=layers["aoi"], n=10, seed=1,
    )["points"]  # fmt: skip
    out = ok("sampling/split_points", data=points, stratify_by="cls")
    train, test = out["train"], out["test"]
    assert (len(train), len(test)) == (49, 21)
    assert train.crs == points.crs and test.crs == points.crs
    assert set(test["cls"]) == set(points["cls"])  # every class in the test part

    def keys(g: gpd.GeoDataFrame) -> set[tuple[float, float]]:
        return set(zip(g.geometry.x, g.geometry.y, strict=True))

    assert keys(train).isdisjoint(keys(test))
    assert keys(train) | keys(test) == keys(points)
    again = ok("sampling/split_points", data=points, stratify_by="cls")
    assert again["test"].geometry.equals(test.geometry)  # same seed, same split
    bad = run_builtin("sampling/split_points", data=points, test_fraction=1.5)
    assert "between 0 and 1" in (bad.error or "")
