"""Vector tab: Read Vector, Write Vector, Reproject."""

from pathlib import Path

import geopandas as gpd
import pytest

from tests.components.util import ok, run_builtin


def test_read_vector(synthetic_data: dict[str, Path]) -> None:
    ref = ok("vector/read_vector", path=str(synthetic_data["reference"]))["vector"]
    assert len(ref) == 150
    assert {"PLOTID", "stratum", "imd_ref"} <= set(ref.columns)
    assert ref.crs.to_epsg() == 32632
    aoi = ok("vector/read_vector", path=str(synthetic_data["aoi"]), layer="aoi")["vector"]
    assert len(aoi) == 1


@pytest.mark.parametrize("name", ["out.gpkg", "out.geojson", "out.shp", "sub/out.parquet"])
def test_write_vector_round_trip(
    synthetic_data: dict[str, Path], tmp_path: Path, name: str
) -> None:
    ref = gpd.read_file(synthetic_data["reference"])
    out = ok("vector/write_vector", tmp_path, vector=ref, path=name)
    assert out["file"] == name
    ok("vector/write_vector", tmp_path, vector=ref.head(5), path=name)  # overwrite, not append
    back = ok("vector/read_vector", tmp_path, path=name)["vector"]
    assert len(back) == 5


def test_write_vector_unknown_extension(synthetic_data: dict[str, Path], tmp_path: Path) -> None:
    ref = gpd.read_file(synthetic_data["reference"])
    result = run_builtin("vector/write_vector", tmp_path, vector=ref, path="out.xyz")
    assert "cannot tell the format" in (result.error or "")


def test_reproject(synthetic_data: dict[str, Path]) -> None:
    ref = gpd.read_file(synthetic_data["reference"])
    out = ok("vector/reproject", vector=ref, crs="EPSG:4326")["reprojected"]
    assert out.crs.to_epsg() == 4326
    assert 8 < out.geometry.x.mean() < 10  # longitude near Milan
