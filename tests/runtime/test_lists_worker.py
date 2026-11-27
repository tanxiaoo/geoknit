"""List values through the worker process (change 01 step 3, SPEC 3 and 6)."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_SLIDER, Graph
from geoknit.runtime.client import WorkerExecutor
from tests.core.test_lists import COLLECT, NUMBERS

RASTERS = """\
# geoknit: component
# name: Rasters
# category: Test
# outputs:
#   rasters: {type: Raster, access: list}

# --- code ---
import numpy as np
import rioxarray  # noqa: F401
import xarray as xr

rasters = []
for i in range(3):
    da = xr.DataArray(
        np.full((2, 4, 5), i, dtype="float32"),
        dims=("band", "y", "x"),
        coords={"band": [1, 2], "y": 5000000 - np.arange(4) * 10.0,
                "x": 500000 + np.arange(5) * 10.0},
    ).rio.write_crs("EPSG:32632")
    da.attrs["long_name"] = (f"red{i}", f"nir{i}")
    rasters.append(da)
"""

BAND_NAMES = """\
# geoknit: component
# name: Band Names
# category: Test
# inputs:
#   rasters: {type: Raster, access: list}
# outputs:
#   names: Text

# --- settings ---
sep = ","

# --- code ---
from geoknit.core.types import raster_band_names

names = sep.join("/".join(raster_band_names(r)) for r in rasters)
names += sep + sep.join(str(float(r.values[0, 0, 0])) for r in rasters)
"""


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[tuple[Graph, WorkerExecutor]]:
    g = Graph()
    ex = WorkerExecutor(g, base_dir=tmp_path)
    yield g, ex
    ex.close()


def test_worker_concatenates_and_panel_shows_the_list(
    executor: tuple[Graph, WorkerExecutor],
) -> None:
    g, ex = executor
    nums = g.add_component(INLINE, source=NUMBERS).id
    seven = g.add_component(PARAM_SLIDER).id
    g.set_value(seven, 7)
    coll = g.add_component(INLINE, source=COLLECT).id
    g.add_wire(nums, "values", coll, "items")
    g.add_wire(seven, "value", coll, "items")
    shown = g.add_component(PARAM_PANEL).id
    g.add_wire(coll, "got", shown, "data")
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(nums, "values", panel, "data")
    # Through the Panel the list still concatenates into a list input.
    coll2 = g.add_component(INLINE, source=COLLECT).id
    g.add_wire(seven, "value", coll2, "items")
    g.add_wire(panel, "data", coll2, "items")
    shown2 = g.add_component(PARAM_PANEL).id
    g.add_wire(coll2, "got", shown2, "data")

    assert ex.run().ok, ex.errors
    assert ex.summaries[shown]["data"] == "[3, 1, 2, 7]"
    assert ex.summaries[shown2]["data"] == "[7, 3, 1, 2]"
    assert ex.summaries[panel]["data"] == "list of 3 Number\n[0] 3\n[1] 1\n[2] 2"


def test_list_of_rasters_survives_a_worker_restart(
    executor: tuple[Graph, WorkerExecutor], tmp_path: Path
) -> None:
    """Done when: a list of 3 Rasters comes back from the disk cache with its band names."""
    g, ex = executor
    make = g.add_component(INLINE, source=RASTERS).id
    names = g.add_component(INLINE, source=BAND_NAMES).id
    g.add_wire(make, "rasters", names, "rasters")
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(make, "rasters", panel, "data")
    assert ex.run().ok, ex.errors
    first = ex.summaries[names]["names"]
    assert first == "red0/nir0,red1/nir1,red2/nir2,0.0,1.0,2.0"
    summary = ex.summaries[panel]["data"].splitlines()
    assert summary[0] == "list of 3 Raster"
    assert summary[1].startswith("[0] Raster · 2 bands: red0, nir0")

    ex.restart()  # worker memory is gone; the disk cache stays
    g.set_setting(names, "sep", ";")  # only Band Names runs again
    report = ex.run()
    assert report.ok, ex.errors
    assert report.ran == [names] and make not in report.ran
    assert ex.summaries[names]["names"] == first.replace(",", ";")
    entry = next((tmp_path / ".geoknit" / "cache").glob("*/rasters/index.json"))
    assert sorted(f.name for f in entry.parent.iterdir()) == [
        "0.tif", "1.tif", "2.tif", "index.json",
    ]  # fmt: skip
