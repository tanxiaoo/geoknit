"""Cache keys (SPEC 6 "Cache"): deterministic, and they change exactly where results do."""

import os
from pathlib import Path

from geoknit.core.cache import EMPTY_KEY, compute_keys
from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph
from tests.core.sources import JOIN, LENGTH, READ_FILE, REPEAT


def _chain() -> tuple[Graph, list[str]]:
    """Text → Repeat → Length, plus an unrelated slider."""
    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "ab")
    rep = g.add_component(INLINE, source=REPEAT).id
    length = g.add_component(INLINE, source=LENGTH).id
    slider = g.add_component(PARAM_SLIDER).id
    g.add_wire(text, "value", rep, "text")
    g.add_wire(rep, "repeated", length, "text")
    return g, [text, rep, length, slider]


def test_same_graph_gives_same_keys() -> None:
    a, _ = _chain()
    b, _ = _chain()
    assert compute_keys(a).nodes == compute_keys(b).nodes
    assert compute_keys(a).ports == compute_keys(b).ports


def test_port_keys_are_node_key_plus_port() -> None:
    g, (text, rep, _, _) = _chain()
    keys = compute_keys(g)
    assert keys.ports[rep]["repeated"] == f"{keys.nodes[rep]}.repeated"
    assert keys.inputs[rep] == {"text": [keys.ports[text]["value"]]}
    assert keys.values[keys.ports[text]["value"]] == "ab"


def _changed(before: dict[str, str | None], after: dict[str, str | None]) -> set[str]:
    return {n for n in before if before[n] != after.get(n)}


def test_a_setting_changes_that_node_and_downstream_only() -> None:
    g, (text, rep, length, slider) = _chain()
    before = compute_keys(g).nodes
    g.set_setting(rep, "sep", "+")
    assert _changed(before, compute_keys(g).nodes) == {rep, length}


def test_a_value_changes_that_node_and_downstream_only() -> None:
    g, (text, rep, length, slider) = _chain()
    before = compute_keys(g).nodes
    g.set_value(text, "abc")
    assert _changed(before, compute_keys(g).nodes) == {text, rep, length}


def test_a_wire_changes_the_receiving_node_and_downstream() -> None:
    g, (text, rep, length, slider) = _chain()
    before = compute_keys(g).nodes
    g.add_wire(slider, "value", rep, "times")
    assert _changed(before, compute_keys(g).nodes) == {rep, length}


def test_list_inputs_keep_wire_order() -> None:
    g = Graph()
    a = g.add_component(PARAM_TEXT).id
    g.set_value(a, "a")
    b = g.add_component(PARAM_TEXT).id
    g.set_value(b, "b")
    j1 = g.add_component(INLINE, source=JOIN).id
    j2 = g.add_component(INLINE, source=JOIN).id
    g.add_wire(a, "value", j1, "items")
    g.add_wire(b, "value", j1, "items")
    g.add_wire(b, "value", j2, "items")
    g.add_wire(a, "value", j2, "items")
    keys = compute_keys(g)
    assert keys.nodes[j1] != keys.nodes[j2]


def test_panel_passes_its_upstream_key_through() -> None:
    g, (text, rep, _, _) = _chain()
    panel = g.add_component(PARAM_PANEL).id
    empty = g.add_component(PARAM_PANEL).id
    g.add_wire(rep, "repeated", panel, "data")
    keys = compute_keys(g)
    assert keys.nodes[panel] is None
    assert keys.ports[panel]["data"] == keys.ports[rep]["repeated"]
    assert keys.ports[empty]["data"] == EMPTY_KEY
    assert keys.values[EMPTY_KEY] is None


def test_touching_a_referenced_file_changes_keys(tmp_path: Path) -> None:
    f = tmp_path / "input.txt"
    f.write_text("one")
    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "input.txt")
    reader = g.add_component(INLINE, source=READ_FILE).id
    g.add_wire(text, "value", reader, "path")
    by_setting = g.add_component(INLINE, source=READ_FILE).id  # path from its setting
    before = compute_keys(g, tmp_path).nodes

    f.write_text("two!")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    after = compute_keys(g, tmp_path).nodes
    assert _changed(before, after) == {text, reader, by_setting}


def test_missing_files_and_plain_text_are_not_fingerprinted(tmp_path: Path) -> None:
    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "no such file.tif")
    k1 = compute_keys(g, tmp_path).nodes[text]
    assert compute_keys(g, None).nodes[text] == k1


def test_files_a_component_writes_are_not_fingerprinted(tmp_path: Path) -> None:
    from tests.core.sources import WRITE_FILE

    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "hello")
    out_path = g.add_component(PARAM_TEXT).id
    g.set_value(out_path, "output.txt")
    writer = g.add_component(INLINE, source=WRITE_FILE).id
    by_setting = g.add_component(INLINE, source=WRITE_FILE).id  # path from its setting
    g.add_wire(text, "value", writer, "text")
    g.add_wire(text, "value", by_setting, "text")
    g.add_wire(out_path, "value", writer, "path")
    before = compute_keys(g, tmp_path).nodes

    (tmp_path / "output.txt").write_text("hello")  # what the writers produce
    assert compute_keys(g, tmp_path).nodes == before


def test_a_text_that_is_also_read_keeps_its_fingerprint(tmp_path: Path) -> None:
    from tests.core.sources import WRITE_FILE

    g = Graph()
    path = g.add_component(PARAM_TEXT).id
    g.set_value(path, "input.txt")
    writer = g.add_component(INLINE, source=WRITE_FILE).id
    reader = g.add_component(INLINE, source=READ_FILE).id
    g.add_wire(path, "value", writer, "path")
    g.add_wire(path, "value", reader, "path")
    before = compute_keys(g, tmp_path).nodes
    (tmp_path / "input.txt").write_text("x")
    assert _changed(before, compute_keys(g, tmp_path).nodes) == {path, writer, reader}
