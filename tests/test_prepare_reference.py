"""examples/milan_imd/prepare_reference.py on a tiny hand-written CSV."""

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

from tests.conftest import ROOT, load_script

prep = load_script(ROOT / "examples" / "milan_imd" / "prepare_reference.py", "prepare_reference")


def _cells(*labels: str) -> str:
    return json.dumps([{"idx": i, "code": 0, "label": lab} for i, lab in enumerate(labels)])


@pytest.mark.parametrize(
    ("cells", "share"),
    [
        (_cells("Impervious (Road)", "Pervious (Grass)", "Impervious (Roof)"), 200 / 3),
        (_cells("Pervious (Trees)", "Unclear / cloud", "Pervious (Water)"), 0.0),
        (_cells("Impervious (Roof)", "No data"), 100.0),
        (_cells("No data"), None),
        ("", None),
        ("not json", None),
    ],
)
def test_impervious_share(cells: str, share: float | None) -> None:
    got = prep.impervious_share(cells)  # type: ignore[attr-defined]
    assert got == pytest.approx(share) if share is not None else got is None


def test_prepare_reference(tmp_path: Path) -> None:
    csv = tmp_path / "cells.csv"
    pd.DataFrame(
        {
            "PLOTID": ["PLOT_001", "PLOT_002", "PLOT_003"],
            "LAT": [45.4642, 45.47, 45.48],
            "LON": [9.19, 9.2, 9.21],
            "ref_label": ["IMD_Class_5", "IMD_Class_0", "IMD_Class_2"],
            "cells_json": [
                _cells("Impervious (Roof)", "Impervious (Road)", "Pervious (Grass)", "Pervious"),
                _cells("Pervious (Grass)"),
                _cells("Unclear"),
            ],
            "other": [1, 2, 3],
        }
    ).to_csv(csv, index=False)
    out = tmp_path / "data" / "earthlabel_2018.gpkg"
    assert prep.main([str(csv), "-o", str(out)]) == 0  # type: ignore[attr-defined]
    points = gpd.read_file(out)
    assert points.crs.to_epsg() == 32632
    assert list(points.columns) == ["PLOTID", "stratum", "imd_ref", "geometry"]
    assert points["PLOTID"].tolist() == ["PLOT_001", "PLOT_002"]  # PLOT_003 has no resolvable cell
    assert points["imd_ref"].tolist() == [50.0, 0.0]
    assert points["stratum"].tolist() == ["IMD_Class_5", "IMD_Class_0"]
    assert 510_000 < points.geometry.x.iloc[0] < 520_000  # Milan in UTM 32N
