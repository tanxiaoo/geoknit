"""Editable ports for any component and the INPUTS dict (change 01, SPEC 4)."""

from pathlib import Path

import pytest

from geoknit.core.component import (
    DEFAULT_EDITABLE_TYPES,
    ComponentParseError,
    EditablePorts,
    parse_component,
)
from geoknit.core.executor import InProcessExecutor
from geoknit.core.export import export_script
from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, GraphError
from tests.core.test_export import _run_script

CALC = """\
# geoknit: component
# name: Raster Calculator
# category: Raster
# ports: {inputs: editable, types: [Raster, Number]}
# inputs:
#   a: Raster
# outputs:
#   result: Raster

# --- code ---
result = a
"""

FIXED = """\
# geoknit: component
# name: Fixed
# category: Script
# inputs:
#   x: Number
# outputs:
#   y: Number

# --- code ---
y = x
"""

SEES_INPUTS = """\
# geoknit: component
# name: Show Inputs
# category: Text
# inputs:
#   a: Number
#   b: Text
# outputs:
#   shown: Text

# --- settings ---
b = "from the setting"

# --- code ---
shown = ", ".join(f"{k}={v!r}" for k, v in INPUTS.items())
"""


def _header(ports_line: str) -> str:
    return CALC.replace("# ports: {inputs: editable, types: [Raster, Number]}", ports_line)


# ── header ──


def test_ports_key_parses() -> None:
    assert parse_component(CALC).ports == EditablePorts(
        inputs=True, outputs=False, types=("Raster", "Number")
    )
    both = parse_component(_header("# ports: {inputs: editable, outputs: editable}"))
    assert both.ports == EditablePorts(True, True, DEFAULT_EDITABLE_TYPES, any_inputs=True)
    assert "Layer" not in DEFAULT_EDITABLE_TYPES and "Any" not in DEFAULT_EDITABLE_TYPES
    assert parse_component(FIXED).ports is None


def test_default_types_offer_any_for_inputs_only() -> None:
    both = parse_component(_header("# ports: {inputs: editable, outputs: editable}")).ports
    assert both is not None
    assert both.types_for("inputs") == (*DEFAULT_EDITABLE_TYPES, "Any")
    assert both.types_for("outputs") == DEFAULT_EDITABLE_TYPES
    assert both.as_dict()["input_types"][-1] == "Any"
    listed = parse_component(CALC).ports
    assert listed is not None and listed.types_for("inputs") == ("Raster", "Number")

    g = Graph()
    n = g.add_component(INLINE, source=_header("# ports: {inputs: editable, outputs: editable}"))
    g.set_ports(n.id, inputs=[{"name": "a", "type": "Any"}], outputs=None)
    assert g.nodes[n.id].inputs["a"].type == "Any"
    with pytest.raises(GraphError, match="outputs are Number, Text"):
        g.set_ports(n.id, inputs=None, outputs=[{"name": "result", "type": "Any"}])


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("# ports: editable", "ports must look like"),
        ("# ports: {inputs: yes}", 'inputs can only be "editable"'),
        ("# ports: {types: [Raster]}", "needs inputs: editable or outputs: editable"),
        ("# ports: {inputs: editable, types: [Pixel]}", 'unknown type "Pixel"'),
        ("# ports: {inputs: editable, types: [Raster, Raster]}", 'lists "Raster" twice'),
        ("# ports: {inputs: editable, sides: 2}", 'unknown key "sides"'),
    ],
)
def test_bad_ports_key_is_a_parse_error(line: str, message: str) -> None:
    with pytest.raises(ComponentParseError, match=message):
        parse_component(_header(line))


def test_inputs_is_a_reserved_name() -> None:
    with pytest.raises(ComponentParseError, match='"INPUTS" is reserved'):
        parse_component(FIXED.replace("#   x: Number", "#   INPUTS: Number"))
    with pytest.raises(ComponentParseError, match='"INPUTS" is reserved') as exc:
        parse_component(
            FIXED.replace("# --- code ---", "# --- settings ---\nINPUTS = 1\n# --- code ---")
        )
    assert exc.value.line == 10


