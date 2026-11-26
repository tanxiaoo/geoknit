"""The named ramps in ``geoknit.core.types`` sample the Map Viewer's tables (change 01)."""

import pytest

from geoknit.core.types import NAMED_RAMPS, Colormap
from geoknit.server import tiles


def test_named_ramps_are_the_map_viewer_colormaps() -> None:
    assert tuple(NAMED_RAMPS) == tiles.COLORMAPS


@pytest.mark.parametrize("name", tiles.COLORMAPS)
def test_stops_sample_rio_tiler_tables(name: str) -> None:
    lut = tiles._lut(name)
    stops = Colormap.named(name).stops
    assert len(stops) == 11
    for position, color in stops:
        expected = lut[round(position * 255)][:3]
        got = color.rgba[:3]
        assert all(abs(int(a) - int(b)) <= 1 for a, b in zip(got, expected, strict=True)), (
            f"{name} at {position}: {color.hex} vs {expected}"
        )
