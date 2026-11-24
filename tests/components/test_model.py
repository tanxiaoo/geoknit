"""Model tab: Random Forest, SVM, Predict Raster."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rioxarray
import xarray as xr

from geoknit.core.types import ModelBundle, raster_band_names
from geoknit.helpers import RASTER_CHUNKS
from tests.components.util import ok, run_builtin

BANDS = [f"A{i:02d}" for i in range(8)]


@pytest.fixture(scope="module")
def predictors(synthetic_data: dict[str, Path]) -> xr.DataArray:
    return rioxarray.open_rasterio(synthetic_data["predictors"], chunks=dict(RASTER_CHUNKS))


@pytest.fixture(scope="module")
def training(synthetic_data: dict[str, Path], predictors: xr.DataArray) -> pd.DataFrame:
    """The reference points with their predictor values."""
    ref = gpd.read_file(synthetic_data["reference"])
    return ok("sampling/extract_values", points=ref, raster=predictors)["table"]


def test_random_forest_regression(training: pd.DataFrame) -> None:
    result = run_builtin("model/random_forest", table=training, target="imd_ref", n_trees=50)
    assert result.ok, result.error
    model = result.outputs["model"]
    assert isinstance(model, ModelBundle)
    assert (model.task, model.target, model.feature_names) == ("regression", "imd_ref", BANDS)
    assert model.info["n_samples"] == 150
    assert model.info["oob_score"] > 0.5  # the predictors carry the IMD signal
    assert model.estimator.n_estimators == 50
    assert any("out-of-bag" in line for line in result.log)
    again = ok("model/random_forest", table=training, target="imd_ref", n_trees=50)["model"]
    assert np.array_equal(  # same seed, same forest
        again.estimator.predict(training[BANDS].to_numpy()),
        model.estimator.predict(training[BANDS].to_numpy()),
    )


def test_random_forest_features_and_classification(training: pd.DataFrame) -> None:
    out = ok(
        "model/random_forest",
        table=training, target="stratum", task="classification", features="A00, A01", max_depth=4,
    )  # fmt: skip
    model = out["model"]
    assert model.feature_names == ["A00", "A01"]
    assert model.estimator.max_depth == 4
    assert set(model.estimator.classes_) <= {f"IMD_Class_{i}" for i in range(1, 6)}
    plain = training.copy()
    plain.attrs = {}  # without feature_columns: numeric columns except the target
    model = ok("model/random_forest", table=plain, target="imd_ref", n_trees=5)["model"]
    assert model.feature_names == BANDS
    bad = run_builtin("model/random_forest", table=training, target="nope")
    assert 'no target column "nope"' in (bad.error or "")


@pytest.mark.parametrize("task", ["regression", "classification"])
def test_svm(training: pd.DataFrame, task: str) -> None:
    target = "imd_ref" if task == "regression" else "stratum"
    model = ok("model/svm", table=training, target=target, task=task, C=10.0)["model"]
    assert model.task == task and model.feature_names == BANDS
    assert type(model.estimator).__name__ == "Pipeline"  # standardize=True
    raw = ok("model/svm", table=training, target=target, task=task, standardize=False)["model"]
    assert type(raw.estimator).__name__ in ("SVR", "SVC")


def test_predict_raster_regression(training: pd.DataFrame, predictors: xr.DataArray) -> None:
    model = ok("model/random_forest", table=training, target="imd_ref", n_trees=20)["model"]
    result = ok("model/predict_raster", model=model, raster=predictors, window=64)["map"]
    assert hasattr(result.data, "dask")  # lazy until written
    assert result.data.chunks[1][0] == 64
    assert result.dtype == np.float32
    assert raster_band_names(result) == ["imd_ref"]
    assert result.rio.crs.to_epsg() == 32632
    assert result.rio.transform() == predictors.rio.transform()
    values = result.values
    assert np.isnan(values[0, :20, :20]).all()  # nodata block of the predictors
    window = predictors.isel(x=slice(100, 104), y=slice(100, 104)).values
    expected = model.estimator.predict(window.reshape(8, -1).T).reshape(4, 4)
    assert np.allclose(values[0, 100:104, 100:104], expected)


def test_predict_raster_uses_bands_by_name(
    training: pd.DataFrame, predictors: xr.DataArray
) -> None:
    model = ok(
        "model/random_forest", table=training, target="imd_ref", n_trees=5, features="A05,A02"
    )["model"]
    reordered = predictors.isel(band=[7, 5, 2, 0])
    reordered.attrs["long_name"] = ("A07", "A05", "A02", "A00")
    result = ok("model/predict_raster", model=model, raster=reordered)["map"].values
    pixels = predictors.isel(band=[5, 2], x=slice(50, 52), y=slice(50, 52)).values
    assert np.allclose(
        result[0, 50:52, 50:52], model.estimator.predict(pixels.reshape(2, -1).T).reshape(2, 2)
    )


def test_predict_raster_missing_band_is_named(
    training: pd.DataFrame, predictors: xr.DataArray
) -> None:
    """PLAN Phase 3: a raster with a missing band fails with a message naming it."""
    model = ok("model/random_forest", table=training, target="imd_ref", n_trees=5)["model"]
    seven = predictors.isel(band=[0, 1, 2, 4, 5, 6, 7])
    seven.attrs["long_name"] = tuple(b for b in BANDS if b != "A03")
    result = run_builtin("model/predict_raster", model=model, raster=seven)
    assert not result.ok
    assert "the raster has no band A03" in (result.error or "")


def test_predict_raster_classification(training: pd.DataFrame, predictors: xr.DataArray) -> None:
    numeric = training.assign(cls=training["stratum"].str[-1].astype(int))
    model = ok(
        "model/random_forest", table=numeric, target="cls", task="classification", n_trees=10
    )["model"]
    classes = ok("model/predict_raster", model=model, raster=predictors)["map"]
    assert classes.dtype == np.uint8
    values = classes.values
    assert (values[0, :20, :20] == 0).all()  # nodata
    assert set(np.unique(values[0, 20:, 20:])) <= {1, 2, 3, 4, 5}
    text_model = ok(
        "model/random_forest", table=training, target="stratum", task="classification", n_trees=5
    )["model"]
    result = run_builtin("model/predict_raster", model=text_model, raster=predictors)
    assert result.ok, result.error
    assert any("1 = IMD_Class_1" in line for line in result.log)
    assert set(np.unique(result.outputs["map"].values)) <= {0, 1, 2, 3, 4, 5}
