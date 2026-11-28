"""The Map Viewer node (SPEC 7, 8): a Params node with a list input and no outputs.

Its ``layers`` input takes Raster, Vector and Layer (change 03, section 4); a
Panel's ``Any`` pass-through still connects, so the tests wire unwired Panels.
"""

import re
from pathlib import Path

import pytest

from geoknit.core.cache import compute_keys
from geoknit.core.executor import InProcessExecutor
from geoknit.core.graph import PARAM_MAP, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, GraphError
from geoknit.core.workflow import graph_from_dict, graph_to_dict, load_workflow, save_workflow


def _viewer() -> tuple[Graph, str, str, str]:
    g = Graph()
    first = g.add_component(PARAM_PANEL).id
    second = g.add_component(PARAM_PANEL).id
    viewer = g.add_component(PARAM_MAP).id
    g.add_wire(first, "data", viewer, "layers")
    g.add_wire(second, "data", viewer, "layers")
    return g, first, second, viewer


def test_map_viewer_takes_several_wires_and_has_no_outputs() -> None:
    g, text, _, viewer = _viewer()
    node = g.nodes[viewer]
    assert node.title == "Map Viewer" and node.is_param
    assert node.inputs["layers"].access == "list"
    assert node.inputs["layers"].types == ("Raster", "Vector", "Layer")
    assert node.outputs == {}
    assert [w.src for w in g.wires_into(viewer, "layers")] == [text, g.wires[1].src]
    with pytest.raises(GraphError):
        g.add_wire(text, "data", viewer, "layers")  # the same wire twice


def test_map_viewer_refuses_values_that_are_not_map_layers() -> None:
    g, _, _, viewer = _viewer()
    for component in (PARAM_TEXT, PARAM_SLIDER):
        src = g.add_component(component).id
        with pytest.raises(GraphError, match=re.escape("Raster | Vector | Layer")):
            g.add_wire(src, "value", viewer, "layers")


def test_map_viewer_has_no_key_and_is_done_when_its_inputs_are() -> None:
    """A view node (change 03, section 4): never in a run plan, done with its sources."""
    g, _, _, viewer = _viewer()
    keys = compute_keys(g)
    assert keys.nodes[viewer] is None and keys.ports[viewer] == {}
    ex = InProcessExecutor(g)
    assert viewer not in ex.solver.plan() and ex.solver.states[viewer] == "never_run"
    report = ex.run()
    assert report.ok and viewer not in report.ran
    assert ex.solver.states[viewer] == "done" and ex.solver.out_of_date_count == 0


def test_map_styles_are_saved_and_loaded(tmp_path: Path) -> None:
    g, _, _, viewer = _viewer()
    styles = {"basemap": "none", "styles": {"n1.value": {"colormap": "magma"}}}
    g.nodes[viewer].extra["map"] = styles
    doc = graph_to_dict(g)
    raw = next(n for n in doc["nodes"] if n["id"] == viewer)
    assert raw == {"map": styles, "id": viewer, "component": "param/map", "position": [0, 0]}
    path = tmp_path / "m.geoknit"
    save_workflow(g, path)
    back = load_workflow(path)
    assert back.nodes[viewer].extra["map"] == styles
    assert graph_to_dict(graph_from_dict(doc)) == doc
