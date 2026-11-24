"""Shared test setup."""

import importlib.util
import os
from collections.abc import Callable
from pathlib import Path

import pytest

# A system PROJ/GDAL install (e.g. PostGIS) can point these at old data files
# that the rasterio/pyproj wheels cannot use; the wheels ship their own.
for _var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
    os.environ.pop(_var, None)

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "examples" / "synthetic"


def load_script(path: Path, name: str) -> object:
    """Load an example script (not a package) as a module."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_make_data() -> Callable[..., dict[str, Path]]:
    return load_script(SYNTHETIC / "make_data.py", "make_data").make_data  # type: ignore[attr-defined]


@pytest.fixture(scope="session")
def synthetic_data(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """The synthetic rasters and vectors, generated once per test session."""
    return load_make_data()(tmp_path_factory.mktemp("synthetic"))
