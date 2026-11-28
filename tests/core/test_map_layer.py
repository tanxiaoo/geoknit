"""Map Layer (change 03, section 3) and the view-node rule (section 4): engine side.

Done when (step 3): a Map Layer fed by Read Raster and a Colormap node is
``done`` as soon as Read Raster is, without running; its port key changes when
the Colormap changes and the out-of-date count does not grow beyond the
Colormap itself; Read Raster's downstream components stay done; a Panel on the
Layer shows its name, source and style.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from geoknit.components.registry import default_registry
from geoknit.core import types
from geoknit.core.cache import EMPTY_KEY, compute_keys
from geoknit.core.executor import InProcessExecutor
from geoknit.core.export import export_script
from geoknit.core.graph import (
    INLINE,
    PARAM_COLOR,
    PARAM_COLORMAP,
    PARAM_LAYER,
    PARAM_MAP,
    PARAM_PANEL,
    PARAM_SLIDER,
    PARAM_TEXT,
    Graph,
    GraphError,
    check_style,
    merge_style,
)
from geoknit.core.layers import build_layer, layer_key
from geoknit.core.workflow import (
    apply_dict,
    dumps,
    graph_from_dict,
    graph_to_dict,
    load_workflow,
    save_workflow,
)


def _component(name: str, ports: str, code: str) -> str:
    return (
        f"# geoknit: component\n# name: {name}\n# category: Test\n{ports}\n# --- code ---\n{code}\n"
    )


LIB = default_registry(Path("no-user-components"), packs=False)

MAKE_CLASSES = _component(
    "Make Classes",
    "# outputs:\n#   cmap: Colormap\n",
    "from geoknit.core.types import Colormap\n"
    "cmap = Colormap('classes', classes=((1, '#FF0000', 'one'),))",
)
WIDTH = _component(
    "Width",
    "# inputs:\n#   raster: Raster\n# outputs:\n#   n: Number\n",
    "n = raster.sizes['x']",
)
COLORMAPS = _component(
    "Colormaps",
    "# outputs:\n#   cmaps: {type: Colormap, access: list}\n",
    "from geoknit.core.types import Colormap\ncmaps = [Colormap.named('magma')]",
)


def _raster_layer(path: Path) -> tuple[Graph, dict[str, str]]:
    """Text → Read Raster → Width, Read Raster → Map Layer ← Colormap, Panel on it."""
    g = Graph()
    ids = {
        "path": g.add_component(PARAM_TEXT).id,
        "read": g.add_component("builtin/raster/read_raster", LIB).id,
        "select": g.add_component(INLINE, source=WIDTH).id,
        "cmap": g.add_component(PARAM_COLORMAP).id,
        "layer": g.add_component(PARAM_LAYER).id,
        "panel": g.add_component(PARAM_PANEL).id,
        "viewer": g.add_component(PARAM_MAP).id,
    }
    g.set_value(ids["path"], str(path))
    g.add_wire(ids["path"], "value", ids["read"], "path")
    g.add_wire(ids["read"], "raster", ids["select"], "raster")
    g.add_wire(ids["read"], "raster", ids["layer"], "data")
    g.add_wire(ids["cmap"], "value", ids["layer"], "colormap")
    g.add_wire(ids["layer"], "layer", ids["panel"], "data")
    g.add_wire(ids["layer"], "layer", ids["viewer"], "layers")
    return g, ids


# ── node, ports, style ──


def test_map_layer_ports() -> None:
    g = Graph()
    node = g.add_component(PARAM_LAYER)
    assert node.title == "Map Layer" and node.is_param and node.is_view
    assert node.inputs["data"].types == ("Raster", "Vector")
    assert [p.type for p in node.inputs.values()] == [
        "Raster", "Colormap", "Color", "Number", "Text", "Text",
    ]  # fmt: skip
    assert list(node.inputs) == ["data", "colormap", "color", "opacity", "bands", "name"]
    assert node.outputs["layer"].type == "Layer"
    text = g.add_component(PARAM_TEXT).id
    with pytest.raises(GraphError, match="Text can't connect"):
        g.add_wire(text, "value", node.id, "data")


def test_a_list_wire_into_a_style_input_is_refused() -> None:
    g = Graph()
    many = g.add_component(INLINE, source=COLORMAPS).id
    layer = g.add_component(PARAM_LAYER).id
    with pytest.raises(GraphError, match="gives a list"):
        g.add_wire(many, "cmaps", layer, "colormap")


def test_style_is_checked_and_normalised() -> None:
    style = check_style(
        {
            "colormap": "magma",
            "color": "#d62728",
            "opacity": 0.5,
            "bands": "4, 3, 2",
            "name": "AOI",
            "field": "cls",
        }
    )
    assert style == {
        "colormap": types.Colormap.named("magma").to_json(),
        "color": "#D62728",
        "opacity": 0.5,
        "bands": "4,3,2",
        "name": "AOI",
        "field": "cls",
    }
    assert check_style(style) == style  # normal form is stable
    for bad, message in (
        ({"opacity": 2}, "opacity"),
        ({"opacity": True}, "opacity"),
        ({"bands": "1,2"}, "1 or 3"),
        ({"color": "red"}, "not a colour"),
        ({"colormap": {"kind": "nope"}}, "colormap"),
        ({"name": ""}, "name is text"),
        ({"size": 3}, 'unknown style field "size"'),
    ):
        with pytest.raises(GraphError, match=message):
            check_style(bad)
    merged = merge_style(style, {"opacity": None, "name": "Other"})
    assert "opacity" not in merged and merged["name"] == "Other"


def test_set_style_marks_nothing_out_of_date(synthetic_data: dict[str, Path]) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    ex = InProcessExecutor(g)
    ex.run()
    before = compute_keys(g).ports[ids["layer"]]["layer"]
    g.set_style(ids["layer"], {"opacity": 0.4, "name": "Predictors"})
    assert all(s == "done" for s in ex.solver.states.values())
    assert compute_keys(g).ports[ids["layer"]]["layer"] != before
    with pytest.raises(GraphError, match="not a Map Layer"):
        g.set_style(ids["read"], {"opacity": 0.4})


def test_workflow_round_trip_is_byte_identical(tmp_path: Path) -> None:
    g = Graph()
    cmap = g.add_component(PARAM_COLORMAP).id
    layer = g.add_component(PARAM_LAYER).id
    g.add_wire(cmap, "value", layer, "colormap")
    g.set_style(layer, {"opacity": 0.7, "bands": "1", "name": "IMD", "color": "#123456"})
    raw = next(n for n in graph_to_dict(g)["nodes"] if n["id"] == layer)
    assert raw == {
        "id": layer,
        "component": "param/layer",
        "position": [0, 0],
        "style": {"opacity": 0.7, "bands": "1", "name": "IMD", "color": "#123456"},
    }
    path = tmp_path / "layer.geoknit"
    save_workflow(g, path)
    first = path.read_bytes()
    save_workflow(load_workflow(path), path)
    assert path.read_bytes() == first
    assert load_workflow(path).nodes[layer].style == g.nodes[layer].style


def test_a_bad_saved_style_is_refused() -> None:
    doc = {
        "format": 1,
        "nodes": [{"id": "n1", "component": "param/layer", "style": {"opacity": 3}}],
    }
    with pytest.raises(ValueError, match="opacity"):
        graph_from_dict(doc)


def test_undo_of_a_style_edit_restores_it_without_invalidating() -> None:
    g = Graph()
    layer = g.add_component(PARAM_LAYER).id
    before = graph_to_dict(g)
    g.set_style(layer, {"name": "A"})
    changed: list[set[str]] = []
    g.subscribe(lambda c, r: changed.append(c))
    apply_dict(g, before)
    assert g.nodes[layer].style == {} and not any(changed)


# ── keys, states, view-node rule ──


def test_map_layer_is_done_with_read_raster_without_running(
    synthetic_data: dict[str, Path],
) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    ex = InProcessExecutor(g)
    assert ex.solver.states[ids["layer"]] == "never_run"
    plan = ex.solver.plan()
    assert ids["layer"] not in plan and ids["viewer"] not in plan
    assert ex.solver.out_of_date_count == 2  # read, select: components only, no Params
    report = ex.run()
    assert report.ok
    assert ids["layer"] not in report.ran and ids["viewer"] not in report.ran
    assert ex.solver.states[ids["layer"]] == "done"
    assert ex.solver.states[ids["viewer"]] == "done"
    assert ex.solver.out_of_date_count == 0

    layer = ex.results[ids["layer"]]["layer"]
    keys = compute_keys(g, results=ex)
    assert isinstance(layer, types.MapLayer)
    assert layer.source == keys.ports[ids["read"]]["raster"]
    assert layer.kind == "raster" and layer.name == "Read Raster › raster"
    assert layer.colormap == types.Colormap.named("viridis") and layer.opacity == 1.0
    assert keys.nodes[ids["layer"]] is None
    assert keys.ports[ids["layer"]]["layer"] == f"{layer_key(layer.source, layer)}.layer"
    assert keys.values[keys.ports[ids["layer"]]["layer"]] == layer


def test_changing_the_colormap_restyles_without_out_of_date(
    synthetic_data: dict[str, Path],
) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    ex = InProcessExecutor(g)
    ex.run()
    before = compute_keys(g).ports[ids["layer"]]["layer"]
    g.set_value(ids["cmap"], types.Colormap.named("magma"))
    out = {n for n, s in ex.solver.states.items() if s != "done"}
    assert out == {ids["cmap"]}  # only the Colormap itself, as every Params edit
    assert ex.solver.out_of_date_count == 0  # Params never count in the banner
    assert ex.solver.states[ids["select"]] == "done"  # Read Raster's downstream component
    assert ex.solver.states[ids["layer"]] == "done"
    after = compute_keys(g).ports[ids["layer"]]["layer"]
    assert after != before
    # Wiring another colormap in, or out, carries no out-of-date either.
    other = g.add_component(PARAM_COLORMAP).id
    g.remove_wire(ids["cmap"], "value", ids["layer"], "colormap")
    g.add_wire(other, "value", ids["layer"], "colormap")
    assert ex.solver.states[ids["panel"]] == "done"
    assert ex.solver.states[ids["select"]] == "done"
    # The data wire does: the Panel on the layer goes out of date.
    g.remove_wire(ids["read"], "raster", ids["layer"], "data")
    assert ex.solver.states[ids["panel"]] == "out_of_date"
    assert ex.solver.states[ids["layer"]] == "never_run"
    assert compute_keys(g).ports[ids["layer"]]["layer"] == EMPTY_KEY


def test_panel_on_a_layer_shows_name_source_and_style(synthetic_data: dict[str, Path]) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    g.set_style(ids["layer"], {"name": "Predictors", "opacity": 0.5, "bands": "1"})
    ex = InProcessExecutor(g)
    ex.run()
    summary = ex.summaries[ids["panel"]]["data"]
    source = compute_keys(g).ports[ids["read"]]["raster"]
    assert summary.splitlines() == [
        "Layer · Predictors · raster",
        f"source {source[:12]}….raster",
        "colormap continuous · viridis · 2–98 % stretch · bands 1 · opacity 0.5",
    ]
    assert ex.views[ids["panel"]]["data"] == {"kind": "summary", "type": "Layer", "text": summary}
    assert types.describe(ex.results[ids["layer"]]["layer"]) == summary


def test_vector_layer_uses_color_and_field(synthetic_data: dict[str, Path]) -> None:
    g = Graph()
    path = g.add_component(PARAM_TEXT).id
    read = g.add_component("builtin/vector/read_vector", LIB).id
    color = g.add_component(PARAM_COLOR).id
    layer = g.add_component(PARAM_LAYER).id
    g.set_value(path, str(synthetic_data["reference"]))
    g.add_wire(path, "value", read, "path")
    g.add_wire(read, "vector", layer, "data")
    g.add_wire(color, "value", layer, "color")
    g.set_style(layer, {"field": "imd_ref", "bands": "1", "color": "#000000"})
    ex = InProcessExecutor(g)
    ex.run()
    built = compute_keys(g, results=ex).layers[layer]
    assert built.layer is not None and built.layer.kind == "vector"
    assert built.layer.color == types.Color("#0B7A7C")  # the wire wins over the saved colour
    assert built.layer.field == "imd_ref" and built.layer.bands is None
    assert built.wired == {"color": "params"}


def test_style_from_a_component_needs_its_result(synthetic_data: dict[str, Path]) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    maker = g.add_component(INLINE, source=MAKE_CLASSES).id
    g.remove_wire(ids["cmap"], "value", ids["layer"], "colormap")
    g.add_wire(maker, "cmap", ids["layer"], "colormap")
    g.set_style(ids["layer"], {"colormap": "magma"})
    ex = InProcessExecutor(g)
    unrun = compute_keys(g, results=ex).layers[ids["layer"]]
    assert "Make Classes has no result yet" in unrun.issues["colormap"]
    assert compute_keys(g).layers[ids["layer"]].issues["colormap"]  # no results at all
    ex.run()
    built = compute_keys(g, results=ex).layers[ids["layer"]]
    assert built.issues == {} and built.wired == {"colormap": "component"}
    assert built.layer is not None and built.layer.colormap is not None
    assert built.layer.colormap.kind == "classes"
    # The Map Layer's result after the run uses the component's colormap.
    assert ex.results[ids["layer"]]["layer"] == built.layer


def test_bands_by_name_and_wired_values(synthetic_data: dict[str, Path]) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    slider = g.add_component(PARAM_SLIDER).id  # 50, outside 0..1
    g.add_wire(slider, "value", ids["layer"], "opacity")
    ex = InProcessExecutor(g)
    ex.run()
    names = types.raster_band_names(ex.results[ids["read"]]["raster"])
    g.set_style(ids["layer"], {"bands": f"{names[2]},{names[1]},{names[0]}"})
    built = build_layer(g, ids["layer"], "k.raster", ex)
    assert built.layer is not None and built.layer.bands == (3, 2, 1)
    assert built.layer.opacity == 1.0 and "opacity" in built.issues
    g.set_style(ids["layer"], {"bands": "nope"})
    built = build_layer(g, ids["layer"], "k.raster", ex)
    assert built.layer is not None and built.layer.bands is None
    assert built.issues["bands"].startswith('no band "nope"')


def test_layer_json_round_trip() -> None:
    layer = types.MapLayer(
        source="ab.raster",
        kind="raster",
        name="x",
        colormap=types.Colormap.named("magma"),
        color=types.Color("#112233"),
        opacity=0.25,
        bands=(3, 2, 1),
    )
    assert types.type_of(layer) == types.LAYER
    data = types.to_json_value(layer)
    assert data["bands"] == [3, 2, 1] and data["colormap"]["name"] == "magma"
    assert types.from_json_value(types.LAYER, data) == layer
    with pytest.raises(ValueError, match="kind"):
        types.MapLayer(source="a.b", kind="table", name="x")
    with pytest.raises(ValueError, match="opacity"):
        types.MapLayer(source="a.b", kind="vector", name="x", opacity=1.5)


def test_export_keeps_working_with_a_map_layer(synthetic_data: dict[str, Path]) -> None:
    g, ids = _raster_layer(synthetic_data["predictors"])
    script = export_script(g, workflow_name="t.geoknit").script
    read, cmap, layer = (ids[k] for k in ("read", "cmap", "layer"))
    pad = {i: f"n{int(i[1:]):02d}" for i in ids.values()}
    comment = f'# {layer} Map Layer "Read Raster › raster"'
    assert f"    {comment}: {pad[read]}.raster, colormap {pad[cmap]}\n" in script
    assert f"    # {ids['viewer']} Map Viewer: {pad[layer]}.layer\n" in script
    assert '"(Map Layer, not exported)"' in script
    assert f"{pad[cmap].upper()}_COLORMAP = Colormap.named(" in script  # change 01


def test_export_comment_names_the_layer_and_every_style_wire() -> None:
    g = Graph()
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "Built-up")
    color = g.add_component(PARAM_COLOR).id
    layer = g.add_component(PARAM_LAYER).id
    g.add_wire(text, "value", layer, "name")
    g.add_wire(color, "value", layer, "color")
    script = export_script(g).script
    assert f'# {layer} Map Layer "Built-up": no data, color n02, name n01\n' in script
    g.remove_wire(text, "value", layer, "name")
    g.set_style(layer, {"name": "AOI"})
    assert f'# {layer} Map Layer "AOI": no data, color n02\n' in export_script(g).script


def test_round_trip_of_the_whole_raster_workflow(synthetic_data: dict[str, Path]) -> None:
    g, _ = _raster_layer(synthetic_data["predictors"])
    text = dumps(graph_to_dict(g))
    assert dumps(graph_to_dict(graph_from_dict(graph_to_dict(g), LIB))) == text
