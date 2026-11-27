"""Union input types and ``like:`` outputs (change 01 step 2, SPEC 3 and 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from geoknit.components.registry import default_registry
from geoknit.core.component import ComponentParseError, parse_component
from geoknit.core.executor import InProcessExecutor
from geoknit.core.graph import INLINE, PARAM_PANEL, Graph, GraphError
from geoknit.core.workflow import graph_from_dict, graph_to_dict
from geoknit.runtime import protocol as p
from geoknit.runtime.worker import Worker
from tests.core.sources import TO_NUMBER


def _component(name: str, ports: str, code: str) -> str:
    return (
        f"# geoknit: component\n# name: {name}\n# category: Test\n{ports}\n# --- code ---\n{code}\n"
    )


MAKE_VECTOR = _component(
    "Make Vector",
    "# outputs:\n#   vector: Vector\n",
    "import geopandas as gpd\nfrom shapely.geometry import Point\n"
    "vector = gpd.GeoDataFrame({'a': [1]}, geometry=[Point(0, 0)], crs=4326)",
)
MAKE_TABLE = _component(
    "Make Table",
    "# outputs:\n#   table: Table\n",
    "import pandas as pd\ntable = pd.DataFrame({'a': [1]})",
)
MAKE_RASTER = _component(
    "Make Raster",
    "# outputs:\n#   raster: Raster\n",
    "import numpy as np\nimport xarray as xr\n"
    "raster = xr.DataArray(np.zeros((1, 2, 2)), dims=('band', 'y', 'x'))",
)
SELECT = _component(
    "Select",
    "# inputs:\n#   data: [Table, Vector]\n# outputs:\n#   selected: {like: data}\n",
    "selected = data",
)
TO_FRAME = _component(
    "To Frame",
    "# inputs:\n#   data: [Table, Vector]\n# outputs:\n#   out: {like: data}\n",
    "import pandas as pd\nout = pd.DataFrame(data.drop(columns='geometry', errors='ignore'))",
)
VECTOR_ONLY = _component("Vector Only", "# inputs:\n#   v: Vector\n", "pass")
TABLE_ONLY = _component("Table Only", "# inputs:\n#   t: Table\n", "pass")


def _add(g: Graph, source: str) -> str:
    return g.add_component(INLINE, source=source).id


# ── header parser ──


def test_union_and_like_ports_parse() -> None:
    spec = parse_component(SELECT)
    data = spec.inputs["data"]
    assert data.type == "Table" and data.types == ("Table", "Vector")
    out = spec.outputs["selected"]
    assert out.like == "data" and out.types == ("Table", "Vector") and out.type == "Table"
    one = parse_component(SELECT.replace("[Table, Vector]", "[Raster]"))
    assert one.inputs["data"].types == ("Raster",)
    dict_form = parse_component(SELECT.replace("[Table, Vector]", "{type: [Table, Vector]}"))
    assert dict_form.inputs["data"].types == ("Table", "Vector")


@pytest.mark.parametrize(
    ("before", "after", "message"),
    [
        ("{like: data}", "{like: nope}", 'like: must name an input, not "nope"'),
        ("[Table, Vector]", "[Table, Any]", "Any cannot be part of a list"),
        ("[Table, Vector]", "[Table, Table]", 'lists the type "Table" twice'),
        ("{like: data}", "{like: data, type: Table}", "either like: or type:"),
        ("{like: data}", "[Table, Vector]", "only inputs can list several types"),
        ("[Table, Vector]", "[Table, Grid]", 'unknown type "Grid"'),
        ("[Table, Vector]", "{like: selected}", "only outputs can use like:"),
    ],
)
def test_header_errors(before: str, after: str, message: str) -> None:
    with pytest.raises(ComponentParseError, match=message):
        parse_component(SELECT.replace(before, after, 1))


# ── wiring ──


def test_like_output_follows_its_input_and_rewiring_removes_wires() -> None:
    g = Graph()
    vec, table, sel = _add(g, MAKE_VECTOR), _add(g, MAKE_TABLE), _add(g, SELECT)
    vonly, tonly = _add(g, VECTOR_ONLY), _add(g, TABLE_ONLY)
    assert g.output_types(sel, "selected") == ("Table", "Vector")  # unresolved
    assert g.output_type(sel, "selected") is None
    g.add_wire(vec, "vector", sel, "data")
    assert g.output_type(sel, "selected") == "Vector"
    g.add_wire(sel, "selected", vonly, "v")
    with pytest.raises(GraphError, match="Vector can't connect to Table"):
        g.add_wire(sel, "selected", tonly, "t")
    # re-wire data from a Table: the wire into the Vector-only input goes
    g.remove_wire(vec, "vector", sel, "data")
    assert len(g.wires) == 1  # unresolved, still fits a Vector input
    changed: list[set[str]] = []
    g.subscribe(lambda c, r: changed.append(c))
    g.add_wire(table, "table", sel, "data")
    assert [(w.src, w.dst) for w in g.wires] == [(table, sel)]
    assert any(vonly in c for c in changed)  # the node that lost a wire is out of date


def test_refusal_lists_the_union() -> None:
    g = Graph()
    raster, sel = _add(g, MAKE_RASTER), _add(g, SELECT)
    with pytest.raises(GraphError, match=r"^Raster can't connect to Table \| Vector$"):
        g.add_wire(raster, "raster", sel, "data")


@pytest.mark.parametrize("with_panel", [False, True])
def test_like_chain_re_resolves_end_to_end(with_panel: bool) -> None:
    g = Graph()
    vec, table = _add(g, MAKE_VECTOR), _add(g, MAKE_TABLE)
    first, second = _add(g, SELECT), _add(g, SELECT)
    vonly = _add(g, VECTOR_ONLY)
    g.add_wire(vec, "vector", first, "data")
    if with_panel:
        panel = g.add_component(PARAM_PANEL).id
        g.add_wire(first, "selected", panel, "data")
        g.add_wire(panel, "data", second, "data")
        assert g.output_type(panel, "data") == "Vector"
    else:
        g.add_wire(first, "selected", second, "data")
    g.add_wire(second, "selected", vonly, "v")
    assert g.output_type(second, "selected") == "Vector"
    g.remove_wire(vec, "vector", first, "data")
    g.add_wire(table, "table", first, "data")
    assert g.output_type(second, "selected") == "Table"
    assert not g.wires_into(vonly)
    assert len(g.wires) == (4 if with_panel else 3) - 1


def test_panel_takes_the_type_of_its_input() -> None:
    g = Graph()
    read = g.add_component("builtin/raster/read_raster", default_registry(packs=False)).id
    panel = g.add_component(PARAM_PANEL).id
    half = _add(g, TO_NUMBER)
    g.add_wire(read, "raster", panel, "data")
    with pytest.raises(GraphError, match="Raster can't connect to Number"):
        g.add_wire(panel, "data", half, "x")
    # an unwired Panel's output connects anywhere ...
    g.remove_wire(read, "raster", panel, "data")
    assert g.output_types(panel, "data") == ("Any",)
    g.add_wire(panel, "data", half, "x")
    vonly = _add(g, VECTOR_ONLY)
    other = g.add_component(PARAM_PANEL).id
    g.add_wire(other, "data", vonly, "v")
    # ... and its outgoing wires are re-checked once it is wired
    g.add_wire(read, "raster", panel, "data")
    assert not g.wires_into(half)


def test_load_checks_wires_after_all_are_added() -> None:
    g = Graph()
    vec, sel, vonly = _add(g, MAKE_VECTOR), _add(g, SELECT), _add(g, VECTOR_ONLY)
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(vec, "vector", panel, "data")
    g.add_wire(panel, "data", sel, "data")
    g.add_wire(sel, "selected", vonly, "v")
    data = graph_to_dict(g)
    data["wires"].reverse()  # the wire out of a like: output comes first
    loaded = graph_from_dict(data)
    assert len(loaded.wires) == 3
    assert loaded.output_type(sel, "selected") == "Vector"


# ── run ──


def test_like_output_value_must_have_the_resolved_type(tmp_path: Path) -> None:
    g = Graph()
    vec, conv = _add(g, MAKE_VECTOR), _add(g, TO_FRAME)
    g.add_wire(vec, "vector", conv, "data")
    ex = InProcessExecutor(g)
    ex.run()
    assert ex.errors[conv] == 'output "out": expected Vector, got Table'

    # the worker checks the types the server sends with run_node
    sent: list[object] = []
    w = Worker(sent.append, tmp_path, None)
    w.handle(p.RunNode("a", MAKE_VECTOR, {}, "k1"))
    w.handle(p.RunNode("b", TO_FRAME, {"data": "k1.vector"}, "k2", {"out": "Vector"}))
    errors = [m for m in sent if isinstance(m, p.Error)]
    assert [e.traceback for e in errors] == ['output "out": expected Vector, got Table']
    sent.clear()
    w.handle(p.RunNode("c", TO_FRAME, {"data": "k1.vector"}, "k3"))  # unresolved: declared types
    assert any(isinstance(m, p.Done) for m in sent)


def test_union_input_checked_when_run() -> None:
    from geoknit.core.component import run_component

    result = run_component(parse_component(SELECT), {"data": 3})
    assert result.error == 'input "data": expected Table | Vector, got Number'
