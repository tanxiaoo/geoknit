"""Raster tab: Read/Write Raster, Reclassify, Clip, Align Raster, Band Select."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import rioxarray
import xarray as xr
from shapely.geometry import box

from geoknit.core.cache import file_view_source
from geoknit.core.types import raster_band_names
from tests.components.util import ok, run_builtin

IMD_BREAKS = "0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100"


def _read(path: Path, **settings: object) -> xr.DataArray:
    return ok("raster/read_raster", path=str(path), **settings)["raster"]


def _grid(values: list[float]) -> xr.DataArray:
    """A 1 × 1 × n float raster in EPSG:32632."""
    da = xr.DataArray(
        np.array(values, dtype="float32").reshape(1, 1, -1),
        dims=("band", "y", "x"),
        coords={
            "band": [1],
            "y": [5000005.0],
            "x": [500005.0 + 10 * i for i in range(len(values))],
        },
    )
    return da.rio.write_crs("EPSG:32632")


def test_read_raster_is_lazy_and_keeps_band_names(synthetic_data: dict[str, Path]) -> None:
    raster = _read(synthetic_data["predictors"])
    assert hasattr(raster.data, "dask")
    assert raster_band_names(raster) == [f"A{i:02d}" for i in range(8)]
    assert file_view_source(raster) is not None  # the cache stores a reference, not a copy
    imd = _read(synthetic_data["imd"])
    assert float(imd.max()) == 100.0 and bool(np.isnan(imd.values).any())  # masked nodata


def test_read_raster_band_selection(synthetic_data: dict[str, Path]) -> None:
    raster = _read(synthetic_data["predictors"], bands="A03,2")
    assert raster_band_names(raster) == ["A03", "A01"]
    result = run_builtin("raster/read_raster", path=str(synthetic_data["predictors"]), bands="A99")
    assert "no band A99" in (result.error or "")


def test_reclassify_imd_breaks() -> None:
    """PLAN Phase 3: classes 1–7, values at 0, 20, 20.5 and 100."""
    raster = _grid([0, 20, 20.5, 100, 55, np.nan, 120])
    classes = ok("raster/reclassify", raster=raster, breaks=IMD_BREAKS)["classes"]
    assert classes.dtype == np.uint8
    assert classes.values.ravel().tolist() == [1, 2, 3, 7, 4, 0, 0]
    assert classes.rio.nodata == 0
    assert classes.rio.crs.to_epsg() == 32632


def test_reclassify_is_lazy_on_the_synthetic_raster(synthetic_data: dict[str, Path]) -> None:
    classes = ok("raster/reclassify", raster=_read(synthetic_data["imd"]), breaks=IMD_BREAKS)[
        "classes"
    ]
    assert hasattr(classes.data, "dask")
    values = set(np.unique(classes.values).tolist())
    assert values == {0, 1, 2, 3, 4, 5, 6, 7}  # 0 = the nodata block


def test_reclassify_keep_and_bad_breaks() -> None:
    raster = _grid([5, 500])
    classes = ok("raster/reclassify", raster=raster, breaks="0-10", no_match="keep")["classes"]
    assert classes.values.ravel().tolist() == [1, 0]
    assert classes.rio.nodata is None
    result = run_builtin("raster/reclassify", raster=raster, breaks="0-10 | x")
    assert 'break rule 2 "x"' in (result.error or "")


def test_write_raster_writes_a_cog(synthetic_data: dict[str, Path], tmp_path: Path) -> None:
    raster = _read(synthetic_data["predictors"])
    out = ok("raster/write_raster", tmp_path, map=raster, path="outputs/p.tif")
    assert out["file"] == "outputs/p.tif"
    written = rioxarray.open_rasterio(tmp_path / "outputs" / "p.tif")
    assert raster_band_names(written) == raster_band_names(raster)
    import rasterio

    with rasterio.open(tmp_path / "outputs" / "p.tif") as ds:
        assert ds.overviews(1) or ds.width <= 512  # small files may have no overview
        assert ds.profile.get("tiled", False) or ds.block_shapes[0][0] > 1
    assert np.allclose(written.values, raster.values, equal_nan=True)


def test_clip_to_aoi(synthetic_data: dict[str, Path]) -> None:
    raster = _read(synthetic_data["imd"])
    aoi = gpd.GeoDataFrame(geometry=[box(510_500, 5_039_000, 511_000, 5_039_500)], crs=32632)
    clipped = ok("raster/clip", raster=raster, aoi=aoi.to_crs(4326))["clipped"]
    assert clipped.sizes["x"] in (50, 51) and clipped.sizes["y"] in (50, 51)
    assert raster_band_names(clipped) == ["IMD"]


def test_align_raster_to_a_coarser_grid(synthetic_data: dict[str, Path]) -> None:
    source = _read(synthetic_data["imd"])
    reference = source.rio.reproject(source.rio.crs, resolution=20)
    aligned = ok("raster/align_raster", source=source, reference=reference, resampling="average")[
        "raster"
    ]
    assert aligned.sizes == reference.sizes
    assert aligned.rio.transform() == reference.rio.transform()


def test_band_select(synthetic_data: dict[str, Path]) -> None:
    raster = _read(synthetic_data["predictors"])
    selected = ok("raster/band_select", raster=raster, bands="A07, A00")["selected"]
    assert raster_band_names(selected) == ["A07", "A00"]
    assert np.allclose(selected.values[0], raster.values[7], equal_nan=True)
    result = run_builtin("raster/band_select", raster=raster, bands="9")
    assert "no band 9" in (result.error or "")
