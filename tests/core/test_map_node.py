"""The Map Viewer node (SPEC 7, 8): a Params node with a list input and no outputs."""

from pathlib import Path

import pytest

from geoknit.core.cache import compute_keys
from geoknit.core.executor import InProcessExecutor
from geoknit.core.graph import PARAM_MAP, PARAM_SLIDER, PARAM_TEXT, Graph, GraphError
from geoknit.core.workflow import graph_from_dict, graph_to_dict, load_workflow, save_workflow


def _viewer() -> tuple[Graph, str, str, str]:
    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    slider = g.add_component(PARAM_SLIDER).id
    viewer = g.add_component(PARAM_MAP).id
    g.add_wire(text, "value", viewer, "layers")
    g.add_wire(slider, "value", viewer, "layers")
    return g, text, slider, viewer


def test_map_viewer_takes_several_wires_and_has_no_outputs() -> None:
    g, text, _, viewer = _viewer()
    node = g.nodes[viewer]
    assert node.title == "Map Viewer" and node.is_param
    assert node.inputs["layers"].access == "list" and node.inputs["layers"].type == "Any"
    assert node.outputs == {}
    assert [w.src for w in g.wires_into(viewer, "layers")] == [text, g.wires[1].src]
    with pytest.raises(GraphError):
        g.add_wire(text, "value", viewer, "layers")  # the same wire twice


def test_map_viewer_has_no_key_and_runs_after_its_inputs() -> None:
    g, _, _, viewer = _viewer()
    keys = compute_keys(g)
    assert keys.nodes[viewer] is None and keys.ports[viewer] == {}
    report = InProcessExecutor(g).run()
    assert report.ok and viewer in report.ran
    assert g.nodes[viewer] is not None


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
