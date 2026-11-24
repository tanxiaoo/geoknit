"""Make the geo wheels use the PROJ / GDAL data they ship with.

A system install (PostGIS, QGIS, OSGeo4W, …) often sets ``PROJ_LIB``,
``PROJ_DATA`` or ``GDAL_DATA`` globally. rasterio prefers those variables over
its bundled data, so a ``proj.db`` from an older PROJ makes every CRS operation
fail ("proj.db contains DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 5
is expected"). GeoKnit uses the geo stack from wheels only (CLAUDE.md), so when
the rasterio wheel bundles its own data these variables are removed from the
process before rasterio is imported. A non-wheel install (e.g. conda), which
needs them, is left alone.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

GEO_DATA_VARS: dict[str, str] = {
    "PROJ_LIB": "proj_data",
    "PROJ_DATA": "proj_data",
    "GDAL_DATA": "gdal_data",
}
"""Environment variable → folder inside the rasterio wheel that replaces it."""


def _package_dir(name: str) -> Path | None:
    spec = importlib.util.find_spec(name)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def use_bundled_geo_data(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Remove the variables the rasterio wheel has its own data for.

    Returns the removed variables and their old values. Call it before
    rasterio is imported in the process.
    """
    env = os.environ if environ is None else environ
    rasterio_dir = _package_dir("rasterio")
    removed: dict[str, str] = {}
    if rasterio_dir is None:
        return removed
    for var, folder in GEO_DATA_VARS.items():
        if var in env and (rasterio_dir / folder).is_dir():
            removed[var] = env.pop(var)
    return removed
