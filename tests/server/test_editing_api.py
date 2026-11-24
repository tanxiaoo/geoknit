"""Undo / redo, batch edits, paste, groups, unsaved state and autosave (SPEC 8, 9)."""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.server.conftest import make_client


def _add(client: TestClient, component: str, position: list[float] | None = None) -> str:
    r = client.post("/api/nodes", json={"component": component, "position": position or [0, 0]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _graph(client: TestClient) -> dict:
    return client.get("/api/graph").json()


def _text_and_panel(client: TestClient) -> tuple[str, str]:
    t = _add(client, "param/text")
    p = _add(client, "param/panel", [200, 0])
    assert client.patch(f"/api/nodes/{t}", json={"value": "hello"}).status_code == 200
    r = client.post("/api/wires", json={"from": [t, "value"], "to": [p, "data"]})
    assert r.status_code == 201, r.text
    return t, p


def test_undo_and_redo_every_kind_of_edit(client: TestClient) -> None:
    assert _graph(client)["can_undo"] is False
    t, p = _text_and_panel(client)
    docs = []
    g = _graph(client)
    assert g["can_undo"] and not g["can_redo"] and g["dirty"]
    docs.append(g["workflow"])

    client.patch(f"/api/nodes/{t}", json={"value": "changed", "position": [5, 6]})
    client.request("DELETE", "/api/wires", json={"from": [t, "value"], "to": [p, "data"]})
    after = _graph(client)["workflow"]
    assert after["wires"] == []

    client.post("/api/undo")  # the wire comes back
    client.post("/api/undo")  # value and position come back
    g = _graph(client)
    assert g["workflow"] == docs[0] and g["can_redo"]
    assert client.post("/api/redo").status_code == 200
    r = client.post("/api/redo")
    assert r.json()["workflow"] == after and not r.json()["can_redo"]

    # a new edit clears what could be redone
    client.post("/api/undo")
    _add(client, "param/slider")
    assert not _graph(client)["can_redo"]


def test_undo_with_nothing_to_undo_is_harmless(client: TestClient) -> None:
    assert client.post("/api/undo").status_code == 200
    assert client.post("/api/redo").status_code == 200


def test_view_changes_are_not_undone(client: TestClient) -> None:
    _add(client, "param/text")
    client.patch("/api/view", json={"display": "icon"})
    client.post("/api/undo")
    g = _graph(client)
    assert g["workflow"]["nodes"] == [] and g["workflow"]["view"]["display"] == "icon"


def test_refused_edit_records_nothing(client: TestClient) -> None:
    t, p = _text_and_panel(client)
    before = _graph(client)["workflow"]
    r = client.post("/api/wires", json={"from": [t, "value"], "to": [p, "data"]})
    assert r.status_code == 400
    client.post("/api/undo")
    assert _graph(client)["workflow"]["wires"] == []  # the undo reverted the wire, not the 400
    client.post("/api/redo")
    assert _graph(client)["workflow"] == before


def test_delete_several_is_one_step(client: TestClient) -> None:
    t, p = _text_and_panel(client)
    s = _add(client, "param/slider", [0, 200])
    before = _graph(client)["workflow"]
    r = client.post(
        "/api/delete",
        json={"nodes": [p, s], "wires": [{"from": [t, "value"], "to": [p, "data"]}]},
    )
    assert r.status_code == 204, r.text
    assert [n["id"] for n in _graph(client)["workflow"]["nodes"]] == [t]
    client.post("/api/undo")
    assert _graph(client)["workflow"] == before


def test_move_several_is_one_step(client: TestClient) -> None:
    t, p = _text_and_panel(client)
    r = client.patch("/api/positions", json={"positions": {t: [10, 10], p: [300, 10]}})
    assert r.status_code == 200, r.text
    pos = {n["id"]: n["position"] for n in _graph(client)["workflow"]["nodes"]}
    assert pos == {t: [10, 10], p: [300, 10]}
    client.post("/api/undo")
    pos = {n["id"]: n["position"] for n in _graph(client)["workflow"]["nodes"]}
    assert pos == {t: [0, 0], p: [200, 0]}
    assert client.patch("/api/positions", json={"positions": {"nope": [0, 0]}}).status_code == 404


def test_paste_copies_nodes_and_inner_wires(client: TestClient) -> None:
    t, p = _text_and_panel(client)
    wf = _graph(client)["workflow"]
    r = client.post(
        "/api/paste", json={"nodes": wf["nodes"], "wires": wf["wires"], "offset": [0, 100]}
    )
    assert r.status_code == 201, r.text
    t2, p2 = r.json()["ids"]
    assert {t2, p2}.isdisjoint({t, p})
    g = _graph(client)
    nodes = {n["id"]: n for n in g["workflow"]["nodes"]}
    assert nodes[t2]["value"] == "hello" and nodes[t2]["position"] == [0, 100]
    assert {"from": [t2, "value"], "to": [p2, "data"]} in g["workflow"]["wires"]
    assert len(g["workflow"]["wires"]) == 2
    client.post("/api/undo")
    assert len(_graph(client)["workflow"]["nodes"]) == 2


def test_paste_a_library_component_keeps_its_settings(client: TestClient) -> None:
    rid = _add(client, "builtin/raster/reclassify")
    node = next(n for n in _graph(client)["workflow"]["nodes"] if n["id"] == rid)
    r = client.post("/api/paste", json={"nodes": [node]})
    (new,) = r.json()["ids"]
    copy = next(n for n in _graph(client)["workflow"]["nodes"] if n["id"] == new)
    assert copy["component"] == node["component"] and copy["settings"] == node["settings"]
    assert client.post("/api/paste", json={"nodes": [{"component": "x"}]}).status_code == 400


def test_groups(client: TestClient) -> None:
    t, p = _text_and_panel(client)
    r = client.post("/api/groups", json={"title": "Inputs", "nodes": [t, p]})
    assert r.status_code == 201 and r.json() == {"index": 0}
    r = client.patch("/api/groups/0", json={"title": "Renamed"})
    assert r.json() == {"title": "Renamed", "nodes": [t, p]}
    assert _graph(client)["workflow"]["groups"] == [{"title": "Renamed", "nodes": [t, p]}]
    client.post("/api/undo")
    assert _graph(client)["workflow"]["groups"][0]["title"] == "Inputs"
    assert client.delete("/api/groups/0").status_code == 204
    assert _graph(client)["workflow"]["groups"] == []
    assert client.delete("/api/groups/0").status_code == 404
    assert client.post("/api/groups", json={"nodes": []}).status_code == 400
    assert client.post("/api/groups", json={"nodes": ["nope"]}).status_code == 404


def test_dirty_follows_save_and_undo(client: TestClient) -> None:
    assert _graph(client)["dirty"] is False
    t = _add(client, "param/text")
    assert client.post("/api/workflow/save", json={"path": "w.geoknit"}).status_code == 200
    assert _graph(client)["dirty"] is False
    client.patch(f"/api/nodes/{t}", json={"value": "x"})
    assert _graph(client)["dirty"] is True
    client.post("/api/undo")
    assert _graph(client)["dirty"] is False


def test_open_clears_the_history(client: TestClient) -> None:
    _add(client, "param/text")
    client.post("/api/workflow/save", json={"path": "w.geoknit"})
    client.post("/api/workflow/open", json={"path": "w.geoknit"})
    assert _graph(client)["can_undo"] is False


def test_autosave_is_offered_after_a_restart(project: Path, trust_file: Path) -> None:
    autosaves = trust_file.parent / "autosave"
    with make_client(project, trust_file) as c:
        t = _add(c, "param/text")
        c.post("/api/workflow/save", json={"path": "w.geoknit"})
        assert not autosaves.exists() or not list(autosaves.iterdir())
        c.patch(f"/api/nodes/{t}", json={"value": "unsaved edit"})
        (auto,) = autosaves.iterdir()
        assert auto.name.startswith("w-")
        assert not list(project.rglob("*autosave*"))  # never inside the project
    saved = (project / "w.geoknit").read_text(encoding="utf-8")

    with make_client(project, trust_file) as c:
        c.post("/api/workflow/open", json={"path": "w.geoknit"})
        g = _graph(c)
        assert g["recovery"] is True and g["workflow"]["nodes"][0]["value"] == ""
        r = c.post("/api/workflow/recover", json={"restore": True})
        assert r.status_code == 200, r.text
        g = r.json()
        assert g["recovery"] is False and g["dirty"] is True
        assert g["workflow"]["nodes"][0]["value"] == "unsaved edit"
        assert (project / "w.geoknit").read_text(encoding="utf-8") == saved  # file untouched
        c.post("/api/undo")  # restoring is one undo step
        assert _graph(c)["workflow"]["nodes"][0]["value"] == ""
        assert c.post("/api/workflow/save", json={}).status_code == 200
        assert not list(autosaves.iterdir())


def test_discarding_the_autosave(project: Path, trust_file: Path) -> None:
    with make_client(project, trust_file) as c:
        _add(c, "param/slider")  # untitled, never saved
    with make_client(project, trust_file) as c:
        assert _graph(c)["recovery"] is True
        r = c.post("/api/workflow/recover", json={"restore": False})
        assert r.json()["recovery"] is False and r.json()["workflow"]["nodes"] == []
        assert c.post("/api/workflow/recover", json={"restore": False}).status_code == 400
    with make_client(project, trust_file) as c:
        assert _graph(c)["recovery"] is False


def test_autosave_matching_the_file_is_not_offered(project: Path, trust_file: Path) -> None:
    with make_client(project, trust_file) as c:
        t = _add(c, "param/text")
        c.post("/api/workflow/save", json={"path": "w.geoknit"})
        c.patch(f"/api/nodes/{t}", json={"value": "x"})
        c.post("/api/undo")  # back to the saved state: the autosave goes away
        assert not list((trust_file.parent / "autosave").iterdir())
    with make_client(project, trust_file) as c:
        c.post("/api/workflow/open", json={"path": "w.geoknit"})
        assert _graph(c)["recovery"] is False


def test_new_routes_are_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/undo", "/api/redo", "/api/delete", "/api/positions", "/api/paste",
        "/api/groups", "/api/groups/{index}", "/api/workflow/recover",
    ):  # fmt: skip
        assert path in paths, path
