"""Top-bar status, canvas view and Panel size (Phase 5 additions to SPEC 9)."""

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from geoknit.core.trust import TRUST_FILE_ENV, TrustStore


def test_status_reports_python_and_worker(client: TestClient) -> None:
    status = client.get("/api/status").json()
    assert status["python"] == f"{sys.version_info[0]}.{sys.version_info[1]}"
    assert status["worker"] == "idle"
    assert isinstance(status["pid"], int)


def test_view_is_saved_with_the_workflow(client: TestClient, project: Path) -> None:
    r = client.patch("/api/view", json={"display": "icon", "zoom": 0.8, "offset": [10, -5]})
    assert r.json() == {"display": "icon", "zoom": 0.8, "offset": [10, -5]}
    assert client.patch("/api/view", json={"zoom": 1.5}).json()["display"] == "icon"
    assert client.patch("/api/view", json={"display": "default"}).status_code == 422
    client.post("/api/workflow/save", json={"path": "wf.geoknit"})
    saved = json.loads((project / "wf.geoknit").read_text(encoding="utf-8"))
    assert saved["view"] == {"display": "icon", "zoom": 1.5, "offset": [10, -5]}


def test_panel_size_round_trips_and_keeps_results(client: TestClient, project: Path) -> None:
    panel = client.post("/api/nodes", json={"component": "param/panel"}).json()["id"]
    text = client.post("/api/nodes", json={"component": "param/text"}).json()["id"]
    assert client.get("/api/graph").json()["nodes"][panel]["size"] is None
    r = client.patch(f"/api/nodes/{panel}", json={"size": [240, 180]})
    assert r.status_code == 200 and r.json()["size"] == [240, 180]
    assert client.patch(f"/api/nodes/{text}", json={"size": [1, 1]}).status_code == 400
    assert client.patch(f"/api/nodes/{panel}", json={"size": [0, 1]}).status_code == 400

    client.post("/api/workflow/save", json={"path": "wf.geoknit"})
    view = client.post("/api/workflow/open", json={"path": "wf.geoknit"}).json()
    assert view["nodes"][panel]["size"] == [240, 180]
    node = next(n for n in view["workflow"]["nodes"] if n["id"] == panel)
    assert node["size"] == [240, 180]


def test_trust_file_can_be_moved_by_environment(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv(TRUST_FILE_ENV, str(tmp_path / "t.json"))  # type: ignore[attr-defined]
    assert TrustStore().path == tmp_path / "t.json"
