"""Workflow files (SPEC 5) and running a workflow loaded from JSON."""

import json
import shutil
from pathlib import Path

import pytest

from geoknit.core.component import DictLibrary
from geoknit.core.executor import InProcessExecutor
from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph
from geoknit.core.workflow import (
    FORMAT,
    WorkflowError,
    graph_from_dict,
    load_workflow,
    save_workflow,
)
from tests.core.sources import LENGTH, REPEAT

DATA = Path(__file__).parent / "data"


def _library() -> DictLibrary:
    lib = DictLibrary()
    lib.add("test/text/repeat", REPEAT, "0.1.0")
    lib.add("test/text/length", LENGTH, "0.1.0")
    return lib


def test_three_node_graph_from_json_runs(tmp_path: Path) -> None:
    graph = load_workflow(DATA / "three_nodes.geoknit")
    events: list[tuple[str, str]] = []
    ex = InProcessExecutor(
        graph, base_dir=tmp_path, on_event=lambda e: events.append((e.kind, e.node_id))
    )
    report = ex.run()
    assert report.ok and report.ran == ["n1", "n2", "n3"]
    assert ex.output("n2", "repeated") == "ab-ab"
    assert ex.output("n3", "n") == 5
    assert ex.logs["n2"] == ["repeated 2 times"]
    assert ex.summaries["n3"] == {"n": "5"}
    assert events[:4] == [("started", "n1"), ("done", "n1"), ("started", "n2"), ("log", "n2")]


def _build(lib: DictLibrary) -> Graph:
    g = Graph()
    text = g.add_component(PARAM_TEXT, position=[16, 41]).id
    g.set_value(text, "data/clms.tif")
    slider = g.add_component(PARAM_SLIDER, position=[16, 480]).id
    g.set_slider(slider, min=50, max=1000, step=50, value=300)
    rep = g.add_component("test/text/repeat", lib, position=[200, 0]).id
    g.set_setting(rep, "sep", "_")
    modified = g.add_component("test/text/repeat", lib, position=[200, 200]).id
    g.set_source(modified, REPEAT.replace('print(f"repeated', 'print(f"did'))
    length = g.add_component("test/text/length", lib, position=[400, 0]).id
    inline = g.add_component(INLINE, source=LENGTH, position=[400, 200]).id
    panel = g.add_component(PARAM_PANEL, position=[600, 0]).id
    g.add_wire(text, "value", rep, "text")
    g.add_wire(slider, "value", modified, "text")
    g.add_wire(rep, "repeated", length, "text")
    g.add_wire(modified, "repeated", inline, "text")
    g.add_wire(length, "n", panel, "data")
    g.set_display(inline, "icon")
    g.groups = [{"title": "Train · predict", "nodes": [rep, length]}]
    g.view = {"display": "text", "offset": [0, 0], "zoom": 1.0}
    return g


def test_save_load_save_is_identical(tmp_path: Path) -> None:
    lib = _library()
    first = tmp_path / "a.geoknit"
    second = tmp_path / "b.geoknit"
    save_workflow(_build(lib), first)
    save_workflow(load_workflow(first, lib), second)
    assert first.read_bytes() == second.read_bytes()

    data = json.loads(first.read_text(encoding="utf-8"))
    assert data["format"] == FORMAT
    nodes = {n["id"]: n for n in data["nodes"]}
    assert nodes["n3"]["component"] == "test/text/repeat"  # unmodified: by reference
    assert nodes["n3"]["settings"] == {"sep": "_", "times": 2}
    assert "source" not in nodes["n3"]
    assert nodes["n4"]["component"] == "inline"  # code edited: stored inline
    assert nodes["n4"]["based_on"] == "test/text/repeat@0.1.0"
    assert nodes["n2"] == {
        "component": "param/slider", "id": "n2", "max": 1000, "min": 50,
        "position": [16, 480], "step": 50, "value": 300,
    }  # fmt: skip
    text = first.read_text(encoding="utf-8")
    assert text.endswith("}\n") and '\n  "format": 1,' in text  # sorted, 2-space indent

    # The reloaded workflow gives the same results.
    ex = InProcessExecutor(load_workflow(first, lib))
    assert ex.run().ok
    assert ex.output("n5", "n") == len("data/clms.tif_data/clms.tif")
    assert ex.output("n6", "n") == len("300-300")


def test_paths_inside_project_saved_relative(tmp_path: Path) -> None:
    g = Graph()
    inside = g.add_component(PARAM_TEXT).id
    outside = g.add_component(PARAM_TEXT).id
    g.set_value(inside, str(tmp_path / "data" / "aoi.gpkg"))
    other = tmp_path.parent / "elsewhere.tif"
    g.set_value(outside, str(other))
    save_workflow(g, tmp_path / "w.geoknit")
    nodes = json.loads((tmp_path / "w.geoknit").read_text(encoding="utf-8"))["nodes"]
    assert nodes[0]["value"] == "data/aoi.gpkg"
    assert nodes[1]["value"] == str(other)


def test_relative_paths_resolve_against_workflow_folder(tmp_path: Path) -> None:
    shutil.copy(DATA / "three_nodes.geoknit", tmp_path / "w.geoknit")
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    reader = (
        "# geoknit: component\n# name: Read Text\n# inputs:\n#   path: Text\n"
        "# outputs:\n#   text: Text\n\n# --- code ---\n"
        "from pathlib import Path\ntext = Path(path).read_text()\n"
    )
    g = load_workflow(tmp_path / "w.geoknit")
    t = g.add_component(PARAM_TEXT).id
    g.set_value(t, "hello.txt")
    r = g.add_component(INLINE, source=reader).id
    g.add_wire(t, "value", r, "path")
    ex = InProcessExecutor(g, base_dir=tmp_path)
    assert ex.run().ok
    assert ex.output(r, "text") == "hello"


def test_unknown_keys_survive_and_format_checks(tmp_path: Path) -> None:
    doc = json.loads((DATA / "three_nodes.geoknit").read_text(encoding="utf-8"))
    doc["nodes"][0]["size"] = [120, 80]
    g = graph_from_dict(doc)
    save_workflow(g, tmp_path / "w.geoknit")
    assert json.loads((tmp_path / "w.geoknit").read_text(encoding="utf-8"))["nodes"][0]["size"] == [
        120,
        80,
    ]
    with pytest.raises(WorkflowError, match="newer than this GeoKnit"):
        graph_from_dict({**doc, "format": FORMAT + 1})
    with pytest.raises(WorkflowError, match='missing "format"'):
        graph_from_dict({"nodes": []})
    with pytest.raises(WorkflowError, match="no library"):
        graph_from_dict({"format": 1, "nodes": [{"id": "n1", "component": "test/text/repeat"}]})
