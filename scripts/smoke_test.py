"""Check an installed GeoKnit the way a user meets it (PLAN Phase 8, release build).

    python scripts/smoke_test.py [--version 0.1.0]

Run it with the Python of a fresh environment where only the wheel was
installed (``pip install dist/geoknit-*.whl``), not an editable checkout. It
works in a temporary folder and checks that:

1. ``geoknit`` is imported from the installed package, ``geoknit --version`` works;
2. ``geoknit run`` on the synthetic example prints the metrics Panel;
3. ``geoknit export`` writes a script that prints the same Panel;
4. ``geoknit <folder>`` serves the built canvas (not the placeholder) and its assets.

Standard library only, so it needs nothing besides the installed wheel.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "examples" / "synthetic"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def step(message: str) -> None:
    print(f"smoke: {message}", flush=True)


def fail(message: str) -> None:
    print(f"smoke: FAILED: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def geoknit_command() -> list[str]:
    """The installed console script next to this Python."""
    found = shutil.which("geoknit", path=str(Path(sys.executable).parent))
    if found is None:
        fail(f"no geoknit command next to {sys.executable}")
    return [str(found)]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=ENV, check=False
    )
    if proc.returncode != 0:
        fail(f"{' '.join(cmd)} exited with {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc


def panels(stdout: str) -> str:
    if "--- Panel" not in stdout:
        fail(f"no Panel in the output:\n{stdout}")
    return stdout[stdout.index("--- Panel") :]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as res:  # noqa: S310  (localhost only)
        return res.status, res.read().decode("utf-8", errors="replace")


def check_install(version: str | None, work: Path) -> None:
    where = run([sys.executable, "-c", "import geoknit; print(geoknit.__file__)"], work)
    location = Path(where.stdout.strip()).resolve()
    if ROOT in location.parents:
        fail(f"geoknit is imported from the checkout ({location}), not from the wheel")
    step(f"imported from {location.parent}")
    out = run([*geoknit_command(), "--version"], work).stdout.strip()
    if version is not None and out != f"geoknit {version}":
        fail(f'geoknit --version says "{out}", expected "geoknit {version}"')
    step(out)


def check_run_and_export(work: Path) -> None:
    shutil.copy(SYNTHETIC / "imd.geoknit", work / "imd.geoknit")
    shutil.copy(SYNTHETIC / "make_data.py", work / "make_data.py")
    run([sys.executable, "make_data.py", "data"], work)
    shown = panels(run([*geoknit_command(), "run", "-q", "imd.geoknit"], work).stdout)
    if "RMSE" not in shown:
        fail(f"the metrics Panel has no RMSE:\n{shown}")
    step("geoknit run printed the metrics Panel")
    run([*geoknit_command(), "export", "imd.geoknit"], work)
    # Started from another folder: the script must find its data relative to itself.
    exported = panels(run([sys.executable, str(work / "imd.py")], work.parent).stdout)
    if exported != shown:
        fail(f"the exported script printed\n{exported}\ninstead of\n{shown}")
    step("the exported script printed the same Panel")


def stop_tree(proc: subprocess.Popen[str]) -> None:
    """Stop the server and its children: on Windows ``geoknit.exe`` is only a launcher,
    and the worker keeps the project folder busy until it exits."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        os.killpg(proc.pid, signal.SIGTERM)
    proc.wait(timeout=30)


def check_server(work: Path) -> None:
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [*geoknit_command(), str(work), "--port", str(port), "--no-browser"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=ENV,
        start_new_session=os.name != "nt",  # a process group to stop with the worker
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                status, _ = get(f"{base}/api/status")
                if status == 200:
                    break
            except OSError:
                pass
            if server.poll() is not None or time.monotonic() > deadline:
                fail(f"the server did not start:\n{server.stderr.read() if server.stderr else ''}")
            time.sleep(0.5)
        _, page = get(f"{base}/")
        if "has not been built" in page:
            fail("the server shows the placeholder page: the wheel has no frontend")
        assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page)
        if not assets:
            fail(f"index.html references no /assets/ files:\n{page[:500]}")
        for asset in assets:
            status, _ = get(base + asset)
            if status != 200:
                fail(f"{asset} answered {status}")
        step(f"the server serves the canvas and its {len(assets)} assets")
    finally:
        stop_tree(server)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="the version geoknit --version must report")
    args = parser.parse_args()
    # A process that is slow to exit must not fail the checks that already passed.
    with tempfile.TemporaryDirectory(prefix="geoknit-smoke-", ignore_cleanup_errors=True) as tmp:
        work = Path(tmp) / "project"
        work.mkdir()
        check_install(args.version, work)
        check_run_and_export(work)
        check_server(work)
    step("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
