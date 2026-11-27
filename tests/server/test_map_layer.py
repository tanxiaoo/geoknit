"""Map Layer through the API (change 03, sections 3, 4, 6): no Run for styles.

Done when (step 3, server side): a Map Layer fed by Read Raster and a Colormap
is ``done`` as soon as Read Raster is, without a worker run (no ``started``
event); its port key changes when the Colormap changes and only the Colormap
counts as out of date; Read Raster's downstream components stay done; a Panel
on the Layer shows name, source and style.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from geoknit.core import types
from tests.server.conftest import collect_until_finished, make_client

MAKE_CLASSES = (
    "# geoknit: component\n# name: Make Classes\n# category: Test\n"
    "# outputs:\n#   cmap: Colormap\n# --- code ---\n"
    "from geoknit.core.types import Colormap\n"
    "cmap = Colormap('classes', classes=((1, '#FF0000', 'one'),))\n"
)
WIDTH = (
    "# geoknit: component\n# name: Width\n# category: Test\n"
    "# inputs:\n#   raster: Raster\n# outputs:\n#   n: Number\n# --- code ---\n"
    "n = raster.sizes['x']\n"
)


def _add(client: TestClient, component: str, **body: Any) -> str:
    r = client.post("/api/nodes", json={"component": component, **body})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wire(client: TestClient, src: str, sp: str, dst: str, dp: str) -> None:
    r = client.post("/api/wires", json={"from": [src, sp], "to": [dst, dp]})
    assert r.status_code == 201, r.text


def _patch(client: TestClient, node: str, **body: Any) -> dict[str, Any]:
    r = client.patch(f"/api/nodes/{node}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _graph(client: TestClient) -> dict[str, Any]:
    return client.get("/api/graph").json()


def _until_states(ws: Any) -> list[dict[str, Any]]:
    events = []
    while True:
        msg = ws.receive_json()
        events.append(msg)
        if msg["type"] == "states":
            return events


@pytest.fixture
def setup(
    tmp_path: Path, synthetic_data: dict[str, Path]
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    project = tmp_path / "project"
    project.mkdir()
    for name in ("predictors", "reference"):
        shutil.copy(synthetic_data[name], project / synthetic_data[name].name)
    with make_client(project, tmp_path / "home" / "trusted.json") as client:
        ids = {
            "path": _add(client, "param/text"),
            "read": _add(client, "builtin/raster/read_raster"),
            "width": _add(client, "inline", source=WIDTH),
            "cmap": _add(client, "param/colormap"),
            "layer": _add(client, "param/layer"),
            "panel": _add(client, "param/panel"),
            "viewer": _add(client, "param/map"),
        }
        _patch(client, ids["path"], value="predictors.tif")
        _wire(client, ids["path"], "value", ids["read"], "path")
        _wire(client, ids["read"], "raster", ids["width"], "raster")
        _wire(client, ids["read"], "raster", ids["layer"], "data")
        _wire(client, ids["cmap"], "value", ids["layer"], "colormap")
        _wire(client, ids["layer"], "layer", ids["panel"], "data")
        _wire(client, ids["layer"], "layer", ids["viewer"], "layers")
        yield client, ids


def _run(client: TestClient) -> list[dict[str, Any]]:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert client.post("/api/run", json={}).status_code == 202
        events = collect_until_finished(ws)
    assert events[-1]["report"]["ok"], events[-1]
    return events


def test_map_layer_is_done_without_a_worker_run(setup: tuple[TestClient, dict[str, str]]) -> None:
    client, ids = setup
    g = _graph(client)
    layer = g["nodes"][ids["layer"]]
    assert layer["state"] == "never_run" and layer["style"] == {}
    # The layer is known from the graph (Read Raster gives a Raster) before any run.
    assert layer["layer"]["value"]["kind"] == "raster" and layer["layer"]["issues"] == {}
    assert g["out_of_date"] == 5  # not the Map Layer, not the Map Viewer
    assert client.get(f"/api/nodes/{ids['layer']}/output").json()["outputs"] == {}

    plan = client.post("/api/run", json={}).json()["plan"]
    client.app.state.session.wait(120)  # type: ignore[attr-defined]
    assert ids["layer"] not in plan and ids["viewer"] not in plan
    g = _graph(client)
    assert {n: v["state"] for n, v in g["nodes"].items()} == dict.fromkeys(g["nodes"], "done")
    assert g["out_of_date"] == 0
    view = g["nodes"][ids["layer"]]["layer"]
    raster_key = client.get(f"/api/nodes/{ids['read']}/output").json()["keys"]["raster"]
    assert view["value"]["source"] == raster_key and view["value"]["kind"] == "raster"
    assert view["key"].endswith(".layer") and view["wired"] == {"colormap": "params"}
    out = client.get(f"/api/nodes/{ids['layer']}/output").json()
    assert out["state"] == "done" and out["keys"] == {"layer": view["key"]}


def test_no_started_event_for_view_nodes(setup: tuple[TestClient, dict[str, str]]) -> None:
    client, ids = setup
    events = _run(client)
    started = {e["node"] for e in events if e["type"] == "started"}
    assert ids["layer"] not in started and ids["viewer"] not in started
    assert ids["read"] in started
    report = events[-1]["report"]
    assert ids["layer"] not in report["ran"] + report["cached"]


def test_colormap_change_restyles_without_out_of_date(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    _run(client)
    before = _graph(client)["nodes"][ids["layer"]]["layer"]["key"]
    magma = types.Colormap.named("magma").to_json()
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        _patch(client, ids["cmap"], value=magma)
        events = _until_states(ws)
    changed = [e for e in events if e["type"] == "map_changed"]
    assert changed == [{"type": "map_changed", "node": ids["layer"], "viewers": [ids["viewer"]]}]
    states = events[-1]["states"]
    assert {n for n, s in states.items() if s != "done"} == {ids["cmap"]}
    assert events[-1]["out_of_date"] == 1
    g = _graph(client)
    assert g["nodes"][ids["width"]]["state"] == "done"  # Read Raster's downstream component
    after = g["nodes"][ids["layer"]]["layer"]
    assert after["key"] != before and after["value"]["colormap"] == magma


def test_style_patch_is_merged_checked_and_one_undo_step(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    _run(client)
    before = _graph(client)["nodes"][ids["layer"]]["layer"]["key"]
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        view = _patch(client, ids["layer"], style={"opacity": 0.5, "name": "Predictors"})
        events = _until_states(ws)
    assert view["style"] == {"opacity": 0.5, "name": "Predictors"}
    assert any(e["type"] == "map_changed" and e["node"] == ids["layer"] for e in events)
    assert events[-1]["out_of_date"] == 0
    g = _graph(client)
    assert g["nodes"][ids["layer"]]["layer"]["key"] != before
    assert g["nodes"][ids["layer"]]["layer"]["value"]["name"] == "Predictors"
    assert g["dirty"] and g["can_undo"]

    view = _patch(client, ids["layer"], style={"opacity": None, "color": "#abcdef"})
    assert view["style"] == {"name": "Predictors", "color": "#ABCDEF"}
    assert client.post("/api/undo").status_code == 200
    assert _graph(client)["nodes"][ids["layer"]]["style"] == {"opacity": 0.5, "name": "Predictors"}
    assert _patch(client, ids["layer"], style=None)["style"] == {}

    r = client.patch(f"/api/nodes/{ids['layer']}", json={"style": {"opacity": 4}})
    assert r.status_code == 400 and "opacity" in r.json()["detail"]
    r = client.patch(f"/api/nodes/{ids['layer']}", json={"style": {"size": 1}})
    assert r.status_code == 400 and "unknown style field" in r.json()["detail"]
    r = client.patch(f"/api/nodes/{ids['read']}", json={"style": {"opacity": 1}})
    assert r.status_code == 400 and "not a Map Layer" in r.json()["detail"]


def test_panel_on_the_layer_shows_name_source_and_style(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    _patch(client, ids["layer"], style={"name": "Predictors", "bands": "1"})
    _run(client)
    out = client.get(f"/api/nodes/{ids['panel']}/output").json()
    text = out["outputs"]["data"]
    assert text.startswith("Layer · Predictors · raster\nsource ")
    assert "colormap continuous · viridis" in text and "bands 1" in text
    assert out["views"]["data"] == {"kind": "summary", "type": "Layer", "text": text}


def test_layer_info_gives_band_names_and_vector_columns(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    info = client.get(f"/api/layer/{ids['layer']}").json()
    assert info["state"] == "never_run" and info["bands"] is None and info["columns"] is None
    _run(client)
    info = client.get(f"/api/layer/{ids['layer']}").json()
    assert info["node"] == ids["layer"] and info["state"] == "done"
    assert info["bands"] and len(info["bands"]) >= 3 and info["columns"] is None

    path = _add(client, "param/text")
    read = _add(client, "builtin/vector/read_vector")
    vlayer = _add(client, "param/layer")
    _patch(client, path, value="reference.gpkg")
    _wire(client, path, "value", read, "path")
    _wire(client, read, "vector", vlayer, "data")
    _patch(client, vlayer, style={"field": "imd_ref"})
    _run(client)
    info = client.get(f"/api/layer/{vlayer}").json()
    assert "imd_ref" in info["columns"] and info["bands"] is None
    assert info["value"]["kind"] == "vector" and info["value"]["field"] == "imd_ref"
    assert client.get(f"/api/layer/{read}").status_code == 400


def test_colormap_from_a_component_comes_from_the_disk_cache(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    maker = _add(client, "inline", source=MAKE_CLASSES)
    r = client.request(
        "DELETE",
        "/api/wires",
        json={"from": [ids["cmap"], "value"], "to": [ids["layer"], "colormap"]},
    )
    assert r.status_code == 204, r.text
    _wire(client, maker, "cmap", ids["layer"], "colormap")
    view = _graph(client)["nodes"][ids["layer"]]["layer"]
    assert "Make Classes has no result yet" in view["issues"]["colormap"]
    _run(client)
    view = _graph(client)["nodes"][ids["layer"]]["layer"]
    assert view["issues"] == {} and view["wired"] == {"colormap": "component"}
    assert view["value"]["colormap"]["kind"] == "classes"
    panel = client.get(f"/api/nodes/{ids['panel']}/output").json()["outputs"]["data"]
    assert "classes" in panel


def test_display_tab_lists_map_layer_and_map_viewer(client: TestClient) -> None:
    lib = client.get("/api/components").json()
    display = next(t for t in lib["tabs"] if t["name"] == "Display")
    assert display == {"name": "Display", "colour": "#A21CAF", "groups": ["Style", "Map"]}
    entries = {c["ref"]: c for c in lib["components"]}
    assert (entries["param/layer"]["category"], entries["param/layer"]["group"]) == (
        "Display",
        "Style",
    )
    assert (entries["param/map"]["category"], entries["param/map"]["group"]) == ("Display", "Map")
    assert [p["name"] for p in entries["param/layer"]["inputs"]] == [
        "data", "colormap", "color", "opacity", "bands", "name",
    ]  # fmt: skip
    assert entries["param/layer"]["outputs"][0]["type"] == "Layer"
