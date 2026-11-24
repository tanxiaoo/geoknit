"""Start GeoKnit on a fresh project with the synthetic data, for Playwright.

    python e2e/serve.py PORT [--workflow]

The project lives in a new temporary folder; ``--workflow`` also copies
``examples/synthetic/imd.geoknit`` into it and opens it (trusted). The trust
file is private to the run.
"""

from __future__ import annotations

import runpy
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    port = int(sys.argv[1])
    with_workflow = "--workflow" in sys.argv[2:]

    import os

    from geoknit.runtime.geoenv import use_bundled_geo_data

    use_bundled_geo_data()  # a system PROJ_LIB must not break make_data.py
    project = Path(tempfile.mkdtemp(prefix="geoknit-e2e-"))
    os.environ["GEOKNIT_TRUST_FILE"] = str(project.parent / f"{project.name}-trusted.json")

    make_data = runpy.run_path(str(ROOT / "examples" / "synthetic" / "make_data.py"))["make_data"]
    make_data(project / "data")

    target = project
    if with_workflow:
        target = project / "imd.geoknit"
        shutil.copy(ROOT / "examples" / "synthetic" / "imd.geoknit", target)
        from geoknit.core.trust import TrustStore

        TrustStore().add(target.read_bytes())

    from geoknit.cli import main as geoknit_main

    print(f"e2e project: {project}", flush=True)
    return geoknit_main([str(target), "--port", str(port), "--no-browser"])


if __name__ == "__main__":
    sys.exit(main())
