"""Graph wiring rules, out-of-date propagation and run plans (SPEC 3, 6)."""

import pytest

from geoknit.core.component import DictLibrary
from geoknit.core.executor import InProcessExecutor
from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, GraphError
from geoknit.core.solver import DONE, NEVER_RUN, OUT_OF_DATE, Solver
from tests.core.sources import LENGTH, MAKE_RASTER, REPEAT, TO_NUMBER


def _text(g: Graph, value: str) -> str:
    nid = g.add_component(PARAM_TEXT).id
    g.set_value(nid, value)
    return nid


def test_raster_to_number_is_refused() -> None:
    g = Graph()
    raster = g.add_component(INLINE, source=MAKE_RASTER).id
    half = g.add_component(INLINE, source=TO_NUMBER).id
    with pytest.raises(GraphError, match="Raster can't connect to Number"):
        g.add_wire(raster, "raster", half, "x")
    assert g.wires == []


def test_cycle_is_refused() -> None:
    g = Graph()
    a = g.add_component(INLINE, source=REPEAT).id
    b = g.add_component(INLINE, source=REPEAT).id
    c = g.add_component(INLINE, source=REPEAT).id
    g.add_wire(a, "repeated", b, "text")
    g.add_wire(b, "repeated", c, "text")
    with pytest.raises(GraphError, match="would create a cycle"):
        g.add_wire(c, "repeated", a, "text")
    with pytest.raises(GraphError, match="would create a cycle"):
        g.add_wire(a, "repeated", a, "text")
    assert len(g.wires) == 2


def test_other_wiring_rules() -> None:
    g = Graph()
    slider = g.add_component(PARAM_SLIDER).id
    rep = g.add_component(INLINE, source=REPEAT).id
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(slider, "value", rep, "text")  # Number → Text is allowed
    with pytest.raises(GraphError, match="already connected"):
        g.add_wire(_text(g, "x"), "value", rep, "text")  # item input takes one wire
    with pytest.raises(GraphError, match='no output "nope"'):
        g.add_wire(rep, "nope", panel, "data")
    g.add_wire(rep, "repeated", panel, "data")  # anything → Any
    half = g.add_component(INLINE, source=TO_NUMBER).id
    # The Panel's pass-through takes the type of its input (SPEC 4, like: data).
    with pytest.raises(GraphError, match="Text can't connect to Number"):
        g.add_wire(panel, "data", half, "x")
    ex = InProcessExecutor(g)
    ex.run()
    assert ex.output(rep, "repeated") == "50-50"


def test_changing_a_setting_marks_only_node_and_downstream() -> None:
    g = Graph()
    t1 = _text(g, "ab")
    rep = g.add_component(INLINE, source=REPEAT).id
    length = g.add_component(INLINE, source=LENGTH).id
    t2 = _text(g, "other branch")
    length2 = g.add_component(INLINE, source=LENGTH).id
    g.add_wire(t1, "value", rep, "text")
    g.add_wire(rep, "repeated", length, "text")
    g.add_wire(t2, "value", length2, "text")
    ex = InProcessExecutor(g)
    solver = ex.solver
    assert set(solver.states.values()) == {NEVER_RUN}
    assert ex.run().ok
    assert set(solver.states.values()) == {DONE}

    g.set_setting(rep, "sep", "+")
    assert {n for n, s in solver.states.items() if s == OUT_OF_DATE} == {rep, length}
    assert solver.out_of_date_count == 2
    assert solver.plan() == [rep, length]
    report = ex.run()
    assert report.ran == [rep, length]
    assert ex.output(length, "n") == 5  # "ab+ab"

    g.set_position(t2, [10, 10])  # moving does not invalidate
    g.set_display(t2, "icon")
    assert solver.out_of_date_count == 0
    g.set_value(t1, "abc")
    assert solver.plan() == [t1, rep, length]


def test_wire_changes_and_removal_invalidate_downstream() -> None:
    g = Graph()
    t = _text(g, "ab")
    rep = g.add_component(INLINE, source=REPEAT).id
    length = g.add_component(INLINE, source=LENGTH).id
    g.add_wire(rep, "repeated", length, "text")
    g.add_wire(t, "value", rep, "text")
    ex = InProcessExecutor(g)
    ex.run()
    g.remove_wire(t, "value", rep, "text")
    assert ex.solver.plan() == [rep, length]
    g.remove_node(rep)
    assert rep not in ex.solver.states and rep not in ex.results
    assert g.wires == []
    assert ex.solver.states[length] == OUT_OF_DATE


def test_run_to_here_and_test_plans() -> None:
    g = Graph()
    t = _text(g, "ab")
    rep = g.add_component(INLINE, source=REPEAT).id
    length = g.add_component(INLINE, source=LENGTH).id
    other = _text(g, "unrelated")
    g.add_wire(t, "value", rep, "text")
    g.add_wire(rep, "repeated", length, "text")
    solver = Solver(g)
    assert solver.plan("to_node", rep) == [t, rep]
    assert solver.plan("test", length) == [length]
    assert solver.plan() == [t, rep, length, other]
    with pytest.raises(GraphError, match="unknown run mode"):
        solver.plan("sideways", rep)


def test_test_mode_needs_cached_inputs_and_errors_skip_downstream() -> None:
    g = Graph()
    t = _text(g, "ab")
    rep = g.add_component(INLINE, source=REPEAT).id
    length = g.add_component(INLINE, source=LENGTH).id
    g.add_wire(t, "value", rep, "text")
    g.add_wire(rep, "repeated", length, "text")
    ex = InProcessExecutor(g)
    ex.run("test", length)
    assert "has no result yet; run it first" in ex.errors[length]

    broken = REPEAT.replace("times = 2", "times = 0").replace(
        "repeated = sep.join([text] * int(times))", "repeated = text * int(1 / times)"
    )
    g.set_source(rep, broken)
    report = ex.run()
    assert report.failed == [rep] and report.skipped == [length]
    assert ex.solver.states[length] == "skipped"
    assert "ZeroDivisionError" in ex.errors[rep]


def test_library_component_and_unknown_reference() -> None:
    lib = DictLibrary()
    lib.add("test/repeat", REPEAT)
    g = Graph()
    node = g.add_component("test/repeat", lib)
    assert (node.version, node.title) == ("0.1.0", "Repeat")
    with pytest.raises(GraphError, match='unknown component "test/missing"'):
        g.add_component("test/missing", lib)


def test_code_change_drops_wires_to_removed_ports() -> None:
    g = Graph()
    rep = g.add_component(INLINE, source=REPEAT).id
    length = g.add_component(INLINE, source=LENGTH).id
    g.add_wire(rep, "repeated", length, "text")
    g.set_source(rep, REPEAT.replace("repeated", "result"))
    assert g.wires == []
    g.set_source(length, "broken")  # parse error keeps the last good ports
    assert g.nodes[length].parse_error is not None
    assert "text" in g.nodes[length].inputs
