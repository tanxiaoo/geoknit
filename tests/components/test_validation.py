"""Validation tab: Accuracy, Confusion Matrix; Script tab: Python."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rioxarray
import xarray as xr
from shapely.geometry import Point

from geoknit.helpers import RASTER_CHUNKS
from tests.components.util import ok, run_builtin


@pytest.fixture(scope="module")
def imd(synthetic_data: dict[str, Path]) -> xr.DataArray:
    return rioxarray.open_rasterio(synthetic_data["imd"], chunks=dict(RASTER_CHUNKS), masked=True)


def _points(xs: list[float], ys: list[float], **fields: list[object]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        fields, geometry=[Point(x, y) for x, y in zip(xs, ys, strict=True)], crs=32632
    )


def test_accuracy_against_known_errors(imd: xr.DataArray) -> None:
    xs = [510_505.0, 510_995.0, 511_505.0, 511_905.0]
    ys = [5_039_005.0, 5_038_505.0, 5_038_205.0, 5_039_505.0]
    truth = [imd.sel(x=x, y=y, method="nearest").values.item() for x, y in zip(xs, ys, strict=True)]
    observed = [t + d for t, d in zip(truth, [2.0, -2.0, 4.0, 0.0], strict=True)]
    ref = _points(
        xs + [400_000.0, 510_015.0, 510_605.0],
        ys + [5_000_000.0, 5_039_985.0, 5_039_005.0],
        imd_ref=observed + [1.0, 1.0, None],
    )  # + one outside, one on nodata, one without a value
    result = run_builtin("validation/accuracy", map=imd, reference=ref, field="imd_ref")
    assert result.ok, result.error
    m = result.outputs["metrics"].iloc[0]
    assert list(result.outputs["metrics"].columns) == ["n", "dropped", "RMSE", "MAE", "R²", "bias"]
    assert (m["n"], m["dropped"]) == (4, 3)
    assert m["RMSE"] == pytest.approx(np.sqrt((4 + 4 + 16) / 4))
    assert m["MAE"] == pytest.approx(2.0)
    assert m["bias"] == pytest.approx(1.0)  # observed − predicted
    obs = np.array(observed)
    r2 = 1 - 24 / np.sum((obs - obs.mean()) ** 2)
    assert m["R²"] == pytest.approx(r2)
    assert any("1 outside the map, 1 on nodata, 1 without a value" in line for line in result.log)


def test_accuracy_reprojects_reference_and_checks_field(imd: xr.DataArray) -> None:
    ref = _points([510_505.0], [5_039_005.0], v=[50.0]).to_crs(4326)
    m = ok("validation/accuracy", map=imd, reference=ref, field="v")["metrics"]
    assert m.loc[0, "n"] == 1
    bad = run_builtin("validation/accuracy", map=imd, reference=ref, field="nope")
    assert 'no field "nope"' in (bad.error or "")


def test_confusion_matrix(imd: xr.DataArray) -> None:
    classes = ok("raster/reclassify", raster=imd, breaks="0-50 | 50-100")["classes"]
    sample = ok(
        "sampling/stratified_sample",
        classes=classes, value=imd,
        aoi=gpd.GeoDataFrame(geometry=[Point(511_000, 5_039_000).buffer(900)], crs=32632),
        n=5, seed=0,
    )["points"]  # fmt: skip
    ref = sample.assign(truth=sample["cls"])
    ref.loc[ref.index[0], "truth"] = 2 if ref.loc[ref.index[0], "cls"] == 1 else 1  # one mistake
    out = ok("validation/confusion_matrix", map=classes, reference=ref, field="truth")
    matrix = out["matrix"].set_index("reference \\ map")
    assert int(np.trace(matrix.to_numpy())) == 9 and int(matrix.to_numpy().sum()) == 10
    metrics = out["metrics"]
    assert list(metrics["metric"][:2]) == ["overall accuracy", "kappa"]
    assert metrics.loc[0, "value"] == pytest.approx(0.9)
    assert 0.7 < metrics.loc[1, "value"] < 0.9
    f1 = metrics[metrics["metric"] == "F1"]
    assert list(f1["class"]) == ["1", "2"]


def test_confusion_matrix_text_reference(imd: xr.DataArray) -> None:
    classes = ok("raster/reclassify", raster=imd, breaks="0-50 | 50-100")["classes"]
    ref = _points([510_505.0, 510_995.0], [5_039_005.0, 5_038_505.0], label=["1", "2"])
    out = ok("validation/confusion_matrix", map=classes, reference=ref, field="label")
    assert set(out["matrix"].columns) - {"reference \\ map"} <= {"1", "2"}


def test_python_template_prints_to_out() -> None:
    result = run_builtin("script/python")
    assert result.ok, result.error
    assert result.outputs["out"] == "hello from GeoKnit\n"
    assert isinstance(pd.DataFrame(), pd.DataFrame)
