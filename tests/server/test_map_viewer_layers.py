"""Map Viewer with Layers and lists (change 03, sections 4 and 6; PLAN step 4).

- ``GET /api/map/{id}``: a wire from a Map Layer (also through a Panel) draws the
  layer's ``source``, with ``from_layer`` and the fields it sets ``locked``
  (their values win over ``map.styles``; show/hide stays the viewer's).
- A list wire gives one layer per element, ``<id>.<port>[i]``, whose key
  ``<port key>[i]`` the tile, GeoJSON and inspect routes answer.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from geoknit.server import tiles
from tests.server.conftest import make_client

LISTS = (
    "# geoknit: component\n# name: Make Lists\n# category: Test\n"
    "# inputs:\n#   raster: Raster\n#   vector: Vector\n"
    "# outputs:\n#   rasters: {type: Raster, access: list}\n"
    "#   vectors: {type: Vector, access: list}\n# --- code ---\n"
    "rasters = [raster, raster.isel(band=[0])]\n"
    "vectors = [vector, vector.head(5)]\n"
)
CLASSES = {
    "kind": "classes",
    "classes": [[1, "#FF0000", "Low"], [2, "#0000FF", ""]],
    "other": None,
}


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


def _layers(client: TestClient, viewer: str) -> list[dict[str, Any]]:
    r = client.get(f"/api/map/{viewer}")
    assert r.status_code == 200, r.text
    return r.json()["layers"]


@pytest.fixture(scope="module")
def setup(
    tmp_path_factory: pytest.TempPathFactory, synthetic_data: dict[str, Path]
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    """Read Raster (imd.tif) → Map Layer (classes Colormap) and Read Vector (reference)
    → Map Layer (colour, colormap by ``imd_ref``), both into a viewer with the raw
    vector between them; a list component into a second viewer. Run once."""
    root = tmp_path_factory.mktemp("map_layers")
    project = root / "project"
    project.mkdir()
    for name in ("imd", "reference"):
        shutil.copy(synthetic_data[name], project / synthetic_data[name].name)
    with make_client(project, root / "home" / "trusted.json") as client:
        ids = {
            "rpath": _add(client, "param/text"),
            "vpath": _add(client, "param/text"),
            "raster": _add(client, "builtin/raster/read_raster"),
            "vector": _add(client, "builtin/vector/read_vector"),
            "cmap": _add(client, "param/colormap"),
            "rlayer": _add(client, "param/layer"),
            "vlayer": _add(client, "param/layer"),
            "panel": _add(client, "param/panel"),
            "viewer": _add(client, "param/map"),
            "lists": _add(client, "inline", source=LISTS),
            "lviewer": _add(client, "param/map"),
        }
        _patch(client, ids["rpath"], value="imd.tif")
        _patch(client, ids["vpath"], value="reference.gpkg")
        _patch(client, ids["cmap"], value=CLASSES)
        _wire(client, ids["rpath"], "value", ids["raster"], "path")
        _wire(client, ids["vpath"], "value", ids["vector"], "path")
        _wire(client, ids["raster"], "raster", ids["rlayer"], "data")
        _wire(client, ids["cmap"], "value", ids["rlayer"], "colormap")
        _patch(client, ids["rlayer"], style={"opacity": 0.5, "name": "IMD classes"})
        _wire(client, ids["vector"], "vector", ids["vlayer"], "data")
        _patch(
            client,
            ids["vlayer"],
            style={"color": "#00ff00", "colormap": "viridis", "field": "imd_ref"},
        )
        _wire(client, ids["rlayer"], "layer", ids["viewer"], "layers")
        _wire(client, ids["vector"], "vector", ids["viewer"], "layers")
        _wire(client, ids["vlayer"], "layer", ids["panel"], "data")
        _wire(client, ids["panel"], "data", ids["viewer"], "layers")
        _wire(client, ids["raster"], "raster", ids["lists"], "raster")
        _wire(client, ids["vector"], "vector", ids["lists"], "vector")
        _wire(client, ids["lists"], "rasters", ids["lviewer"], "layers")
        _wire(client, ids["lists"], "vectors", ids["lviewer"], "layers")
        assert client.post("/api/run", json={}).status_code == 202
        client.app.state.session.wait(120)  # type: ignore[attr-defined]
        states = {n: v["state"] for n, v in client.get("/api/graph").json()["nodes"].items()}
        assert set(states.values()) == {"done"}, states
        yield client, ids


def test_layer_wires_draw_the_source_with_locked_fields(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    layers = _layers(client, ids["viewer"])
    # wire order; ids are the wire's source port as before
    assert [layer["id"] for layer in layers] == [
        f"{ids['rlayer']}.layer",
        f"{ids['vector']}.vector",
        f"{ids['panel']}.data",
    ]
    assert [layer["status"] for layer in layers] == ["ready"] * 3
    raster, raw, vector = layers
    source = client.get(f"/api/nodes/{ids['raster']}/output").json()["keys"]["raster"]
    assert raster["key"] == source and raster["type"] == "Raster"
    assert raster["from_layer"] == ids["rlayer"] and raster["title"] == "IMD classes"
    assert raster["locked"] == ["colormap", "opacity"]
    assert raster["style"]["colormap"] == CLASSES and raster["style"]["opacity"] == 0.5
    assert raster["style"]["visible"] is True

    assert raw["from_layer"] is None and raw["locked"] == []
    assert raw["style"]["color"] == "#d62728"

    # through the Panel: still the Map Layer's layer; colour by field with its range
    assert vector["from_layer"] == ids["vlayer"] and vector["type"] == "Vector"
    assert vector["locked"] == ["color", "colormap", "field"]
    assert vector["style"]["color"] == "#00FF00" and vector["style"]["field"] == "imd_ref"
    assert vector["style"]["colormap"] == {
        "kind": "continuous",
        "name": "viridis",
        "min": None,
        "max": None,
        "reverse": False,
    }
    field = vector["vector"]["field"]
    assert field["name"] == "imd_ref" and field["numeric"] is True
    assert 0 <= field["min"] < field["max"] <= 100
    assert "opacity" not in vector["locked"]  # not set in that Map Layer: the viewer's


def test_locked_fields_win_over_saved_styles_and_visibility_stays_editable(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    lid = f"{ids['rlayer']}.layer"
    _patch(
        client,
        ids["viewer"],
        map={"styles": {lid: {"colormap": "magma", "opacity": 0.9, "visible": False}}},
    )
    try:
        raster = _layers(client, ids["viewer"])[0]
        assert raster["style"]["colormap"] == CLASSES and raster["style"]["opacity"] == 0.5
        assert raster["style"]["visible"] is False
        # unlocked fields keep the viewer's saved value
        vid = f"{ids['panel']}.data"
        _patch(client, ids["viewer"], map={"styles": {vid: {"opacity": 0.3}}})
        assert _layers(client, ids["viewer"])[2]["style"]["opacity"] == 0.3
    finally:
        _patch(client, ids["viewer"], map={"styles": {lid: None, f"{ids['panel']}.data": None}})


def test_a_colormap_change_restyles_the_map_without_a_run(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    changed = {**CLASSES, "classes": [[1, "#00FF00", "Low"], [2, "#0000FF", ""]]}
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        _patch(client, ids["cmap"], value=changed)
        events = []
        while True:
            msg = ws.receive_json()
            events.append(msg)
            if msg["type"] == "states":
                break
    try:
        kinds = [e["type"] for e in events]
        assert "started" not in kinds
        found = next(e for e in events if e["type"] == "map_changed")
        assert found["node"] == ids["rlayer"] and found["viewers"] == [ids["viewer"]]
        raster = _layers(client, ids["viewer"])[0]
        assert raster["status"] == "ready" and raster["style"]["colormap"] == changed
    finally:
        _patch(client, ids["cmap"], value=CLASSES)


def test_a_list_wire_gives_one_layer_per_element(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    layers = _layers(client, ids["lviewer"])
    lists = ids["lists"]
    assert [layer["id"] for layer in layers] == [
        f"{lists}.rasters[0]",
        f"{lists}.rasters[1]",
        f"{lists}.vectors[0]",
        f"{lists}.vectors[1]",
    ]
    assert [layer["status"] for layer in layers] == ["ready"] * 4
    assert [layer["type"] for layer in layers] == ["Raster", "Raster", "Vector", "Vector"]
    keys = client.get(f"/api/nodes/{lists}/output").json()["keys"]
    assert [layer["key"] for layer in layers] == [
        f"{keys['rasters']}[0]",
        f"{keys['rasters']}[1]",
        f"{keys['vectors']}[0]",
        f"{keys['vectors']}[1]",
    ]
    assert layers[0]["title"].endswith("rasters [0]")
    assert layers[2]["vector"]["features"] == 150 and layers[3]["vector"]["features"] == 5

    # the routes answer element keys
    west, south, east, north = layers[0]["raster"]["bounds"]
    lon, lat = (west + east) / 2, (south + north) / 2
    import morecantile

    t = morecantile.tms.get("WebMercatorQuad").tile(lon, lat, 12)
    r = client.get(f"/tiles/{layers[1]['key']}/{t.z}/{t.x}/{t.y}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    r = client.get(f"/api/vector/{layers[3]['key']}.geojson")
    assert r.status_code == 200 and r.headers["x-geoknit-features"] == "5"
    found = client.get(f"/api/map/{ids['lviewer']}/inspect?lon={lon}&lat={lat}").json()
    assert [layer["id"] for layer in found["layers"]] == [
        f"{lists}.rasters[0]",
        f"{lists}.rasters[1]",
    ]
    # the whole list, an element out of range, and an element of no list are 404
    for key in (keys["rasters"], f"{keys['rasters']}[2]", f"{keys['rasters']}[x]"):
        assert client.get(f"/tiles/{key}/{t.z}/{t.x}/{t.y}.png").status_code == 404, key
    assert client.get(f"/api/vector/{keys['vectors']}[7].geojson").status_code == 404
    raster_key = client.get(f"/api/nodes/{ids['raster']}/output").json()["keys"]["raster"]
    assert client.get(f"/tiles/{raster_key}[0]/{t.z}/{t.x}/{t.y}.png").status_code == 404


def test_the_key_pattern_takes_a_list_index() -> None:
    key = "a" * 64 + ".raster"
    assert tiles.check_key(key) == key
    assert tiles.check_key(key + "[0]") == key + "[0]"
    assert tiles.check_key(key + "[12]") == key + "[12]"
    for bad in (key + "[]", key + "[-1]", key + "[1][2]", key + "[a]", "a" * 63 + ".raster"):
        with pytest.raises(tiles.MapError):
            tiles.check_key(bad)


def test_a_panel_still_connects_and_other_values_are_refused(
    setup: tuple[TestClient, dict[str, str]],
) -> None:
    client, ids = setup
    panel = _add(client, "param/panel")
    viewer = _add(client, "param/map")
    try:
        _wire(client, panel, "data", viewer, "layers")  # unwired Panel: Any
        r = client.post(
            "/api/wires", json={"from": [ids["rpath"], "value"], "to": [viewer, "layers"]}
        )
        assert r.status_code == 400
        assert re.search(r"Text can't connect to Raster \| Vector \| Layer", r.json()["detail"])
        _wire(client, ids["cmap"], "value", panel, "data")  # the Panel now gives a Colormap
        wires = client.get("/api/graph").json()["workflow"]["wires"]
        assert not any(w["to"][0] == viewer for w in wires)
    finally:
        client.post("/api/delete", json={"nodes": [panel, viewer], "wires": []})
