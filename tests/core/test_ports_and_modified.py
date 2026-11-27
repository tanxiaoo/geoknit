"""Port editing from the component window, and the "modified" mark after reopening (SPEC 4)."""

import pytest

from geoknit.core.component import DictLibrary
from geoknit.core.graph import INLINE, PARAM_TEXT, Graph, GraphError
from geoknit.core.workflow import graph_from_dict, graph_to_dict, is_modified
from tests.core.sources import REPEAT

PY = """\
# geoknit: component
# name: Python
# category: Script
# ports: {inputs: editable, outputs: editable}
# inputs:
#   text: Text
# outputs:
#   n: Number

# --- code ---
n = len(text)
"""


def _graph() -> tuple[Graph, str, str, str]:
    g = Graph()
    t = g.add_component(PARAM_TEXT).id
    py = g.add_component(INLINE, source=PY).id
    g2 = g.add_component(INLINE, source=PY).id
    g.add_wire(t, "value", py, "text")
    g.add_wire(t, "value", g2, "text")
    return g, t, py, g2


def test_renamed_ports_keep_their_wires() -> None:
    g, t, py, _ = _graph()
    g.set_ports(
        py,
        [{"name": "words", "type": "Text", "was": "text"}],
        [{"name": "count", "type": "Number", "was": "n"}],
    )
    assert list(g.nodes[py].inputs) == ["words"]
    assert [(w.src, w.dst_port) for w in g.wires_into(py)] == [(t, "words")]
    assert "#   words: Text" in (g.nodes[py].source or "")


def test_removed_or_retyped_ports_drop_their_wires() -> None:
    g, t, py, _ = _graph()
    g.set_ports(py, [{"name": "text", "type": "Raster"}], [{"name": "n", "type": "Number"}])
    assert g.wires_into(py) == []  # Text can't feed a Raster input
    g.set_ports(py, [], [{"name": "n", "type": "Number"}])
    assert g.nodes[py].inputs == {}


def test_bad_ports_are_refused_and_change_nothing() -> None:
    g, _, py, _ = _graph()
    before = g.nodes[py].source
    with pytest.raises(GraphError, match="unknown type"):
        g.set_ports(py, [{"name": "x", "type": "Nope"}], [])
    assert g.nodes[py].source == before
    g.set_source(py, "# geoknit: component\n# name: [\n# --- code ---\n")
    with pytest.raises(GraphError, match="fix the code first"):
        g.set_ports(py, [], [])


def test_edited_library_component_stays_modified_after_reopening() -> None:
    lib = DictLibrary()
    lib.add("test/text/repeat", REPEAT, "0.1.0")
    g = Graph()
    node = g.add_component("test/text/repeat", lib)
    assert not is_modified(node)
    g.set_setting(node.id, "times", 3)
    assert not is_modified(node)  # settings alone are not a modification
    g.set_source(node.id, (node.source or "").replace('print(f"repeated', 'print(f"rep'))
    assert is_modified(node)

    doc = graph_to_dict(g)
    saved = doc["nodes"][0]
    assert saved["component"] == INLINE
    assert saved["based_on"] == "test/text/repeat@0.1.0"

    again = graph_from_dict(doc, lib).nodes[node.id]
    assert is_modified(again)
    assert again.source == node.source
    # without the library at hand, based_on alone still says "modified"
    assert is_modified(graph_from_dict(doc, DictLibrary()).nodes[node.id])
    # a plain inline component (no based_on) is never "modified"
    plain = graph_from_dict(
        {"format": 1, "nodes": [{"id": "n1", "component": INLINE, "source": PY}]}
    )
    assert not is_modified(plain.nodes["n1"])
