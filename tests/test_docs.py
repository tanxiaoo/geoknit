"""The examples in docs/writing-components.md parse and run."""

import re
from pathlib import Path

import numpy as np
import rioxarray

from geoknit.core.component import HEADER_MARK, parse_component, run_component
from geoknit.helpers import RASTER_CHUNKS
from tests.conftest import ROOT

GUIDE = ROOT / "docs" / "writing-components.md"


def _components() -> list[str]:
    blocks = re.findall(r"```python\n(.*?)```", GUIDE.read_text(encoding="utf-8"), re.S)
    return [b for b in blocks if b.startswith(f"# {HEADER_MARK}")]


def test_every_component_in_the_guide_parses() -> None:
    sources = _components()
    assert sources, "the guide has no complete component"
    for source in sources:
        parse_component(source)


def test_the_first_example_runs(synthetic_data: dict[str, Path]) -> None:
    spec = parse_component(_components()[0])
    assert spec.name == "Normalized Difference"
    raster = rioxarray.open_rasterio(
        synthetic_data["predictors"], chunks=dict(RASTER_CHUNKS), masked=True
    )
    result = run_component(spec, {"raster": raster})
    assert result.ok, result.error
    index = result.outputs["index"]
    assert index.sizes["band"] == 1 and index.attrs["long_name"] == ("index",)
    assert index.rio.crs == raster.rio.crs
    a, b = raster.sel(band=8).values, raster.sel(band=4).values
    expected = (a - b) / (a + b)
    np.testing.assert_allclose(index.values[0], expected, rtol=1e-6, equal_nan=True)
    assert result.log == ["(A07 - A03) / (A07 + A03)"]
