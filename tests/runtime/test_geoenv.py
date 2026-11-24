"""The worker ignores a system PROJ / GDAL install (e.g. PostGIS setting PROJ_LIB)."""

import subprocess
import sys
from pathlib import Path

import pytest

from geoknit.core.graph import INLINE, Graph
from geoknit.runtime.client import WorkerExecutor
from geoknit.runtime.geoenv import use_bundled_geo_data

CRS_WORK = """\
# geoknit: component
# name: CRS Work
# category: Script
# outputs:
#   lon: Number
#   epsg: Number
#   crs: Text

# --- code ---
import numpy as np
import pyproj
import rasterio
import rioxarray
from rasterio.transform import from_origin

# Write a small raster in UTM 32N, read it, reproject it to WGS84.
with rasterio.open(
    "utm.tif", "w", driver="GTiff", width=4, height=4, count=1, dtype="uint8",
    crs="EPSG:32632", transform=from_origin(514000, 5034000, 10, 10),
) as ds:
    ds.write(np.ones((1, 4, 4), dtype="uint8"))
da = rioxarray.open_rasterio("utm.tif")
wgs = da.rio.reproject("EPSG:4326")
epsg = wgs.rio.crs.to_epsg()
da.close()

t = pyproj.Transformer.from_crs(32632, 4326, always_xy=True)
lon, _ = t.transform(514000, 5034000)
crs = pyproj.CRS.from_epsg(32632).name
"""


def _broken_geo_install(root: Path) -> tuple[Path, Path]:
    """Folders that look like an old system PROJ / GDAL data install."""
    proj = root / "old_proj"
    proj.mkdir()
    (proj / "proj.db").write_bytes(b"not a PROJ database")
    gdal = root / "old_gdal"
    gdal.mkdir()
    return proj, gdal


def test_rule_removes_only_what_the_wheel_replaces() -> None:
    env = {"PROJ_LIB": "x", "PROJ_DATA": "y", "GDAL_DATA": "z", "PATH": "p"}
    removed = use_bundled_geo_data(env)
    assert removed == {"PROJ_LIB": "x", "PROJ_DATA": "y", "GDAL_DATA": "z"}
    assert env == {"PATH": "p"}


def test_importing_the_worker_does_not_import_rasterio() -> None:
    """Otherwise the clean-up in worker_main would come too late."""
    code = "import sys, geoknit.runtime.worker; print('rasterio' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_broken_install_really_breaks_rasterio_without_the_fix(tmp_path: Path) -> None:
    """Guards the test below: the fake install must reproduce the failure."""
    proj, gdal = _broken_geo_install(tmp_path)
    code = "import rasterio.crs; rasterio.crs.CRS.from_epsg(32632)"
    env = {**__import__("os").environ, "PROJ_LIB": str(proj), "GDAL_DATA": str(gdal)}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert result.returncode != 0
    assert "proj" in result.stderr.lower()


def test_crs_operations_work_in_a_real_worker_despite_a_system_proj(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proj, gdal = _broken_geo_install(tmp_path)
    monkeypatch.setenv("PROJ_LIB", str(proj))
    monkeypatch.setenv("PROJ_DATA", str(proj))
    monkeypatch.setenv("GDAL_DATA", str(gdal))

    g = Graph()
    nid = g.add_component(INLINE, source=CRS_WORK).id
    with WorkerExecutor(g, base_dir=tmp_path, use_disk_cache=False) as ex:
        report = ex.run()
    assert report.ok, ex.errors
    assert ex.summaries[nid]["epsg"] == "4326"
    assert ex.summaries[nid]["crs"] == "WGS 84 / UTM zone 32N"
    assert 9.1 < float(ex.summaries[nid]["lon"]) < 9.3  # near Milan
