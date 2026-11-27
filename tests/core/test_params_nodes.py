"""The Params nodes of change 01 (section 8) and the integer mode (section 2)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from geoknit.core import types
from geoknit.core.cache import compute_keys
from geoknit.core.executor import InProcessExecutor
from geoknit.core.export import export_script
from geoknit.core.graph import (
    PARAM_COLOR,
    PARAM_COLORMAP,
    PARAM_NUMBER,
    PARAM_PANEL,
    PARAM_SLIDER,
    PARAM_TEXT,
    PARAM_TOGGLE,
    PARAM_VALUE_LIST,
    Graph,
    GraphError,
)
from geoknit.core.solver import Solver
from geoknit.core.types import Color, Colormap
from geoknit.core.workflow import (
    WorkflowError,
    apply_dict,
    dumps,
    graph_from_dict,
    graph_to_dict,
    load_workflow,
    save_workflow,
)
from tests.core.sources import LENGTH, TO_NUMBER

FLIP = """\
# geoknit: component
# name: Flip
# category: Logic
# inputs:
#   flag: Boolean
# outputs:
#   inverted: Boolean

# --- code ---
inverted = not flag
print("flip", flag)
"""

ECHO = """\
# geoknit: component
# name: Echo
# category: Text
# inputs:
#   text: Text
# outputs:
#   same: Text

