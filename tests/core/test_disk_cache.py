"""Disk cache (SPEC 6 "Cache"): formats per type, read-raster references, LRU, clear."""

import os
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
from geoknit.core.cache import (
    CacheMiss,
    DiskCache,
    file_view_source,
    release_file_handles,
    split_port_key,
)

KEY = "a" * 64


def _tif(path: Path, *, nodata: float | None = -9999) -> Path:
    data = np.arange(2 * 10 * 20, dtype="float32").reshape(2, 10, 20)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=20,
        height=10,
        count=2,
        dtype="float32",
        crs="EPSG:32632",
        transform=from_origin(500000, 5000000, 10, 10),
        nodata=nodata,
    ) as ds:
        ds.write(data)
        ds.descriptions = ("red", "nir")
    return path


def _formats(cache: DiskCache, key: str = KEY) -> dict[str, str]:
    return {p: info["format"] for p, info in cache.meta(key)["ports"].items()}


def test_number_and_text_round_trip_as_json(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"n": 3.5, "t": "héllo\nworld"}, {"n": "3.5", "t": "héllo"})
    outputs, summaries = cache.read(KEY)
    assert outputs == {"n": 3.5, "t": "héllo\nworld"}
    assert summaries == {"n": "3.5", "t": "héllo"}
    assert _formats(cache) == {"n": "json", "t": "json"}


def test_vector_and_table_round_trip_as_parquet(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    gdf = gpd.GeoDataFrame({"imd": [10, 80]}, geometry=[Point(0, 0), Point(1, 1)], crs=32632)
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    cache.write(KEY, {"points": gdf, "table": df})
    outputs, _ = cache.read(KEY)
    assert _formats(cache) == {"points": "geoparquet", "table": "parquet"}
    assert outputs["points"].crs.to_epsg() == 32632
    assert outputs["points"].geometry.equals(gdf.geometry)
    pd.testing.assert_frame_equal(outputs["table"], df)


def test_table_that_parquet_refuses_falls_back_to_pickle(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    df = pd.DataFrame({"mixed": [1, "two", 3.0]})
    cache.write(KEY, {"table": df})
    assert _formats(cache) == {"table": "pickle"}
    pd.testing.assert_frame_equal(cache.read(KEY)[0]["table"], df)


def test_model_round_trips_with_joblib(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    model = types.ModelBundle(
        estimator={"coef": [1, 2]}, task="regression", target="imd", feature_names=["a", "b"]
    )
    cache.write(KEY, {"model": model})
    assert _formats(cache) == {"model": "joblib"}
    assert cache.read(KEY)[0]["model"] == model


def test_computed_raster_is_written_as_a_lazy_cog(tmp_path: Path) -> None:
    src = rioxarray.open_rasterio(_tif(tmp_path / "a.tif"), chunks=True, masked=True)
    computed = src * 2
    computed.attrs["long_name"] = ("red", "nir")
    assert file_view_source(computed) is None

    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"raster": computed})
    assert _formats(cache) == {"raster": "cog"}
    with rasterio.open(tmp_path / "cache" / KEY / "raster.tif") as ds:
        assert ds.profile["driver"] == "GTiff"  # a COG is a GTiff with a COG layout
        assert ds.tags(ns="IMAGE_STRUCTURE").get("LAYOUT") == "COG"
    back = cache.read(KEY)[0]["raster"]
    assert hasattr(back.data, "dask")  # still lazy
    assert types.raster_band_names(back) == ["red", "nir"]
    assert back.rio.crs.to_epsg() == 32632
    np.testing.assert_array_equal(back.values, computed.values)


def test_read_raster_is_referenced_not_copied(tmp_path: Path) -> None:
    path = _tif(tmp_path / "a.tif")
    for kw in ({"chunks": True}, {}):
        da = rioxarray.open_rasterio(path, **kw)
        assert file_view_source(da) == path
    assert file_view_source(rioxarray.open_rasterio(path, chunks=True).isel(x=slice(0, 5))) is None

    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"raster": rioxarray.open_rasterio(path, chunks=True)})
    assert _formats(cache) == {"raster": "ref"}
    assert not list((tmp_path / "cache" / KEY).glob("*.tif"))
    back = cache.read(KEY)[0]["raster"]
    assert types.raster_band_names(back) == ["red", "nir"]
    np.testing.assert_array_equal(back.values, rioxarray.open_rasterio(path).values)


def test_changed_source_file_makes_a_reference_miss(tmp_path: Path) -> None:
    path = _tif(tmp_path / "a.tif")
    cache = DiskCache(tmp_path / "cache")
    da = rioxarray.open_rasterio(path, chunks=True)
    cache.write(KEY, {"raster": da})
    da.close()  # Windows refuses to overwrite an open file
    _tif(path, nodata=0)  # rewritten
    with pytest.raises(CacheMiss):
        cache.read(KEY)
    assert not cache.has(KEY)


