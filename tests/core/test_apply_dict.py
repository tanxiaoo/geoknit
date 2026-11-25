"""apply_dict: move a live graph to a document with the fewest edits (undo, redo, recovery)."""

import copy
import json
from pathlib import Path

import pytest

from geoknit import __version__
from geoknit.core.component import DictLibrary
from geoknit.core.graph import PARAM_SLIDER, PARAM_TEXT
from geoknit.core.solver import DONE, NEVER_RUN, OUT_OF_DATE, Solver
from geoknit.core.workflow import (
    WorkflowError,
    apply_dict,
    dumps,
    graph_from_dict,
    graph_to_dict,
)
from tests.core.sources import LENGTH, REPEAT

DATA = Path(__file__).parent / "fixtures"


def _library() -> DictLibrary:
    lib = DictLibrary()
    lib.add("test/text/repeat", REPEAT, "0.1.0")
    lib.add("test/text/length", LENGTH, "0.1.0")
    return lib


def _loaded() -> tuple[dict, object, Solver]:
    doc = json.loads((DATA / "three_nodes.geoknit").read_text(encoding="utf-8"))
    doc["geoknit_version"] = __version__  # saving stamps the running version
    graph = graph_from_dict(doc)
    solver = Solver(graph)
    for nid in graph.nodes:
        solver.states[nid] = DONE
    return doc, graph, solver


def test_same_document_changes_nothing() -> None:
    doc, graph, solver = _loaded()
    apply_dict(graph, doc)
    assert set(solver.states.values()) == {DONE}
    assert dumps(graph_to_dict(graph)) == dumps(doc)


def test_layout_only_differences_keep_results() -> None:
    doc, graph, solver = _loaded()
    target = copy.deepcopy(doc)
    target["nodes"][1]["position"] = [999, 5]
    target["nodes"][1]["display"] = "icon"
    apply_dict(graph, target)
    assert graph.nodes["n2"].position == [999, 5] and graph.nodes["n2"].display == "icon"
    assert set(solver.states.values()) == {DONE}


def test_value_change_marks_only_downstream() -> None:
    doc, graph, solver = _loaded()
    graph.set_value("n1", "xyz")  # the edit
    for nid in graph.nodes:
        solver.states[nid] = DONE  # …and a run after it
    apply_dict(graph, doc)  # undo
    assert graph.nodes["n1"].value == "ab"
    assert solver.states == {"n1": OUT_OF_DATE, "n2": OUT_OF_DATE, "n3": OUT_OF_DATE}


def test_source_change_and_removed_wire_are_restored() -> None:
    doc, graph, solver = _loaded()
    before = dumps(graph_to_dict(graph))
    graph.remove_wire("n2", "repeated", "n3", "text")
    graph.set_source("n2", REPEAT.replace("times = 2", "times = 3"))
    for nid in graph.nodes:
        solver.states[nid] = DONE
    apply_dict(graph, doc)
    assert dumps(graph_to_dict(graph)) == before
    assert solver.states["n1"] == DONE
    assert solver.states["n2"] == OUT_OF_DATE and solver.states["n3"] == OUT_OF_DATE


def test_removed_node_comes_back_with_its_wires_and_order() -> None:
    doc, graph, _ = _loaded()
    before = dumps(graph_to_dict(graph))
    graph.remove_node("n2")
    apply_dict(graph, doc)
    assert dumps(graph_to_dict(graph)) == before


def test_added_nodes_and_groups_go_away() -> None:
    doc, graph, solver = _loaded()
    graph.add_component(PARAM_SLIDER, position=[0, 300])
    graph.groups.append({"title": "G", "nodes": ["n1", "n2"]})
    apply_dict(graph, doc)
    assert list(graph.nodes) == ["n1", "n2", "n3"] and graph.groups == []
    assert set(solver.states.values()) == {DONE}


def test_library_nodes_and_sliders() -> None:
    lib = _library()
    graph = graph_from_dict({"format": 1, "nodes": [], "wires": [], "groups": [], "view": {}}, lib)
    solver = Solver(graph)
    s = graph.add_component(PARAM_SLIDER).id
    r = graph.add_component("test/text/repeat", lib).id
    t = graph.add_component(PARAM_TEXT).id
    graph.add_wire(t, "value", r, "text")
    graph.add_wire(s, "value", r, "times")
    snap = graph_to_dict(graph)
    graph.set_slider(s, min=10, max=20, value=15)
    graph.set_setting(r, "sep", "+")
    apply_dict(graph, snap, lib)
    assert dumps(graph_to_dict(graph)) == dumps(snap)
    assert graph.nodes[s].min == 0 and graph.nodes[s].value == 50
    assert solver.states[r] == NEVER_RUN


def test_view_only_when_asked() -> None:
    doc, graph, _ = _loaded()
    target = copy.deepcopy(doc)
    target["view"] = {"display": "icon"}
    apply_dict(graph, target)
    assert graph.view == {}
    apply_dict(graph, target, view=True)
    assert graph.view == {"display": "icon"}


def test_bad_document_is_refused() -> None:
    doc, graph, _ = _loaded()
    target = copy.deepcopy(doc)
    target["wires"].append({"from": ["n1", "value"], "to": ["n3", "nope"]})
    with pytest.raises(WorkflowError, match="nope"):
        apply_dict(graph, target)


def test_removing_the_last_member_drops_the_group() -> None:
    _, graph, _ = _loaded()
    graph.groups = [{"title": "A", "nodes": ["n2"]}, {"title": "B", "nodes": ["n2", "n3"]}]
    graph.remove_node("n2")
    assert graph.groups == [{"title": "B", "nodes": ["n3"]}]
