"""PLAN Phase 4 "Done when": build, run and read the synthetic workflow via the API."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import SYNTHETIC, load_make_data
from tests.server.conftest import collect_until_finished


def _metrics(summary: str) -> dict[str, float]:
    lines = summary.splitlines()
    header = next(i for i, line in enumerate(lines) if "RMSE" in line)
    names = lines[header].split()
    values = [float(v) for v in lines[header + 1].split()[1:]]  # drop the row index
    return dict(zip(names, values, strict=True))


def _build(client: TestClient, recipe: dict) -> dict[str, str]:
    """Rebuild ``recipe`` node by node and wire by wire; return old id → new id."""
    ids: dict[str, str] = {}
    for raw in recipe["nodes"]:
        body = {"component": raw["component"], "position": raw["position"]}
        if raw["component"] == "inline":
            body["source"] = raw["source"]
        r = client.post("/api/nodes", json=body)
        assert r.status_code == 201, r.text
        nid = r.json()["id"]
        ids[raw["id"]] = nid
        patch: dict = {}
        if raw["component"] == "param/text":
            patch["value"] = raw["value"]
        elif raw["component"] == "param/slider":
            patch = {k: raw[k] for k in ("min", "max", "step", "value")}
        elif raw["component"] == "param/colormap":
            patch["value"] = raw["value"]
        elif raw["component"] == "param/layer":
            patch["style"] = raw["style"]
        elif raw.get("settings"):
            patch["settings"] = raw["settings"]
        if patch:
            r = client.patch(f"/api/nodes/{nid}", json=patch)
            assert r.status_code == 200, r.text
    for w in recipe["wires"]:
        (src, sp), (dst, dp) = w["from"], w["to"]
        r = client.post("/api/wires", json={"from": [ids[src], sp], "to": [ids[dst], dp]})
        assert r.status_code == 201, r.text
    return ids


def test_build_run_and_read_the_synthetic_workflow(client: TestClient, project: Path) -> None:
    load_make_data()(project / "data")
    recipe = json.loads((SYNTHETIC / "imd.geoknit").read_text(encoding="utf-8"))
    ids = _build(client, recipe)

    graph = client.get("/api/graph").json()
    assert len(graph["nodes"]) == len(recipe["nodes"])
    assert len(graph["workflow"]["wires"]) == len(recipe["wires"])
    # Map Layer and Map Viewer are view nodes: never out of date, never in a plan.
    work = [n for n in recipe["nodes"] if n["component"] not in ("param/layer", "param/map")]
    assert len(work) < len(recipe["nodes"])
    # the banner counts components only, never Params (decided 28 Nov 2026)
    components = [n for n in recipe["nodes"] if not n["component"].startswith("param/")]
    assert graph["out_of_date"] == len(components)

    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "states"
        r = client.post("/api/run", json={"mode": "all"})
        assert r.status_code == 202, r.text
        assert len(r.json()["plan"]) == len(work)
        events = collect_until_finished(ws)

    finished = events[-1]
    assert finished["report"]["ok"], finished
    assert [e["type"] for e in events].count("run_finished") == 1

    # started → log… → done, in that order, for every component node.
    for raw in components:
        nid = ids[raw["id"]]
        mine = [e["type"] for e in events if e.get("node") == nid]
        assert mine[0] == "started" and mine[-1] == "done", (raw["component"], mine)
        assert set(mine[1:-1]) <= {"log"}, mine
    reclassify = ids[
        next(n["id"] for n in recipe["nodes"] if n["component"].endswith("reclassify"))
    ]
    assert any(e["type"] == "log" and e["node"] == reclassify for e in events)

    panel = ids[next(n["id"] for n in recipe["nodes"] if n["component"] == "param/panel")]
    out = client.get(f"/api/nodes/{panel}/output").json()
    assert out["state"] == "done"
    metrics = _metrics(out["outputs"]["data"])
    assert metrics["n"] == 42
    assert metrics["R²"] > 0.5
    assert client.get("/api/graph").json()["out_of_date"] == 0

    # Save through the API and open it again: the same workflow comes back.
    assert client.post("/api/workflow/save", json={"path": "built.geoknit"}).json() == {
        "path": "built.geoknit"
    }
    saved = (project / "built.geoknit").read_bytes()
    reopened = client.post("/api/workflow/open", json={"path": "built.geoknit"}).json()
    assert reopened["trusted"] is True  # saved on this machine
    assert reopened["path"] == "built.geoknit"
    assert len(reopened["nodes"]) == len(recipe["nodes"])
    client.post("/api/workflow/save", json={})
    assert (project / "built.geoknit").read_bytes() == saved
