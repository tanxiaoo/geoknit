"""Export to Python (SPEC 10): the script runs alone and gives GeoKnit's results."""

import ast
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from geoknit.core.executor import InProcessExecutor
from geoknit.core.export import (
    VENDOR_FILES,
    ExportError,
    export_script,
    indent,
    vendored_section,
)
from geoknit.core.graph import PARAM_MAP, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph
from tests.core.sources import LENGTH, REPEAT, TO_NUMBER

MULTILINE = '''\
# geoknit: component
# name: Banner
# category: Text
# inputs:
#   text: Text
# outputs:
#   banner: Text

# --- settings ---
frame = """+--
|  indented line
+--"""  # multiline

# --- code ---
def wrap(t):
    return f"""{frame}
  {t}
end"""

banner = wrap(text)
'''

PRINTS = """\
# geoknit: component
# name: Python
# category: Script
# inputs:
#   x: Text
# outputs:
#   out: Text

# --- settings ---

# --- code ---
print("got", x)
"""

HELPERS = """\
# geoknit: component
# name: Count Rules
# category: Text
# inputs:
#   breaks: Text
# outputs:
#   n: Number

# --- code ---
from geoknit.helpers import parse_breaks as pb
from geoknit.core.types import ModelBundle

if True:
    from geoknit.helpers.breaks import class_dtype
n = len(pb(breaks))
assert class_dtype(n) == "uint8" and ModelBundle
"""

OTHER_IMPORT = """\
# geoknit: component
# name: Uses Cache
# category: Script
# outputs:
#   y: Number

# --- code ---
from geoknit.core.cache import CACHE_FORMAT
y = CACHE_FORMAT
"""


def _text(g: Graph, value: str) -> str:
    n = g.add_component(PARAM_TEXT)
    g.set_value(n.id, value)
    return n.id


def _inline(g: Graph, source: str) -> str:
    return g.add_component("inline", source=source).id


def _panel(g: Graph, src: str, port: str) -> str:
    p = g.add_component(PARAM_PANEL).id
    g.add_wire(src, port, p, "data")
    return p


def _text_graph() -> tuple[Graph, dict[str, str]]:
    """Text → Repeat (times from a slider) → Length → Half → (Number → Text) Repeat → Panel."""
    g = Graph()
    t = _text(g, "ab")
    s = g.add_component(PARAM_SLIDER).id
    g.set_slider(s, min=1, max=10, step=1, value=3)
    rep = _inline(g, REPEAT)
    g.add_wire(t, "value", rep, "text")
    g.add_wire(s, "value", rep, "times")
    length = _inline(g, LENGTH)
    g.add_wire(rep, "repeated", length, "text")
    half = _inline(g, TO_NUMBER)
    g.add_wire(length, "n", half, "x")
    rep2 = _inline(g, REPEAT)
    g.add_wire(half, "half", rep2, "text")  # Number → Text
    p1 = _panel(g, rep, "repeated")
    p2 = _panel(g, rep2, "repeated")
    return g, {"rep": rep, "rep2": rep2, "p1": p1, "p2": p2, "half": half}


def _run_script(script: str, folder: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    path = folder / "exported.py"
    path.write_text(script, encoding="utf-8")
    monkeypatch.chdir(folder)
    return runpy.run_path(str(path))["main"]()


def _run_blocked(script: str, folder: Path) -> subprocess.CompletedProcess[str]:
    """Run the script with ``import geoknit`` failing, as on a machine without GeoKnit."""
    path = folder / "exported.py"
    path.write_text(script, encoding="utf-8")
    code = (
        "import runpy, sys; sys.modules['geoknit'] = None; "
        "runpy.run_path(sys.argv[1], run_name='__main__')"
    )
    return subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # CI consoles are cp1252
        cwd=folder.anchor,
    )


def test_script_gives_the_same_results_as_geoknit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g, ids = _text_graph()
    ex = InProcessExecutor(g)
    assert ex.run().ok
    script = export_script(g).script
    panels = _run_script(script, tmp_path, monkeypatch)
    assert panels == {
        ids["p1"]: ex.output(ids["rep"], "repeated"),
        ids["p2"]: ex.output(ids["rep2"], "repeated"),
    }
    assert panels[ids["p1"]] == "ab-ab-ab"
    assert panels[ids["p2"]] == "4.0-4.0"


def test_script_layout(tmp_path: Path) -> None:
    g, ids = _text_graph()
    script = export_script(g, workflow_name="demo.geoknit").script
    ast.parse(script)
    assert script.startswith('"""demo.geoknit, exported from GeoKnit')
    assert "N01_TEXT = 'ab'" in script
    assert "N02_TIMES = 3" in script
    assert "def n03_repeat(text, times):" in script
    # A wired setting is commented out; the others stay.
    assert "    # times = 2  # range: 1..10  # ← wired input" in script
    assert '    sep = "-"  # options: - | _ | +' in script
    # main() calls in topological order, Number → Text through str().
    main = script[script.index("def main()") :]
    calls = [main.index(f"{n}(") for n in ("n03_repeat", "n04_length", "n05_half", "n06_repeat")]
    assert calls == sorted(calls)
    assert "n06_repeated = n06_repeat(text=str(n05_half_value))" in main
    assert f'_panel("{ids["p1"]}", n03_repeated)' in main


def test_unwired_input_uses_its_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g = Graph()
    rep = _inline(g, REPEAT)
    g.add_wire(_text(g, "x"), "value", rep, "text")
    p = _panel(g, rep, "repeated")
    script = export_script(g).script
    assert "    times = 2  # range: 1..10" in script
    assert _run_script(script, tmp_path, monkeypatch) == {p: "x-x"}


