"""Tests for the ``geoknit`` command line."""

import subprocess
import sys
from pathlib import Path

import pytest

from geoknit import __version__
from geoknit.cli import main


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"geoknit {__version__}"


def test_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "geoknit", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"geoknit {__version__}"


def test_help_mentions_both_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "folder" in out and "geoknit run" in out


# ── geoknit [folder] ──


def test_find_free_port_can_be_bound() -> None:
    import socket

    from geoknit.cli import find_free_port

    port = find_free_port()
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_serve_binds_to_localhost(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append({"app": app, **kw}))
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)

    assert main([str(tmp_path), "--port", "8765"]) == 0
    assert calls[0]["host"] == "127.0.0.1" and calls[0]["port"] == 8765
    assert calls[0]["app"].state.session.project == tmp_path.resolve()

    wf = _workflow(tmp_path)
    assert main([str(wf), "--no-browser"]) == 0
    assert calls[1]["port"] > 0
    session = calls[1]["app"].state.session
    assert session.project == tmp_path.resolve() and session._initial == wf.resolve()
    assert opened == []  # the browser opens only once the server has started


def test_serve_refuses_a_missing_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "nope")]) == 2
    assert "does not exist" in capsys.readouterr().err
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert main([str(tmp_path / "a.txt")]) == 2


# ── geoknit run ──

UPPER = """\
# geoknit: component
# name: Upper
# category: Text
# inputs:
#   text: Text
# outputs:
#   upper: Text

# --- settings ---
fail = False

# --- code ---
print(f"upper-casing {text}")
if fail:
    raise ValueError("asked to fail")
upper = text.upper()
"""


def _workflow(tmp_path: Path, *, fail: bool = False) -> Path:
    from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_TEXT, Graph
    from geoknit.core.workflow import save_workflow

    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "hello")
    up = g.add_component(INLINE, source=UPPER).id
    if fail:
        g.set_setting(up, "fail", True)
    panel = g.add_component(PARAM_PANEL).id
    g.add_component(PARAM_PANEL)  # an unconnected Panel
    g.add_wire(text, "value", up, "text")
    g.add_wire(up, "upper", panel, "data")
    path = tmp_path / "wf.geoknit"
    save_workflow(g, path)
    return path


def test_run_prints_panels_and_uses_the_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workflow(tmp_path)
    assert main(["run", str(path)]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == ["--- Panel n3 ---", "HELLO", "--- Panel n4 ---", "(empty)"]
    assert "[n2 Upper] upper-casing hello" in err
    assert "1 ran · 0 from cache" in err
    assert (tmp_path / ".geoknit" / "cache").is_dir()

    assert main(["run", "-q", str(path)]) == 0
    out2, err2 = capsys.readouterr()
    assert out2 == out
    assert "0 ran · 1 from cache" in err2
    assert "upper-casing" not in err2

    assert main(["run", "--clear-cache", str(path)]) == 0
    assert "0 from cache" in capsys.readouterr().err


def test_run_reports_errors_with_exit_code_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _workflow(tmp_path, fail=True)
    assert main(["run", "--no-cache", str(path)]) == 1
    out, err = capsys.readouterr()
    assert "ValueError: asked to fail" in err
    assert "skipped: upstream n2 failed" in out
    assert not (tmp_path / ".geoknit").exists()


def test_run_refuses_a_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(tmp_path / "nope.geoknit")]) == 1
    assert "cannot open" in capsys.readouterr().err


def test_run_as_a_module_in_a_real_process(tmp_path: Path) -> None:
    path = _workflow(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "geoknit", "run", str(path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "HELLO" in result.stdout