def test_lru_eviction_keeps_recent_entries(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", limit_bytes=10**9)
    keys = [c * 64 for c in "bcd"]
    for k in keys:
        cache.write(k, {"t": "x" * 2000})
    one = cache.entries()[0][1]
    cache.read(keys[0])  # b is now the most recently used
    cache.limit_bytes = 2 * one

    for k, age in zip(keys, (300, 200, 100), strict=True):  # make mtimes distinct
        meta = tmp_path / "cache" / k / "meta.json"
        t = meta.stat().st_mtime - age
        os.utime(meta, (t, t))
    os.utime(tmp_path / "cache" / keys[0] / "meta.json")  # b used last
    assert cache.evict() == [keys[1]]
    assert cache.has(keys[0]) and not cache.has(keys[1]) and cache.has(keys[2])


def test_write_never_evicts_the_entry_just_written(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", limit_bytes=1)
    cache.write(KEY, {"t": "big" * 100})
    assert cache.has(KEY)


def test_clear_and_damaged_entries(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"n": 1})
    (tmp_path / "cache" / KEY / "n.json").write_text("not json")
    with pytest.raises(CacheMiss):
        cache.read(KEY)
    cache.write(KEY, {"n": 1})
    cache.clear()
    assert cache.entries() == []
    with pytest.raises(CacheMiss):
        cache.read(KEY)


def test_failed_write_leaves_no_entry(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    with pytest.raises(TypeError, match="cannot cache"):
        cache.write(KEY, {"n": 1, "bad": object()})
    assert not cache.has(KEY)
    assert list((tmp_path / "cache").iterdir()) == []


def test_split_port_key() -> None:
    assert split_port_key(f"{KEY}.raster") == (KEY, "raster")


# ── Windows file locks ──


def _can_replace(path: Path) -> bool:
    try:
        _tif(path, nodata=0)
        return True
    except Exception:  # noqa: BLE001  (GDAL raises CPLE_AppDefinedError on a locked file)
        return False


def test_released_handles_unlock_files_and_lazy_rasters_reopen(tmp_path: Path) -> None:
    path = _tif(tmp_path / "a.tif")
    da = rioxarray.open_rasterio(path, chunks=True)
    doubled = da * 2
    _ = doubled.values  # make sure the file has really been opened
    # Whether an open raster blocks replacing it depends on the OS and the
    # GDAL / xarray versions (locked here on Windows, not on every CI runner).
    # What must hold: after releasing, it can always be replaced.
    locked = not _can_replace(path)
    closed = release_file_handles()
    assert closed >= 1 or not locked
    assert _can_replace(path)  # rewritten with the same pixel values
    np.testing.assert_array_equal(doubled.values, rioxarray.open_rasterio(path).values * 2)
    release_file_handles()


def test_removing_an_entry_with_an_open_file_invalidates_it_at_once(tmp_path: Path) -> None:
    src = rioxarray.open_rasterio(_tif(tmp_path / "a.tif"), chunks=True)
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"raster": src + 1})
    held = cache.read(KEY)[0]["raster"]
    _ = held.values  # the COG is now open (and locked on Windows)
    cache.remove(KEY)
    assert not cache.has(KEY)  # meta.json went first
    with pytest.raises(CacheMiss):
        cache.read(KEY)
    release_file_handles()
    cache.sweep()  # leftovers go once the file is closed
    assert not (tmp_path / "cache" / KEY).exists()
    cache.write(KEY, {"raster": src + 1})
    assert cache.has(KEY)
    release_file_handles()


def test_eviction_spares_protected_entries(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache", limit_bytes=1)
    held, other = "b" * 64, "c" * 64
    cache.write(held, {"t": "x" * 100})
    cache.write(other, {"t": "y" * 100}, protect={held})
    assert cache.has(held) and cache.has(other)  # above the limit, but both in use
    cache.evict(protect={other})
    assert not cache.has(held) and cache.has(other)


def test_clear_succeeds_while_lazy_rasters_from_the_cache_exist(tmp_path: Path) -> None:
    src = rioxarray.open_rasterio(_tif(tmp_path / "a.tif"), chunks=True)
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"raster": src + 1})
    held = cache.read(KEY)[0]["raster"]
    _ = held.values
    assert cache.clear() is True
    assert not (tmp_path / "cache").exists()


def test_sweep_removes_crashed_writes_but_not_complete_entries(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"n": 1})
    crashed = tmp_path / "cache" / f"{'d' * 64}.tmp-999999"
    crashed.mkdir()
    (crashed / "n.json").write_text("{}")
    cache.sweep()
    assert not crashed.exists()
    assert cache.has(KEY)


def test_integer_cog_overviews_keep_class_values(tmp_path: Path) -> None:
    """The Map Viewer shows overviews: classes must not blend into in-between values."""
    rng = np.random.default_rng(0)
    classes = rng.choice(np.array([1, 50, 200], dtype="uint8"), size=(1, 1200, 1200))
    raster = xr_raster(classes)
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"classes": raster})
    with rasterio.open(tmp_path / "cache" / KEY / "classes.tif") as ds:
        assert ds.overviews(1)
        level = ds.overviews(1)[0]
        small = ds.read(1, out_shape=(1200 // level, 1200 // level))
    assert set(np.unique(small)) <= {1, 50, 200}  # cubic or average would blend them


def test_read_port_and_port_info(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    cache.write(KEY, {"n": 3, "text": "hi"})
    entry, info = cache.port_info(f"{KEY}.text")
    assert entry == tmp_path / "cache" / KEY and info["type"] == "Text"
    assert cache.read_port(f"{KEY}.n") == 3
    with pytest.raises(CacheMiss):
        cache.port_info(f"{KEY}.missing")
    with pytest.raises(CacheMiss):
        cache.read_port(f"{'b' * 64}.n")


def xr_raster(data: np.ndarray) -> object:
    import xarray as xr

    _, h, w = data.shape
    da = xr.DataArray(
        data,
        dims=("band", "y", "x"),
        coords={
            "band": [1],
            "y": 5_000_000 - 10 * np.arange(h) - 5,
            "x": 500_000 + 10 * np.arange(w) + 5,
        },
    )
    return da.rio.write_crs("EPSG:32632")
