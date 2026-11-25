"""Start GeoKnit on a scratch copy of the Milan example, for the walkthrough screenshots.

    python docs-shots/serve_milan.py PORT

The Milan data is not in the repository. Set ``GEOKNIT_MILAN_DATA`` to the
folder holding the three files of ``examples/milan_imd/README.md`` (default:
``examples/milan_imd/data``). The project is a new temporary folder whose
``data`` links to that folder (a junction on Windows), so the real example's
cache and outputs are never touched. Trust file, autosaves and user components
are private to the run.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "milan_imd"
FILES = (
    "CLMS_2018_Milan_UTM32N.tif",
    "aoi_milan.gpkg",
    "AlphaEarth_2018_Milan_UTM32N.tif",
)


def link_folder(link: Path, target: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))  # no admin rights needed
    else:
        link.symlink_to(target, target_is_directory=True)


def main() -> int:
    port = int(sys.argv[1])
    data = Path(os.environ.get("GEOKNIT_MILAN_DATA", EXAMPLE / "data")).resolve()
    missing = [f for f in FILES if not (data / f).is_file()]
    if missing:
        print(f"serve_milan: {data} lacks {', '.join(missing)}", file=sys.stderr)
        return 2

    from geoknit.runtime.geoenv import use_bundled_geo_data

    use_bundled_geo_data()
    base = Path(tempfile.mkdtemp(prefix="geoknit-shots-"))
    project = base / "milan_imd"  # the name shown in the folder tree
    project.mkdir()
    home = base / "home"
    os.environ["GEOKNIT_TRUST_FILE"] = str(home / "trusted.json")
    os.environ["GEOKNIT_USER_COMPONENTS"] = str(home / "components")
    link_folder(project / "data", data)
    workflow = project / "milan_imd.geoknit"
    shutil.copy(EXAMPLE / "milan_imd.geoknit", workflow)

    from geoknit.cli import main as geoknit_main
    from geoknit.core.trust import TrustStore

    TrustStore().add(workflow.read_bytes())
    print(f"screenshots project: {project}", flush=True)
    return geoknit_main([str(workflow), "--port", str(port), "--no-browser"])


if __name__ == "__main__":
    sys.exit(main())
