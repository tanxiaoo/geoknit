"""REST behaviour: refusals, run / stop, trust, files, OpenAPI page."""

import shutil
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from geoknit.server.files import file_tree
from tests.conftest import SYNTHETIC
from tests.server.conftest import collect_until_finished, make_client

UPPER = """\
# geoknit: component
# name: Upper
# category: Text
# inputs:
#   text: Text
# outputs:
#   upper: Text

# --- code ---
print(f"upper-casing {text}")
upper = text.upper()
"""

SLEEPY = """\
# geoknit: component
# name: Sleepy
# category: Script
# outputs:
#   y: Number

# --- code ---
import time
print("going to sleep")
time.sleep(60)
y = 1
"""

QUICK = SLEEPY.replace("time.sleep(60)", "pass")


def _add(client: TestClient, component: str, **extra: object) -> str:
    r = client.post("/api/nodes", json={"component": component, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wire(client: TestClient, src: str, sp: str, dst: str, dp: str) -> object:
    return client.post("/api/wires", json={"from": [src, sp], "to": [dst, dp]})


def test_docs_page_and_schema(client: TestClient) -> None:
    r = client.get("/docs")
    assert r.status_code == 200 and "swagger" in r.text.lower()
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/components", "/api/graph", "/api/nodes", "/api/nodes/{node_id}",
        "/api/wires", "/api/run", "/api/stop", "/api/nodes/{node_id}/output",
        "/api/files", "/api/workflow/save", "/api/workflow/open", "/api/workflow/trust",
        "/api/export/py", "/api/cache/clear",
    ):  # fmt: skip
        assert path in paths, path
    assert client.get("/").status_code == 200


def test_components_list_the_library(client: TestClient) -> None:
    body = client.get("/api/components").json()
    comps = {c["ref"]: c for c in body["components"]}
    rec = comps["builtin/raster/reclassify"]
    assert rec["category"] == "Raster" and rec["group"] == "Calculate"
    assert comps["param/slider"]["category"] == "Params"
    assert comps["param/slider"]["group"] == "Input"
    raster = next(t for t in body["tabs"] if t["name"] == "Raster")
    assert raster["colour"] == "#0B7A7C" and raster["groups"][0] == "Files"
    assert {s["name"] for s in rec["settings"]} == {"no_match", "dtype"}
    assert next(s for s in rec["settings"] if s["name"] == "dtype")["widget"] == "dropdown"


def test_refused_edits_have_clear_messages(client: TestClient) -> None:
    raster = _add(client, "builtin/raster/read_raster")
    rf = _add(client, "builtin/model/random_forest")
    r = _wire(client, raster, "raster", rf, "n_trees")
    assert r.status_code == 400
    assert r.json()["detail"] == "Raster can't connect to Number"

    a = _add(client, "inline", source=UPPER)
    b = _add(client, "inline", source=UPPER)
    assert _wire(client, a, "upper", b, "text").status_code == 201
    r = _wire(client, b, "upper", a, "text")
    assert r.status_code == 400 and "cycle" in r.json()["detail"]

    assert client.patch("/api/nodes/nope", json={"position": [1, 2]}).status_code == 404
    assert client.delete("/api/nodes/nope").status_code == 404
    assert client.get("/api/nodes/nope/output").status_code == 404
    r = client.patch(f"/api/nodes/{rf}", json={"settings": {"nope": 1}})
    assert r.status_code == 400
    r = client.post("/api/nodes", json={"component": "builtin/raster/nope"})
    assert r.status_code == 400 and "unknown component" in r.json()["detail"]
    r = client.post("/api/export/py")
    assert r.status_code == 400
    assert 'Read Raster: input "path" is not connected' in r.json()["detail"]


def test_edit_run_output_and_out_of_date(client: TestClient) -> None:
    text = _add(client, "param/text")
    up = _add(client, "inline", source=UPPER)
    panel = _add(client, "param/panel")
    assert client.patch(f"/api/nodes/{text}", json={"value": "hello"}).json()["value"] == "hello"
    _wire(client, text, "value", up, "text")
    _wire(client, up, "upper", panel, "data")

    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert client.post("/api/run", json={}).status_code == 202
        events = collect_until_finished(ws)
    assert events[-1]["report"]["ok"]
    out = client.get(f"/api/nodes/{up}/output").json()
    assert out["state"] == "done" and out["log"] == ["upper-casing hello"]
    assert out["outputs"]["upper"] == "HELLO"
    assert client.get(f"/api/nodes/{panel}/output").json()["outputs"]["data"] == "HELLO"

    # A position change keeps results; a value change marks it and downstream.
    client.patch(f"/api/nodes/{text}", json={"position": [5, 5]})
    assert client.get("/api/graph").json()["out_of_date"] == 0
    client.patch(f"/api/nodes/{text}", json={"value": "bye"})
    states = {n: v["state"] for n, v in client.get("/api/graph").json()["nodes"].items()}
    assert states == {text: "out_of_date", up: "out_of_date", panel: "out_of_date"}

    # Slider limits and value.
    s = _add(client, "param/slider")
    v = client.patch(f"/api/nodes/{s}", json={"min": 0, "max": 10, "step": 1, "value": 7}).json()
    assert (v["min"], v["max"], v["value"]) == (0, 10, 7)
    assert client.patch(f"/api/nodes/{s}", json={"value": 3}).json()["value"] == 3

    r = client.request("DELETE", "/api/wires", json={"from": [up, "upper"], "to": [panel, "data"]})
    assert r.status_code == 204
    assert client.delete(f"/api/nodes/{panel}").status_code == 204
    assert panel not in client.get("/api/graph").json()["nodes"]


def test_stop_a_sleeping_node_then_run_again(client: TestClient) -> None:
    sleepy = _add(client, "inline", source=SLEEPY)
    text = _add(client, "param/text")
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert client.post("/api/run", json={"mode": "all"}).status_code == 202
        while True:  # wait until the component is really running
            msg = ws.receive_json()
            if msg["type"] == "log" and msg["node"] == sleepy:
                break
        assert client.post("/api/run", json={}).status_code == 409
        assert client.patch(f"/api/nodes/{text}", json={"value": "x"}).status_code == 409
        assert client.patch(f"/api/nodes/{text}", json={"position": [1, 1]}).status_code == 200
        assert client.post("/api/stop").status_code == 200
        collect_until_finished(ws)
    assert client.get(f"/api/nodes/{sleepy}/output").json()["error"] == "stopped"

    client.patch(f"/api/nodes/{sleepy}", json={"source": QUICK})
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        client.post("/api/run", json={})
        events = collect_until_finished(ws)
    assert events[-1]["report"]["ok"], events[-1]
    assert client.get(f"/api/nodes/{sleepy}/output").json()["outputs"]["y"] == "1"


def test_untrusted_workflow_opens_read_only(
    client: TestClient, project: Path, trust_file: Path
) -> None:
    shutil.copy(SYNTHETIC / "imd.geoknit", project / "imd.geoknit")
    view = client.post("/api/workflow/open", json={"path": "imd.geoknit"}).json()
    assert view["trusted"] is False and view["nodes"]
    nid = next(iter(view["nodes"]))
    r = client.patch(f"/api/nodes/{nid}", json={"position": [1, 1]})
    assert r.status_code == 403
    assert r.json()["detail"] == "This workflow contains Python code. Trust and allow running?"
    assert client.post("/api/run", json={}).status_code == 403
    assert client.get("/api/graph").json()["trusted"] is False

    assert client.post("/api/workflow/trust").json() == {"trusted": True}
    assert client.patch(f"/api/nodes/{nid}", json={"position": [1, 1]}).status_code == 200
    assert trust_file.is_file()

    # Trusted from now on, also in a new server.
    with make_client(project, trust_file) as other:
        assert other.post("/api/workflow/open", json={"path": "imd.geoknit"}).json()["trusted"]

    # A changed file is a different workflow: untrusted again.
    path = project / "imd.geoknit"
    path.write_text(
        path.read_text(encoding="utf-8").replace("data/imd.tif", "x.tif"), encoding="utf-8"
    )
    assert (
        client.post("/api/workflow/open", json={"path": "imd.geoknit"}).json()["trusted"] is False
    )


def test_workflow_paths_stay_inside_the_project(client: TestClient, tmp_path: Path) -> None:
    assert client.post("/api/workflow/save", json={}).status_code == 400  # new: needs a path
    r = client.post("/api/workflow/save", json={"path": "../outside.geoknit"})
    assert r.status_code == 400 and "outside the project" in r.json()["detail"]
    assert client.post("/api/workflow/save", json={"path": "a.txt"}).status_code == 400
    assert client.post("/api/workflow/open", json={"path": "missing.geoknit"}).status_code == 400
    assert not (tmp_path / "outside.geoknit").exists()


def test_export_py_returns_and_writes_the_script(client: TestClient, project: Path) -> None:
    text = _add(client, "param/text")
    client.patch(f"/api/nodes/{text}", json={"value": "hi"})
    up = _add(client, "inline", source=UPPER)
    _wire(client, text, "value", up, "text")

    r = client.post("/api/export/py", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["path"] is None and body["warnings"] == []
    assert "def n02_upper(text):" in body["script"]
    assert not list(project.glob("*.py"))

    r = client.post("/api/export/py", json={"path": "wf.py"})
    assert r.status_code == 200 and r.json()["path"] == "wf.py"
    assert (project / "wf.py").read_text(encoding="utf-8") == body["script"]
    r = client.post("/api/export/py", json={"path": "wf.py"})
    assert r.status_code == 409 and "already exists" in r.json()["detail"]
    assert client.post("/api/export/py", json={"path": "wf.py", "overwrite": True}).is_success

    r = client.post("/api/export/py", json={"path": "scripts/wf.py"})
    assert "not next to the workflow" in r.json()["warnings"][0]
    r = client.post("/api/export/py", json={"path": "../outside.py"})
    assert r.status_code == 400 and "outside the project" in r.json()["detail"]
    assert client.post("/api/export/py", json={"path": "wf.txt"}).status_code == 400


def test_files_tree_hides_the_geoknit_folder(client: TestClient, project: Path) -> None:
    (project / ".geoknit" / "cache").mkdir(parents=True)
    (project / "data" / "sub").mkdir(parents=True)
    (project / "data" / "b.tif").write_bytes(b"")
    (project / "data" / "A.gpkg").write_bytes(b"")
    (project / "data" / "sub" / "c.csv").write_bytes(b"")
    (project / "wf.geoknit").write_text("{}", encoding="utf-8")

    tree = client.get("/api/files").json()
    assert tree == file_tree(project)
    assert [c["name"] for c in tree["children"]] == ["data", "wf.geoknit"]
    data = tree["children"][0]
    assert [c["path"] for c in data["children"]] == ["data/sub", "data/A.gpkg", "data/b.tif"]
    assert data["children"][0]["children"][0] == {
        "name": "c.csv", "path": "data/sub/c.csv", "kind": "file",
    }  # fmt: skip


def test_server_does_not_import_the_geo_stack() -> None:
    code = (
        "import sys, geoknit.server.app; "
        "print([m for m in ('rasterio', 'geopandas', 'sklearn', 'xarray') if m in sys.modules])"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.stdout.strip() == "[]", result.stderr


SELECT_ROWS = """\
# geoknit: component
# name: Select
# category: Table
# inputs:
#   data: [Table, Vector]
# outputs:
#   selected: {like: data}

# --- code ---
selected = data
"""


def test_ports_carry_types_like_and_resolved_type(client: TestClient) -> None:
    comps = {c["ref"]: c for c in client.get("/api/components").json()["components"]}
    split = comps["builtin/sampling/split_points"]
    assert all("types" in p for p in split["inputs"] + split["outputs"])
    assert all("like" in p for p in split["outputs"])

    sel = _add(client, "inline", source=SELECT_ROWS)
    panel = _add(client, "param/panel")
    graph = client.get("/api/graph").json()
    (data,) = graph["nodes"][sel]["inputs"]
    assert data["type"] == "Table" and data["types"] == ["Table", "Vector"]
    (out,) = graph["nodes"][sel]["outputs"]
    assert out["like"] == "data" and out["resolved_type"] is None
    assert graph["nodes"][panel]["outputs"][0]["resolved_type"] is None

    text = _add(client, "param/text")
    r = _wire(client, text, "value", sel, "data")
    assert r.status_code == 400 and r.json()["detail"] == "Text can't connect to Table | Vector"
    assert _wire(client, sel, "selected", panel, "data").status_code == 201
    graph = client.get("/api/graph").json()
    through = graph["nodes"][panel]["outputs"][0]
    assert through["resolved_type"] is None  # sel unresolved
    # ... but the server knows what it can be; the frontend checks drags against that
    assert through["types"] == ["Any"] and through["resolved_types"] == ["Table", "Vector"]
    assert graph["nodes"][sel]["outputs"][0]["resolved_types"] == ["Table", "Vector"]
    read = _add(client, "builtin/raster/clip")
    r = _wire(client, panel, "data", read, "raster")
    assert r.status_code == 400 and r.json()["detail"] == "Table | Vector can't connect to Raster"
    up = _add(client, "inline", source=UPPER)
    assert _wire(client, text, "value", up, "text").status_code == 201
    graph = client.get("/api/graph").json()
    assert graph["nodes"][up]["outputs"][0]["resolved_type"] == "Text"  # a plain output


NUMBERS = """\
# geoknit: component
# name: Numbers
# category: Test
# outputs:
#   values: {type: Number, access: list}

# --- code ---
values = [3, 1, 2]
"""


def test_outputs_say_whether_they_carry_a_list(client: TestClient) -> None:
    comps = {c["ref"]: c for c in client.get("/api/components").json()["components"]}
    assert all(p["access"] == "item" for p in comps["builtin/raster/reclassify"]["outputs"])

    nums = _add(client, "inline", source=NUMBERS)
    panel = _add(client, "param/panel")
    up = _add(client, "inline", source=UPPER)
    r = _wire(client, nums, "values", up, "text")
    assert r.status_code == 400
    assert r.json()["detail"] == 'Numbers gives a list; "text" takes one value — use List Item'
    assert _wire(client, nums, "values", panel, "data").status_code == 201
    nodes = client.get("/api/graph").json()["nodes"]
    (out,) = nodes[nums]["outputs"]
    assert out["access"] == "list" and out["resolved_access"] == "list"
    (through,) = nodes[panel]["outputs"]
    assert through["access"] == "item" and through["resolved_access"] == "list"
    assert through["resolved_type"] == "Number"
    assert nodes[up]["outputs"][0]["resolved_access"] == "item"