# ── Graph.set_ports ──


def test_editable_inputs_take_only_the_listed_types() -> None:
    g = Graph()
    calc = g.add_component(INLINE, source=CALC).id
    a = {"name": "a", "type": "Raster"}
    out = [{"name": "result", "type": "Raster"}]
    g.set_ports(calc, [a, {"name": "b", "type": "Number"}], out)
    assert {n: p.type for n, p in g.nodes[calc].inputs.items()} == {"a": "Raster", "b": "Number"}
    before = g.nodes[calc].source
    with pytest.raises(GraphError, match="Raster Calculator inputs are Raster or Number"):
        g.set_ports(calc, [a, {"name": "b", "type": "Text"}], out)
    with pytest.raises(GraphError, match="the outputs of Raster Calculator cannot be edited"):
        g.set_ports(calc, [a], [{"name": "result", "type": "Number"}])
    with pytest.raises(GraphError, match="the outputs of Raster Calculator cannot be edited"):
        g.set_ports(calc, [a], [*out, {"name": "extra", "type": "Raster"}])
    assert g.nodes[calc].source == before
    g.set_ports(calc, [a], None)  # a side left out stays as it is
    assert list(g.nodes[calc].outputs) == ["result"]


def test_a_declared_port_outside_types_may_stay() -> None:
    source = CALC.replace("#   a: Raster", "#   a: Raster\n#   label: Text")
    g = Graph()
    calc = g.add_component(INLINE, source=source).id
    g.set_ports(
        calc,
        [{"name": "a", "type": "Raster"}, {"name": "title", "type": "Text", "was": "label"}],
        None,
    )
    assert list(g.nodes[calc].inputs) == ["a", "title"]


def test_components_without_ports_key_cannot_be_edited() -> None:
    g = Graph()
    fixed = g.add_component(INLINE, source=FIXED).id
    with pytest.raises(GraphError, match="the inputs of Fixed cannot be edited"):
        g.set_ports(fixed, [{"name": "x", "type": "Text"}], None)
    g.set_ports(fixed, None, None)  # nothing changed: nothing refused


def test_unchanged_side_keeps_like_and_union_ports() -> None:
    source = """\
# geoknit: component
# name: Pick
# category: Table
# ports: {outputs: editable}
# inputs:
#   data: [Table, Vector]
# outputs:
#   picked: {like: data}

# --- code ---
picked = data
"""
    g = Graph()
    pick = g.add_component(INLINE, source=source).id
    g.set_ports(
        pick,
        None,
        [{"name": "picked", "type": "Table", "like": "data"}, {"name": "n", "type": "Number"}],
    )
    node = g.nodes[pick]
    assert node.inputs["data"].types == ("Table", "Vector")
    assert node.outputs["picked"].like == "data"


# ── INPUTS ──


def _inputs_graph() -> tuple[Graph, str, str]:
    g = Graph()
    s = g.add_component(PARAM_SLIDER).id
    g.set_slider(s, value=3)
    node = g.add_component(INLINE, source=SEES_INPUTS).id
    g.add_wire(s, "value", node, "a")
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(node, "shown", panel, "data")
    return g, node, panel


EXPECTED = "a=3, b='from the setting'"


def test_inputs_dict_in_geoknit_and_in_the_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g, node, panel = _inputs_graph()
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert ex.output(node, "shown") == EXPECTED

    script = export_script(g).script
    assert '    INPUTS = {"a": a, "b": b}\n    # --- code ---' in script
    assert _run_script(script, tmp_path, monkeypatch) == {panel: EXPECTED}


def test_export_defines_inputs_only_where_the_code_uses_it() -> None:
    g = Graph()
    t = g.add_component(PARAM_TEXT).id
    fixed = g.add_component(INLINE, source=FIXED.replace("x: Number", "x: Text")).id
    g.add_wire(t, "value", fixed, "x")
    assert "INPUTS" not in export_script(g).script