# --- code ---
same = text
"""

NEW_KINDS = (PARAM_NUMBER, PARAM_TOGGLE, PARAM_VALUE_LIST, PARAM_COLOR, PARAM_COLORMAP)


def _one_of_each() -> tuple[Graph, dict[str, str]]:
    g = Graph()
    ids = {kind: g.add_component(kind, position=[0, 80 * i]).id for i, kind in enumerate(NEW_KINDS)}
    g.set_number(ids[PARAM_NUMBER], value=7.6, integer=True)
    g.set_value(ids[PARAM_TOGGLE], True)
    g.set_options(
        ids[PARAM_VALUE_LIST],
        [{"label": "Small", "value": 0.5}, {"label": "Big", "value": 2}],
        value=2,
    )
    g.set_value(ids[PARAM_COLOR], "11,122,124,128")
    g.set_value(ids[PARAM_COLORMAP], Colormap("continuous", name="magma", min=0, max=10).to_json())
    slider = g.add_component(PARAM_SLIDER).id
    g.set_slider(slider, min=0.4, max=9.6, step=0.5, value=3.3, integer=True)
    ids[PARAM_SLIDER] = slider
    return g, ids


def test_new_nodes_have_their_ports_titles_and_defaults() -> None:
    g = Graph()
    made = {kind: g.add_component(kind) for kind in NEW_KINDS}
    assert {k: n.title for k, n in made.items()} == {
        PARAM_NUMBER: "Number",
        PARAM_TOGGLE: "Boolean Toggle",
        PARAM_VALUE_LIST: "Value List",
        PARAM_COLOR: "Color Swatch",
        PARAM_COLORMAP: "Colormap",
    }
    assert {k: n.outputs["value"].type for k, n in made.items()} == {
        PARAM_NUMBER: "Number",
        PARAM_TOGGLE: "Boolean",
        PARAM_VALUE_LIST: "Number",
        PARAM_COLOR: "Color",
        PARAM_COLORMAP: "Colormap",
    }
    assert all(n.inputs == {} for n in made.values())
    assert made[PARAM_NUMBER].value == 0 and made[PARAM_NUMBER].integer is False
    assert made[PARAM_TOGGLE].value is False
    assert made[PARAM_VALUE_LIST].options == [
        {"label": "One", "value": 1},
        {"label": "Two", "value": 2},
        {"label": "Three", "value": 3},
    ]
    assert made[PARAM_VALUE_LIST].value == 1
    assert made[PARAM_COLOR].value == Color("#0B7A7C")
    assert made[PARAM_COLORMAP].value == Colormap.named("viridis")


def test_save_load_save_is_byte_identical(tmp_path: Path) -> None:
    g, ids = _one_of_each()
    first = tmp_path / "a.geoknit"
    save_workflow(g, first)
    nodes = {n["id"]: n for n in json.loads(first.read_text(encoding="utf-8"))["nodes"]}
    assert nodes[ids[PARAM_NUMBER]]["value"] == 8 and nodes[ids[PARAM_NUMBER]]["integer"] is True
    assert nodes[ids[PARAM_TOGGLE]]["value"] is True
    assert nodes[ids[PARAM_VALUE_LIST]]["options"][0] == {"label": "Small", "value": 0.5}
    assert nodes[ids[PARAM_VALUE_LIST]]["value"] == 2
    assert nodes[ids[PARAM_COLOR]]["value"] == "#0B7A7C80"
    assert nodes[ids[PARAM_COLORMAP]]["value"] == {
        "kind": "continuous", "name": "magma", "min": 0, "max": 10, "reverse": False,
    }  # fmt: skip
    slider = nodes[ids[PARAM_SLIDER]]
    assert (slider["min"], slider["max"], slider["step"], slider["value"]) == (0, 10, 1, 3)
    assert slider["integer"] is True

    loaded = load_workflow(first)
    second = tmp_path / "b.geoknit"
    save_workflow(loaded, second)
    assert second.read_bytes() == first.read_bytes()
    assert loaded.nodes[ids[PARAM_COLOR]].value == Color("#0B7A7C80")
    assert loaded.nodes[ids[PARAM_COLORMAP]].value == g.nodes[ids[PARAM_COLORMAP]].value


def test_a_workflow_without_integer_keeps_its_bytes() -> None:
    # Also tests/test_examples.py: both example workflows (with sliders) keep their bytes.
    doc = {
        "format": 1,
        "geoknit_version": "0.1.0",
        "groups": [],
        "nodes": [
            {"component": "param/slider", "id": "n1", "max": 2.5, "min": 0.5, "position": [0, 0],
             "step": 0.25, "value": 1.75},
        ],
        "view": {},
        "wires": [],
    }  # fmt: skip
    g = graph_from_dict(doc)
    assert g.nodes["n1"].integer is False
    assert dumps(graph_to_dict(g)) == dumps(doc)
    assert "integer" not in dumps(graph_to_dict(g))


def test_bad_values_in_a_file_are_refused() -> None:
    def load(node: dict) -> None:
        graph_from_dict({"format": 1, "nodes": [{"id": "n1", "position": [0, 0], **node}]})

    with pytest.raises(WorkflowError, match="must be true or false"):
        load({"component": PARAM_TOGGLE, "value": 1})
    with pytest.raises(WorkflowError, match="not a colour"):
        load({"component": PARAM_COLOR, "value": "teal"})
    with pytest.raises(WorkflowError, match="not one of the Value List's options"):
        load({"component": PARAM_VALUE_LIST, "options": [{"label": "a", "value": 1}], "value": 2})
    with pytest.raises(WorkflowError, match="not a colormap"):
        load({"component": PARAM_COLORMAP, "value": {"kind": "rainbow"}})


def test_set_value_checks_each_kind() -> None:
    g = Graph()
    ids = {kind: g.add_component(kind).id for kind in NEW_KINDS}
    with pytest.raises(GraphError, match="a Number value must be a number"):
        g.set_value(ids[PARAM_NUMBER], True)
    with pytest.raises(GraphError, match="a Number value must be a number"):
        g.set_value(ids[PARAM_NUMBER], "3")
    with pytest.raises(GraphError, match="must be true or false"):
        g.set_value(ids[PARAM_TOGGLE], 0)
    with pytest.raises(GraphError, match="not a colour"):
        g.set_value(ids[PARAM_COLOR], "teal")
    with pytest.raises(GraphError, match="not one of the Value List's options"):
        g.set_value(ids[PARAM_VALUE_LIST], "1")  # text is not the number 1
    with pytest.raises(GraphError, match="not a colormap"):
        g.set_value(ids[PARAM_COLORMAP], "viridis")
    g.set_value(ids[PARAM_COLOR], "#0b7a7c")
    assert g.nodes[ids[PARAM_COLOR]].value == Color("#0B7A7C")
    g.set_value(ids[PARAM_VALUE_LIST], 3.0)
    assert g.nodes[ids[PARAM_VALUE_LIST]].value == 3  # the option's own value
    g.set_value(ids[PARAM_NUMBER], 2.5)
    assert g.nodes[ids[PARAM_NUMBER]].value == 2.5


def test_options_are_checked() -> None:
    g = Graph()
    v = g.add_component(PARAM_VALUE_LIST).id
    with pytest.raises(GraphError, match="at least one option"):
        g.set_options(v, [])
    with pytest.raises(GraphError, match="an option is"):
        g.set_options(v, [{"label": "a"}])
    with pytest.raises(GraphError, match="the value must be a number or text"):
        g.set_options(v, [{"label": "a", "value": True}])
    with pytest.raises(GraphError, match="listed twice"):
        g.set_options(v, [{"label": "a", "value": 1}, {"label": "b", "value": 1.0}])
    # The chosen value stays when it is still an option, else the first is chosen.
    g.set_value(v, 2)
    g.set_options(v, [{"label": "x", "value": 5}, {"label": "y", "value": 2}])
    assert g.nodes[v].value == 2
    g.set_options(v, [{"label": "x", "value": 5}])
    assert g.nodes[v].value == 5


def test_integer_mode_rounds_and_keeps_step_at_least_one() -> None:
    g = Graph()
    n = g.add_component(PARAM_NUMBER).id
    g.set_value(n, 2.5)
    g.set_number(n, integer=True)
    assert g.nodes[n].value == 3 and isinstance(g.nodes[n].value, int)
    g.set_value(n, -2.5)
    assert g.nodes[n].value == -2  # half up, like the frontend's Math.round
    s = g.add_component(PARAM_SLIDER).id
    g.set_slider(s, min=0, max=1, step=0.1, value=0.5)
    with pytest.raises(GraphError, match="slider min must be below max"):
        g.set_slider(s, min=0.2, max=0.4, integer=True)
    g.set_slider(s, min=0, max=10, step=0.2, value=4.4, integer=True)
    node = g.nodes[s]
    assert (node.min, node.max, node.step, node.value, node.integer) == (0, 10, 1, 4, True)
    assert isinstance(node.value, int)


def test_value_list_type_follows_its_options_and_rechecks_wires() -> None:
    g = Graph()
    solver = Solver(g)
    v = g.add_component(PARAM_VALUE_LIST).id
    g.set_options(v, [{"label": str(i), "value": i} for i in (1, 2, 3)])
    assert g.nodes[v].outputs["value"].type == "Number"
    half = g.add_component("inline", source=TO_NUMBER).id
    echo = g.add_component("inline", source=ECHO).id
    g.add_wire(v, "value", half, "x")
    g.add_wire(v, "value", echo, "text")  # Number → Text
    ex = InProcessExecutor(g, solver=solver)
    assert ex.run().ok
    assert ex.output(half, "half") == 0.5
    assert ex.output(echo, "same") == "1"

    g.set_options(
        v, [{"label": "1", "value": 1}, {"label": "a", "value": "a"}, {"label": "3", "value": 3}]
    )
    assert g.nodes[v].outputs["value"].type == "Text"
    assert [(w.dst, w.dst_port) for w in g.wires] == [(echo, "text")]  # the Number wire is gone
    assert solver.states[half] == "out_of_date"
    with pytest.raises(GraphError, match="Text can't connect to Number"):
        g.add_wire(v, "value", half, "x")
    ex = InProcessExecutor(g, solver=solver)
    assert ex.run().failed == [half]  # its input is no longer wired
    assert ex.output(v, "value") == "1"  # a number option of a Text list is given as text
    assert ex.output(echo, "same") == "1"


def test_each_kind_runs_and_feeds_components() -> None:
    g, ids = _one_of_each()
    flip = g.add_component("inline", source=FLIP).id
    g.add_wire(ids[PARAM_TOGGLE], "value", flip, "flag")
    length = g.add_component("inline", source=LENGTH).id
    g.add_wire(ids[PARAM_TOGGLE], "value", length, "text")  # Boolean → Text
    panels = {}
    for kind in (PARAM_COLOR, PARAM_COLORMAP, PARAM_NUMBER):
        panels[kind] = g.add_component(PARAM_PANEL).id
        g.add_wire(ids[kind], "value", panels[kind], "data")
    ex = InProcessExecutor(g)
    assert ex.run().ok
    assert ex.output(flip, "inverted") is False
    assert ex.output(length, "n") == 4  # "True"
    assert ex.output(ids[PARAM_NUMBER], "value") == 8
    assert ex.output(ids[PARAM_VALUE_LIST], "value") == 2
    assert ex.output(panels[PARAM_COLOR], "data") == Color("#0B7A7C80")
    assert isinstance(ex.output(panels[PARAM_COLORMAP], "data"), Colormap)
    assert ex.summaries[ids[PARAM_TOGGLE]] == {"value": "True"}
    assert ex.summaries[ids[PARAM_COLOR]]["value"].startswith("Color #0B7A7C80")


def test_cache_keys_follow_the_value_and_the_kind() -> None:
    g = Graph()
    t = g.add_component(PARAM_TOGGLE).id
    n = g.add_component(PARAM_NUMBER).id
    g.set_value(t, True)
    g.set_value(n, 1)
    keys = compute_keys(g)
    assert keys.nodes[t] != keys.nodes[n]  # True is not 1
    assert keys.values[keys.ports[t]["value"]] is True
    c = g.add_component(PARAM_COLORMAP).id
    before = compute_keys(g).nodes[c]
    g.set_value(c, Colormap.named("viridis", reverse=True))
    assert compute_keys(g).nodes[c] != before
    assert compute_keys(g).values[compute_keys(g).ports[c]["value"]] == Colormap.named(
        "viridis", reverse=True
    )
    # Text and Slider keys keep their recipe: a Text "1" and a Text Value List "1" share it.
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "a")
    v = g.add_component(PARAM_VALUE_LIST).id
    g.set_options(v, [{"label": "a", "value": "a"}])
    keys = compute_keys(g)
    assert keys.nodes[text] == keys.nodes[v]


def test_undo_restores_each_kind() -> None:
    g, ids = _one_of_each()
    solver = Solver(g)
    before = graph_to_dict(g)
    g.set_number(ids[PARAM_NUMBER], integer=False, value=1.5)
    g.set_value(ids[PARAM_TOGGLE], False)
    g.set_options(ids[PARAM_VALUE_LIST], [{"label": "a", "value": "a"}])
    g.set_value(ids[PARAM_COLOR], "#000000")
    g.set_value(ids[PARAM_COLORMAP], Colormap.named("blues").to_json())
    g.set_slider(ids[PARAM_SLIDER], integer=False, step=0.5)
    assert dumps(graph_to_dict(g)) != dumps(before)
    for nid in ids.values():
        solver.states[nid] = "done"
    apply_dict(g, before)
    assert dumps(graph_to_dict(g)) == dumps(before)
    # The slider's value never changed (only its step and mode): its result still holds.
    assert {nid: solver.states[nid] for nid in ids.values()} == {
        nid: "done" if kind == PARAM_SLIDER else "out_of_date" for kind, nid in ids.items()
    }


def test_export_has_a_boolean_constant_and_runs(tmp_path: Path) -> None:
    g = Graph()
    toggle = g.add_component(PARAM_TOGGLE).id
    g.set_value(toggle, True)
    flip = g.add_component("inline", source=FLIP).id
    g.add_wire(toggle, "value", flip, "flag")
    v = g.add_component(PARAM_VALUE_LIST).id
    g.set_options(v, [{"label": "a", "value": "x"}, {"label": "b", "value": 2}], value=2)
    echo = g.add_component("inline", source=ECHO).id
    g.add_wire(v, "value", echo, "text")
    number = g.add_component(PARAM_NUMBER).id
    g.set_number(number, value=4, integer=True)
    half = g.add_component("inline", source=TO_NUMBER).id
    g.add_wire(number, "value", half, "x")
    cm = g.add_component(PARAM_COLORMAP).id
    p_cm = g.add_component(PARAM_PANEL).id
    g.add_wire(cm, "value", p_cm, "data")
    p_flip = g.add_component(PARAM_PANEL).id
    g.add_wire(flip, "inverted", p_flip, "data")
    p_echo = g.add_component(PARAM_PANEL).id
    g.add_wire(echo, "same", p_echo, "data")

    script = export_script(g).script
    assert "# n1 Boolean Toggle → n2 Flip.flag\nN01_FLAG = True\n" in script
    assert "N03_TEXT = '2'" in script  # a Text Value List gives its number as text
    assert "# n3 Value List (a=x, b=2)" in script
    assert "# n5 Number (integer)" in script and "N05_X = 4\n" in script
    assert 'N07_DATA = Colormap.named("viridis")' in script
    path = tmp_path / "exported.py"
    path.write_text(script, encoding="utf-8")
    code = (
        "import runpy, sys; sys.modules['geoknit'] = None; "
        "runpy.run_path(sys.argv[1], run_name='__main__')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=tmp_path.anchor,
    )
    assert proc.returncode == 0, proc.stderr
    ex = InProcessExecutor(g)
    assert ex.run().ok
    assert f"--- Panel {p_flip} ---\nFalse\n" in proc.stdout
    assert f"--- Panel {p_echo} ---\n2\n" in proc.stdout
    assert f"--- Panel {p_cm} ---\n{types.describe(ex.output(cm, 'value'))}\n" in proc.stdout
