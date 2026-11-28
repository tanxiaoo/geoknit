"""The example workflows (PLAN Phase 3 "Done when")."""

import shutil
from pathlib import Path

import pytest

from geoknit.cli import main
from geoknit.components.registry import default_registry
from geoknit.core import types
from geoknit.core.workflow import load_workflow, save_workflow
from geoknit.helpers.breaks import parse_breaks
from tests.conftest import ROOT, SYNTHETIC, load_make_data

WORKFLOWS = [SYNTHETIC / "imd.geoknit", ROOT / "examples" / "milan_imd" / "milan_imd.geoknit"]


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_example_loads_and_saves_identically(path: Path, tmp_path: Path) -> None:
    graph = load_workflow(path, default_registry(tmp_path / "none", packs=False))
    assert graph.nodes and graph.wires
    out = tmp_path / path.name
    save_workflow(graph, out)
    assert out.read_bytes() == path.read_bytes()


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_example_maps_the_imd_classes(path: Path, tmp_path: Path) -> None:
    """Change 03 step 5: a Map Viewer with a Map Layer and the IMD class Colormap,
    one class per Reclassify rule, kept off the metrics path."""
    graph = load_workflow(path, default_registry(tmp_path / "none", packs=False))
    by_kind = {n.component: n for n in graph.nodes.values()}
    layer, viewer, colormap = (by_kind[f"param/{k}"] for k in ("layer", "map", "colormap"))
    reclassify = by_kind["builtin/raster/reclassify"]
    breaks = graph.wires_into(reclassify.id, "breaks")[0].src
    rules = parse_breaks(graph.nodes[breaks].value)
    cmap = colormap.value
    assert isinstance(cmap, types.Colormap) and cmap.kind == "classes" and cmap.other is None
    assert [v for v, _, _ in cmap.classes] == [r.cls for r in rules]
    assert all(label for _, _, label in cmap.classes)
    assert [(w.src, w.src_port) for w in graph.wires_into(layer.id, "data")] == [
        (reclassify.id, "classes")
    ]
    assert graph.wires_into(layer.id, "colormap")[0].src == colormap.id
    assert layer.style == {"name": "IMD classes"}
    shown = [(w.src, w.src_port) for w in graph.wires_into(viewer.id, "layers")]
    assert (layer.id, "layer") in shown
    # nothing reads the view nodes or the Colormap: the metrics cannot change
    for nid in (layer.id, viewer.id, colormap.id):
        assert [w for w in graph.wires if w.src == nid and w.dst not in (layer.id, viewer.id)] == []


def _metrics(stdout: str) -> dict[str, float]:
    lines = stdout.split("--- Panel", 1)[1].splitlines()
    header = next(i for i, line in enumerate(lines) if "RMSE" in line)
    names = lines[header].split()
    values = [float(v) for v in lines[header + 1].split()[1:]]  # drop the row index
    return dict(zip(names, values, strict=True))


def test_synthetic_example_runs_headless(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``geoknit run examples/synthetic/imd.geoknit`` prints the metrics table."""
    shutil.copy(SYNTHETIC / "imd.geoknit", tmp_path / "imd.geoknit")
    load_make_data()(tmp_path / "data")

    assert main(["run", "-q", str(tmp_path / "imd.geoknit")]) == 0
    first = capsys.readouterr()
    metrics = _metrics(first.out)
    assert metrics["n"] == 42  # the held-out 30 % of 7 × 20 sample points
    # Locked: the synthetic data and every random step (sampling, split, forest) are
    # seeded in make_data.py and the workflow, so a change here is a real change. The
    # tolerance only absorbs last-digit float differences between platforms (CI runs
    # Windows and Ubuntu); the printed table has 6 significant digits.
    assert metrics["dropped"] == 0
    assert metrics["RMSE"] == pytest.approx(2.455046, rel=1e-4)
    assert metrics["MAE"] == pytest.approx(1.68384, rel=1e-4)
    assert metrics["R²"] == pytest.approx(0.995317, rel=1e-4)
    assert metrics["bias"] == pytest.approx(-0.369395, rel=1e-4)
    assert (tmp_path / "outputs" / "imd_rf.tif").is_file()
    assert "0 failed" in first.err

    # A second run is all cache hits, although Write Raster wrote its file.
    assert main(["run", "-q", str(tmp_path / "imd.geoknit")]) == 0
    second = capsys.readouterr()
    assert "geoknit: 0 ran" in second.err
    assert _metrics(second.out) == metrics
