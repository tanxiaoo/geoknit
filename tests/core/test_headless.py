"""``geoknit/core`` must stay headless (CLAUDE.md rule)."""

import subprocess
import sys


def test_core_imports_no_server_runtime_or_web_modules() -> None:
    code = (
        "import sys\n"
        "import geoknit.core.executor, geoknit.core.workflow, geoknit.core.solver\n"
        "import geoknit.core.cache\n"
        "bad = [m for m in sys.modules if m.startswith(('geoknit.server', 'geoknit.runtime',"
        " 'fastapi', 'starlette', 'uvicorn', 'osgeo'))]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
