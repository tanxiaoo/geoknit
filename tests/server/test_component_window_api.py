"""API behind the component window (SPEC 4, 9): ports, Save as component, Open in VS Code."""

from pathlib import Path

from fastapi.testclient import TestClient

from geoknit.components.registry import default_registry
from geoknit.server.app import create_app
from geoknit.server.session import Session

PYTHON = "builtin/script/python"
RECLASSIFY = "builtin/raster/reclassify"


def _add(client: TestClient, component: str) -> str:
    r = client.post("/api/nodes", json={"component": component, "position": [0, 0]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _session(client: TestClient) -> Session:
    return client.app.state.session  # type: ignore[attr-defined,no-any-return]


def test_ports_patch_rewrites_the_header_and_keeps_wires(client: TestClient) -> None:
    t = _add(client, "param/text")
    py = _add(client, PYTHON)
    r = client.patch(
        f"/api/nodes/{py}",
        json={"ports": {"inputs": [{"name": "words", "type": "Text"}], "outputs": []}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["inputs"][0]["name"] == "words"
    assert "#   words: Text" in r.json()["source"]
    r = client.post("/api/wires", json={"from": [t, "value"], "to": [py, "words"]})
    assert r.status_code == 201, r.text

    r = client.patch(
        f"/api/nodes/{py}",
        json={
            "ports": {
                "inputs": [{"name": "text", "type": "Text", "was": "words"}],
                "outputs": [{"name": "out", "type": "Text"}],
            }
        },
    )
    assert r.status_code == 200, r.text
    wires = client.get("/api/graph").json()["workflow"]["wires"]
    assert wires == [{"from": [t, "value"], "to": [py, "text"]}]

    bad = client.patch(
        f"/api/nodes/{py}", json={"ports": {"inputs": [{"name": "x y", "type": "Text"}]}}
    )
    assert bad.status_code == 400 and "not a valid port name" in bad.json()["detail"]

    # one undo step per port change
    client.post("/api/undo")
    assert client.get("/api/graph").json()["nodes"][py]["inputs"][0]["name"] == "words"


def test_broken_settings_block_reports_a_parse_error(client: TestClient) -> None:
    rc = _add(client, RECLASSIFY)
    source = client.get("/api/graph").json()["nodes"][rc]["source"]
    broken = source.replace('no_match = "nodata"', "no_match = nodata")
    r = client.patch(f"/api/nodes/{rc}", json={"source": broken})
    assert r.status_code == 200
    assert "settings block" in r.json()["parse_error"]
    # the Settings tab is disabled: settings edits are refused until the code is fixed
    r = client.patch(f"/api/nodes/{rc}", json={"settings": {"dtype": "int16"}})
    assert r.status_code == 400 and "fix the code first" in r.json()["detail"]


def test_save_as_component_appears_in_the_library(tmp_path: Path, trust_file: Path) -> None:
    user = tmp_path / "user-components"
    project = tmp_path / "p"
    project.mkdir()
    app = create_app(project, registry=default_registry(user, packs=False), trust_file=trust_file)
    with TestClient(app) as client:
        py = _add(client, PYTHON)
        source = client.get("/api/graph").json()["nodes"][py]["source"]
        source = source.replace("# name: Python", "# name: My NDVI!")
        client.patch(f"/api/nodes/{py}", json={"source": source})

        r = client.post(f"/api/nodes/{py}/save_component", json={})
        assert r.status_code == 200, r.text
        assert r.json()["ref"] == "user/script/my_ndvi"
        assert (user / "script" / "my_ndvi.py").read_text(encoding="utf-8") == source
        entry = next(
            c
            for c in client.get("/api/components").json()["components"]
            if c["ref"] == r.json()["ref"]
        )
        assert entry["origin"] == "user" and entry["name"] == "My NDVI!"

        again = client.post(f"/api/nodes/{py}/save_component", json={})
        assert again.status_code == 409
        r = client.post(f"/api/nodes/{py}/save_component", json={"overwrite": True})
        assert r.status_code == 200

        # the saved component can be placed like any other
        assert _add(client, "user/script/my_ndvi")

        t = _add(client, "param/text")
        assert client.post(f"/api/nodes/{t}/save_component", json={}).status_code == 400


def test_open_in_vscode_syncs_both_ways(client: TestClient) -> None:
    session = _session(client)
    launched: list[Path] = []
    session.editors.launch = launched.append
    session.editors.interval = 3600  # drive the sync by hand with poll()

    rc = _add(client, RECLASSIFY)
    r = client.post(f"/api/nodes/{rc}/vscode")
    assert r.status_code == 200, r.text
    path = Path(r.json()["path"])
    assert launched == [path] and path.name.endswith("_reclassify.py")
    source = client.get("/api/graph").json()["nodes"][rc]["source"]
    assert path.read_text(encoding="utf-8") == source

    # a save in the editor becomes the node's source, one undo step
    edited = source.replace("print(", "print('edited', ")
    path.write_text(edited, encoding="utf-8")
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # states on connect
        assert session.editors.poll() == [rc]
        events = [ws.receive_json() for _ in range(2)]
    assert {"type": "node_changed", "node": rc} in events
    node = client.get("/api/graph").json()["nodes"][rc]
    assert node["source"] == edited and node["modified"] is True

    # a change in GeoKnit (Settings tab) is written back to the file
    client.patch(f"/api/nodes/{rc}", json={"settings": {"dtype": "int16"}})
    assert session.editors.poll() == []
    assert 'dtype = "int16"' in path.read_text(encoding="utf-8")

    # a deleted node stops being watched
    client.delete(f"/api/nodes/{rc}")
    session.editors.poll()
    assert session.editors.watches == {}


def test_open_in_vscode_without_vscode_is_a_clear_error(
    client: TestClient, monkeypatch: object
) -> None:
    import geoknit.server.editor as editor

    monkeypatch.setattr(editor.shutil, "which", lambda name: None)  # type: ignore[attr-defined]
    rc = _add(client, RECLASSIFY)
    r = client.post(f"/api/nodes/{rc}/vscode")
    assert r.status_code == 400 and "VS Code was not found" in r.json()["detail"]


CALC = """\
# geoknit: component
# name: Raster Calculator
# category: Raster
# ports: {inputs: editable, types: [Raster, Number]}
# inputs:
#   a: Raster
# outputs:
#   result: Raster

# --- code ---
result = a
"""


def test_ports_patch_follows_the_ports_header_key(client: TestClient) -> None:
    r = client.post("/api/nodes", json={"component": "inline", "position": [0, 0], "source": CALC})
    assert r.status_code == 201, r.text
    calc = r.json()["id"]
    assert r.json()["editable_ports"] == {
        "inputs": True,
        "outputs": False,
        "types": ["Raster", "Number"],
        "input_types": ["Raster", "Number"],
    }
    a = {"name": "a", "type": "Raster"}
    r = client.patch(
        f"/api/nodes/{calc}", json={"ports": {"inputs": [a, {"name": "b", "type": "Raster"}]}}
    )
    assert r.status_code == 200, r.text
    assert [(p["name"], p["type"]) for p in r.json()["inputs"]] == [
        ("a", "Raster"),
        ("b", "Raster"),
    ]

    r = client.patch(
        f"/api/nodes/{calc}",
        json={"ports": {"inputs": [a, {"name": "b", "type": "Text", "was": "b"}]}},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Raster Calculator inputs are Raster or Number"
    assert client.get("/api/graph").json()["nodes"][calc]["inputs"][1]["type"] == "Raster"

    rc = _add(client, RECLASSIFY)
    assert client.get("/api/graph").json()["nodes"][rc]["editable_ports"] is None
    r = client.patch(
        f"/api/nodes/{rc}", json={"ports": {"inputs": [{"name": "raster", "type": "Raster"}]}}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "the inputs of Reclassify cannot be edited"


def test_components_list_says_which_ports_are_editable(client: TestClient) -> None:
    entries = {e["ref"]: e for e in client.get("/api/components").json()["components"]}
    python = entries[PYTHON]["editable_ports"]
    assert python["inputs"] and python["outputs"] and python["types"][0] == "Number"
    assert entries[RECLASSIFY]["editable_ports"] is None