def test_multiline_strings_keep_their_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = Graph()
    b = _inline(g, MULTILINE)
    g.add_wire(_text(g, "hi"), "value", b, "text")
    p = _panel(g, b, "banner")
    ex = InProcessExecutor(g)
    assert ex.run().ok
    expected = ex.output(b, "banner")
    assert expected == "+--\n|  indented line\n+--\n  hi\nend"
    assert _run_script(export_script(g).script, tmp_path, monkeypatch) == {p: expected}


def test_indent_skips_string_continuations() -> None:
    src = 'x = """a\n  b"""\nif x:\n    y = 1\n'
    assert indent(src) == '    x = """a\n  b"""\n    if x:\n        y = 1\n'


def test_print_port_collects_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    g = Graph()
    py = _inline(g, PRINTS)
    g.add_wire(_text(g, "it"), "value", py, "x")
    p = _panel(g, py, "out")
    ex = InProcessExecutor(g)
    assert ex.run().ok
    assert ex.output(py, "out") == "got it\n"
    assert _run_script(export_script(g).script, tmp_path, monkeypatch) == {p: "got it\n"}


def test_helpers_are_vendored(tmp_path: Path) -> None:
    g = Graph()
    c = _inline(g, HELPERS)
    g.add_wire(_text(g, "0 | 0-20 | 100"), "value", c, "breaks")
    _panel(g, c, "n")
    g.add_component(PARAM_MAP)
    _ = g.add_component(PARAM_PANEL)  # not connected
    result = export_script(g)
    assert result.warnings == []
    assert "    pb = parse_breaks\n" in result.script
    assert "        pass\n" in result.script  # the indented import left a block
    assert "Map Viewer: view only" in result.script
    proc = _run_blocked(result.script, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.endswith("--- Panel n3 ---\n3\n--- Panel n5 ---\n(empty)\n")


USES_COLOR = """\
# geoknit: component
# name: Shade
# inputs:
#   c: Any
# outputs:
#   opaque: Boolean

# --- code ---
opaque = c.rgba[3] == 255
print("shade", c.hex, c == Color.parse("11,122,124"))
"""


def test_color_constant_vendors_the_types(tmp_path: Path) -> None:
    # Stand-in for the Color Swatch node (change 01 step 6): a Params node whose
    # value is a Color. The component uses ``Color`` without importing it, so
    # only the constant can bring the vendored types into the script.
    from geoknit.core.types import Color

    g = Graph()
    t = _text(g, "x")
    g.nodes[t].value = Color("#0B7A7C")
    shade = _inline(g, USES_COLOR)
    g.add_wire(t, "value", shade, "c")
    length = _inline(g, LENGTH)
    g.add_wire(shade, "opaque", length, "text")  # Boolean → Text
    result = export_script(g)
    assert (t, shade) == ("n1", "n2")
    assert 'N01_C = Color("#0B7A7C")' in result.script
    assert "class Color:" in result.script and "NAMED_RAMPS" in result.script
    assert "text=str(n02_opaque)" in result.script
    proc = _run_blocked(result.script, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "shade #0B7A7C True\n"


def test_colormap_literals() -> None:
    from geoknit.core.export import python_literal
    from geoknit.core.types import Color, Colormap

    assert python_literal(Colormap.named("viridis")) == 'Colormap.named("viridis")'
    assert python_literal(Colormap.named("blues", reverse=True)) == (
        'Colormap.named("blues", reverse=True)'
    )
    for cm in (
        Colormap("continuous", name="magma", min=0, max=1),
        Colormap("continuous", stops=((0, "#000000"), (1, "#FFFFFF"))),
        Colormap("classes", classes=((1, "#FF0000", "a"),), other="#000000"),
    ):
        assert eval(python_literal(cm), {"Color": Color, "Colormap": Colormap}) == cm  # noqa: S307
    assert python_literal(True) == "True"


def test_other_geoknit_imports_are_warned_about() -> None:
    g = Graph()
    n = _inline(g, OTHER_IMPORT)
    result = export_script(g)
    assert result.warnings == [
        f"{n} Uses Cache imports geoknit.core.cache: the script still needs GeoKnit installed"
    ]
    assert "Warnings:" in result.script
    assert "from geoknit.core.cache import CACHE_FORMAT" in result.script


def test_vendored_modules_have_no_clashing_names() -> None:
    text = vendored_section(list(VENDOR_FILES))
    tree = ast.parse("from __future__ import annotations\n" + text)
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.ImportFrom):
            assert not (stmt.module or "").startswith("geoknit"), stmt.module
    defined = [s.name for s in tree.body if isinstance(s, ast.FunctionDef | ast.ClassDef)]
    assert len(defined) == len(set(defined))
    assert not {"main", "BASE_DIR", "_panel", "_as_text", "_capture_print", "_Tee"} & set(defined)


def test_refusals_name_the_node() -> None:
    g = Graph()
    rep = _inline(g, REPEAT)
    with pytest.raises(ExportError, match=f'{rep} Repeat: input "text" is not connected'):
        export_script(g)

    g = Graph()
    n = _inline(g, LENGTH)
    g.set_source(n, LENGTH.replace("# --- code ---", "# --- settings ---\nx = [\n# --- code ---"))
    g.add_wire(_text(g, "a"), "value", n, "text")
    with pytest.raises(ExportError, match=f"{n} Length: fix the component first"):
        export_script(g)

    g = Graph()
    n = _inline(g, LENGTH.replace("n = len(text)", "n = len(text"))
    g.add_wire(_text(g, "a"), "value", n, "text")
    with pytest.raises(ExportError, match="syntax error"):
        export_script(g)
