"""The Params nodes of change 01 (section 8) through the API, and a run in the worker."""

from fastapi.testclient import TestClient

from tests.server.conftest import collect_until_finished

CHECK = """\
# geoknit: component
# name: Check
# category: Script
# inputs:
#   flag: Boolean
#   n: Number
#   pick: Text
#   color: Color
#   ramp: Colormap
# outputs:
#   out: Text

# --- code ---
out = f"{flag} {n!r} {pick} {color.hex} {ramp.name}"
"""

HALF = """\
# geoknit: component
# name: Half
# category: Maths
# inputs:
#   x: Number
# outputs:
#   half: Number

# --- code ---
half = x / 2
"""


def _add(client: TestClient, component: str, **extra: object) -> dict:
    r = client.post("/api/nodes", json={"component": component, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _patch(client: TestClient, node: str, **body: object) -> dict:
    r = client.patch(f"/api/nodes/{node}", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _wire(client: TestClient, src: str, sp: str, dst: str, dp: str) -> int:
    return client.post("/api/wires", json={"from": [src, sp], "to": [dst, dp]}).status_code


def test_new_nodes_are_listed_and_viewed(client: TestClient) -> None:
    comps = {c["ref"]: c for c in client.get("/api/components").json()["components"]}
    for ref, group in [
        ("param/number", "Input"),
        ("param/toggle", "Input"),
        ("param/value_list", "Input"),
        ("param/color", "Style"),
        ("param/colormap", "Style"),
    ]:
        assert comps[ref]["group"] == group and comps[ref]["origin"] == "param"

    number = _add(client, "param/number")
    assert (number["value"], number["integer"]) == (0, False)
    assert number["outputs"][0]["type"] == "Number"
    assert _add(client, "param/slider")["integer"] is False
    toggle = _add(client, "param/toggle")
    assert toggle["value"] is False and toggle["outputs"][0]["resolved_type"] == "Boolean"
    vlist = _add(client, "param/value_list")
    assert vlist["options"] == [
        {"label": "One", "value": 1},
        {"label": "Two", "value": 2},
        {"label": "Three", "value": 3},
    ]
    assert vlist["value"] == 1 and vlist["outputs"][0]["type"] == "Number"
    assert _add(client, "param/color")["value"] == "#0B7A7C"
    assert _add(client, "param/colormap")["value"] == {
        "kind": "continuous", "name": "viridis", "min": None, "max": None, "reverse": False,
    }  # fmt: skip


def test_patch_values_integer_and_options(client: TestClient) -> None:
    number = _add(client, "param/number")["id"]
    assert _patch(client, number, value=2.5)["value"] == 2.5
    view = _patch(client, number, integer=True)
    assert view["value"] == 3 and view["integer"] is True
    slider = _add(client, "param/slider")["id"]
    view = _patch(client, slider, min=0.4, max=9.6, step=0.3, value=4.6, integer=True)
    assert [view[k] for k in ("min", "max", "step", "value", "integer")] == [0, 10, 1, 5, True]
    # a refused value leaves the integer mode (and the undo history) as it was
    other = _add(client, "param/number")["id"]
    _patch(client, other, value=2.5)
    undo_before = client.get("/api/graph").json()["can_undo"]
    r = client.patch(f"/api/nodes/{other}", json={"value": "abc", "integer": True})
    assert r.status_code == 400 and r.json()["detail"] == "a Number value must be a number"
    graph = client.get("/api/graph").json()
    after = graph["nodes"][other]
    assert (after["value"], after["integer"]) == (2.5, False)
    assert client.post("/api/undo").status_code == 200
    assert client.get("/api/graph").json()["nodes"][other]["value"] == 0  # undid the 2.5 patch
    assert undo_before is True
    text = _add(client, "param/text")["id"]
    r = client.patch(f"/api/nodes/{text}", json={"integer": True})
    assert r.status_code == 400 and r.json()["detail"] == "Text has no integer mode"
    r = client.patch(f"/api/nodes/{text}", json={"options": [{"label": "a", "value": 1}]})
    assert r.status_code == 400 and r.json()["detail"] == "Text has no options"

    toggle = _add(client, "param/toggle")["id"]
    assert _patch(client, toggle, value=True)["value"] is True
    assert client.patch(f"/api/nodes/{toggle}", json={"value": 1}).status_code == 400
    color = _add(client, "param/color")["id"]
    assert _patch(client, color, value="11,122,124")["value"] == "#0B7A7C"
    assert client.patch(f"/api/nodes/{color}", json={"value": "teal"}).status_code == 400
    ramp = _add(client, "param/colormap")["id"]
    view = _patch(client, ramp, value={"kind": "continuous", "name": "magma", "reverse": True})
    assert view["value"]["name"] == "magma" and view["value"]["reverse"] is True
    r = client.patch(f"/api/nodes/{ramp}", json={"value": {"kind": "nope"}})
    assert r.status_code == 400 and "not a colormap" in r.json()["detail"]

    vlist = _add(client, "param/value_list")["id"]
    view = _patch(
        client, vlist, options=[{"label": "a", "value": "x"}, {"label": "b", "value": 2}], value=2
    )
    assert view["value"] == 2 and view["outputs"][0]["type"] == "Text"
    r = client.patch(f"/api/nodes/{vlist}", json={"value": 7})
    assert r.status_code == 400 and "not one of the Value List's options" in r.json()["detail"]


def test_value_list_options_recheck_wires_and_undo(client: TestClient) -> None:
    vlist = _add(client, "param/value_list")["id"]
    half = _add(client, "inline", source=HALF)["id"]
    assert _wire(client, vlist, "value", half, "x") == 201
    _patch(client, vlist, options=[{"label": "1", "value": 1}, {"label": "a", "value": "a"}])
    graph = client.get("/api/graph").json()
    assert graph["workflow"]["wires"] == []
    assert graph["nodes"][vlist]["outputs"][0]["resolved_type"] == "Text"
    client.post("/api/undo")
    graph = client.get("/api/graph").json()
    assert len(graph["workflow"]["wires"]) == 1
    assert graph["nodes"][vlist]["outputs"][0]["type"] == "Number"


def test_toggle_runs_in_the_worker_and_undo_restores_it(client: TestClient) -> None:
    ids = {
        kind: _add(client, f"param/{kind}")["id"]
        for kind in ("toggle", "number", "value_list", "color", "colormap")
    }
    check = _add(client, "inline", source=CHECK)["id"]
    _patch(client, ids["toggle"], value=True)
    _patch(client, ids["number"], value=4, integer=True)
    _patch(client, ids["value_list"], options=[{"label": "a", "value": "x"}], value="x")
    for kind, port in [
        ("toggle", "flag"), ("number", "n"), ("value_list", "pick"),
        ("color", "color"), ("colormap", "ramp"),
    ]:  # fmt: skip
        assert _wire(client, ids[kind], "value", check, port) == 201

    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert client.post("/api/run", json={}).status_code == 202
        events = collect_until_finished(ws)
    assert events[-1]["report"]["ok"], events[-1]
    assert client.get(f"/api/nodes/{check}/output").json()["outputs"]["out"] == (
        "True 4 x #0B7A7C viridis"
    )
    out = client.get(f"/api/nodes/{ids['toggle']}/output").json()
    assert out["state"] == "done" and out["outputs"] == {"value": "True"}

    _patch(client, ids["toggle"], value=False)
    states = {n: v["state"] for n, v in client.get("/api/graph").json()["nodes"].items()}
    assert states[ids["toggle"]] == states[check] == "out_of_date"
    client.post("/api/undo")
    graph = client.get("/api/graph").json()
    assert graph["nodes"][ids["toggle"]]["value"] is True


def test_colormaps_lists_the_named_ramps(client: TestClient) -> None:
    from geoknit.core.types import NAMED_RAMPS, Colormap

    ramps = client.get("/api/colormaps").json()
    assert list(ramps) == list(NAMED_RAMPS)
    viridis = Colormap.named("viridis")
    assert ramps["viridis"] == [c.hex for _, c in viridis.stops]
    assert all(len(stops) == 11 for stops in ramps.values())


def test_colormap_editor_values_patch_save_and_reopen(client: TestClient) -> None:
    """The Colormap editor's values (change 03, section 2): classes with labels and
    ``other``, custom stops with fixed min/max; each patch is one undo step and the
    workflow file keeps them as they were sent."""
    ramp = _add(client, "param/colormap")["id"]
    classes = {
        "kind": "classes",
        "classes": [[1, "#ff0000", "Built"], [2, "#00FF00", "Green"], [3, "#0000FF80", ""]],
        "other": "#808080",
    }
    view = _patch(client, ramp, value=classes)
    assert view["value"] == {
        "kind": "classes",
        "classes": [[1, "#FF0000", "Built"], [2, "#00FF00", "Green"], [3, "#0000FF80", ""]],
        "other": "#808080",
    }
    custom = {
        "kind": "continuous",
        "name": None,
        "stops": [[0, "#000000"], [0.4, "#FF0000"], [1, "#FFFFFF"]],
        "min": 0,
        "max": 10.5,
        "reverse": False,
    }
    assert _patch(client, ramp, value=custom)["value"] == custom
    assert client.post("/api/undo").status_code == 200
    assert client.get("/api/graph").json()["nodes"][ramp]["value"]["kind"] == "classes"
    twice = {"kind": "classes", "classes": [[1, "#FF0000", ""], [1, "#00FF00", ""]]}
    r = client.patch(f"/api/nodes/{ramp}", json={"value": twice})
    assert r.status_code == 400 and "listed twice" in r.json()["detail"]

    assert client.post("/api/workflow/save", json={"path": "cm.geoknit"}).status_code == 200
    assert client.post("/api/workflow/open", json={"path": "cm.geoknit"}).status_code == 200
    assert client.get("/api/graph").json()["nodes"][ramp]["value"] == view["value"]
