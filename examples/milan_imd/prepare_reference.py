"""Turn the EarthLabel CSV into the reference points of the Milan example.

Run once, outside GeoKnit:

    python examples/milan_imd/prepare_reference.py

It reads ``data/milan_imd_2018_results_cells.csv`` (450 plots with ``LAT`` /
``LON`` in WGS84, ``ref_label`` and ``cells_json``) and writes
``data/earthlabel_2018.gpkg``: points in EPSG:32632 with the fields

- ``PLOTID``;
- ``stratum``: the plot's ``ref_label`` (e.g. ``IMD_Class_5``);
- ``imd_ref``: the impervious share in % of the plot's resolvable sub-cells.

A sub-cell in ``cells_json`` is resolvable when its label starts with
"Impervious" or "Pervious", and impervious when it starts with "Impervious".
Plots without any resolvable sub-cell are dropped.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
CSV = HERE / "data" / "milan_imd_2018_results_cells.csv"
OUT = HERE / "data" / "earthlabel_2018.gpkg"
CRS = "EPSG:32632"


def impervious_share(cells_json: str) -> float | None:
    """% impervious among the resolvable sub-cells, or ``None`` if there are none."""
    try:
        cells = json.loads(cells_json) if cells_json else []
    except (TypeError, ValueError):
        return None
    labels = [str(c.get("label", "")).strip().lower() for c in cells if isinstance(c, dict)]
    impervious = sum(label.startswith("impervious") for label in labels)
    pervious = sum(label.startswith("pervious") for label in labels)
    resolvable = impervious + pervious
    return 100.0 * impervious / resolvable if resolvable else None


def prepare_reference(csv_path: Path = CSV, out_path: Path = OUT) -> Any:
    """Write the reference GeoPackage; return the GeoDataFrame."""
    import geopandas as gpd
    import pandas as pd

    table = pd.read_csv(csv_path, dtype={"PLOTID": str})
    missing = {"PLOTID", "LAT", "LON", "ref_label", "cells_json"} - set(table.columns)
    if missing:
        raise ValueError(f"{csv_path.name} has no column {', '.join(sorted(missing))}")
    share = table["cells_json"].map(impervious_share)
    keep = share.notna()
    if not keep.all():
        print(f"dropped {int((~keep).sum())} plots without resolvable sub-cells", file=sys.stderr)
    table, share = table[keep], share[keep]
    points = gpd.GeoDataFrame(
        {
            "PLOTID": table["PLOTID"].to_numpy(),
            "stratum": table["ref_label"].astype(str).to_numpy(),
            "imd_ref": share.round(2).to_numpy(dtype="float64"),
        },
        geometry=gpd.points_from_xy(table["LON"], table["LAT"]),
        crs="EPSG:4326",
    ).to_crs(CRS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    points.to_file(out_path, layer="earthlabel_2018", driver="GPKG")
    return points


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv", nargs="?", type=Path, default=CSV)
    parser.add_argument("-o", "--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    from geoknit.runtime.geoenv import use_bundled_geo_data

    use_bundled_geo_data()  # ignore a system PROJ_LIB (e.g. from PostGIS)
    points = prepare_reference(args.csv, args.out)
    print(
        f"wrote {len(points)} points to {args.out} (imd_ref mean {points['imd_ref'].mean():.1f} %)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
