"""PLAN Phase 8 "Done when": the exported synthetic script, run with plain Python,
gives exactly the same metrics as GeoKnit."""

import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from geoknit.cli import main
from geoknit.components.registry import default_registry
from geoknit.core.executor import InProcessExecutor
from geoknit.core.workflow import load_workflow
from tests.conftest import SYNTHETIC, load_make_data

BLOCK_GEOKNIT = (
    "import runpy, sys; sys.modules['geoknit'] = None; "
    "runpy.run_path(sys.argv[1], run_name='__main__')"
)


def _panels(stdout: str) -> str:
    return stdout[stdout.index("--- Panel") :]


def test_exported_synthetic_script_matches_geoknit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = tmp_path / "imd.geoknit"
    shutil.copy(SYNTHETIC / "imd.geoknit", workflow)
    load_make_data()(tmp_path / "data")

    assert main(["run", "-q", str(workflow)]) == 0
    geoknit_out = capsys.readouterr().out

    assert main(["export", str(workflow)]) == 0
    script = tmp_path / "imd.py"
    assert f"wrote {script}" in capsys.readouterr().err

    # 1. Plain Python, with `import geoknit` failing: the same Panel text.
    proc = subprocess.run(
        [sys.executable, "-c", BLOCK_GEOKNIT, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # CI consoles are cp1252
        cwd=tmp_path.anchor,  # the script finds its data relative to itself
    )
    assert proc.returncode == 0, proc.stderr
    assert _panels(proc.stdout) == _panels(geoknit_out)

    # 2. The metrics table itself is identical, value for value.
    graph = load_workflow(workflow, default_registry())
    ex = InProcessExecutor(graph, base_dir=tmp_path)
    assert ex.run().ok
    panel = next(n for n, node in graph.nodes.items() if node.component == "param/panel")
    expected = ex.output(panel, "data")
    monkeypatch.chdir(tmp_path)
    exported = runpy.run_path(str(script))["main"]()[panel]
    pd.testing.assert_frame_equal(exported, expected, check_exact=True)
