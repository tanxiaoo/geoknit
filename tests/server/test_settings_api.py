"""User settings (change 02): ``settings.json`` next to the trust file, the theme API,
and the saved theme written into the served ``index.html``."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geoknit.server import app as app_module
from geoknit.server.user_settings import UserSettings
from tests.conftest import SYNTHETIC
from tests.server.conftest import collect_until_finished, make_client
from tests.server.test_api import SLEEPY, _add


def _settings(trust_file: Path) -> Path:
    return trust_file.parent / "settings.json"


def test_default_without_a_file(client: TestClient, trust_file: Path) -> None:
    assert client.get("/api/settings").json() == {"theme": "system"}
    assert not _settings(trust_file).exists()


def test_patch_writes_the_file_and_get_returns_it(
    client: TestClient, project: Path, trust_file: Path
) -> None:
    r = client.patch("/api/settings", json={"theme": "dark"})
    assert r.status_code == 200 and r.json() == {"theme": "dark"}
    assert json.loads(_settings(trust_file).read_text(encoding="utf-8")) == {"theme": "dark"}
    assert client.get("/api/settings").json() == {"theme": "dark"}
    # the user's, not the session's: a new server reads it back
    with make_client(project, trust_file) as other:
        assert other.get("/api/settings").json() == {"theme": "dark"}


def test_unknown_keys_survive(client: TestClient, trust_file: Path) -> None:
    path = _settings(trust_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"theme": "light", "future": {"a": 1}}), encoding="utf-8")
    assert client.get("/api/settings").json() == {"theme": "light"}
    assert client.patch("/api/settings", json={"theme": "system"}).status_code == 200
    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "system", "future": {"a": 1}}


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '{"theme": "purple"}'])
def test_unreadable_file_means_defaults(client: TestClient, trust_file: Path, text: str) -> None:
    path = _settings(trust_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    assert client.get("/api/settings").json() == {"theme": "system"}
    assert client.patch("/api/settings", json={"theme": "dark"}).json() == {"theme": "dark"}


@pytest.mark.parametrize(
    ("body", "status"), [({"theme": "purple"}, 422), ({"theme": 1}, 422), ({"theme": None}, 400)]
)
def test_invalid_theme_is_refused(
    client: TestClient, trust_file: Path, body: object, status: int
) -> None:
    r = client.patch("/api/settings", json=body)
    assert r.status_code == status, r.text
    assert not _settings(trust_file).exists()


def test_allowed_during_a_run_and_not_an_edit(client: TestClient) -> None:
    sleepy = _add(client, "inline", source=SLEEPY)
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert client.post("/api/run", json={"mode": "all"}).status_code == 202
        while True:  # wait until the component is really running
            msg = ws.receive_json()
            if msg["type"] == "log" and msg["node"] == sleepy:
                break
        before = client.get("/api/graph").json()
        assert before["running"]
        r = client.patch("/api/settings", json={"theme": "dark"})
        assert r.status_code == 200, r.text
        after = client.get("/api/graph").json()
        assert client.post("/api/stop").status_code == 200
        collect_until_finished(ws)
    # never an edit: nothing goes out of date, the undo history is unchanged
    assert after["out_of_date"] == before["out_of_date"]
    assert after["nodes"][sleepy]["state"] == before["nodes"][sleepy]["state"]
    assert after["can_undo"] == before["can_undo"] and not after["can_redo"]
    # undo removes the node added above, not the setting
    client.post("/api/undo")
    assert sleepy not in client.get("/api/graph").json()["nodes"]
    assert client.get("/api/settings").json() == {"theme": "dark"}


def test_allowed_on_a_read_only_workflow(client: TestClient, project: Path) -> None:
    shutil.copy(SYNTHETIC / "imd.geoknit", project / "imd.geoknit")
    view = client.post("/api/workflow/open", json={"path": "imd.geoknit"}).json()
    assert view["trusted"] is False
    assert client.patch("/api/settings", json={"theme": "light"}).status_code == 200
    assert client.get("/api/settings").json() == {"theme": "light"}
    assert client.get("/api/graph").json()["trusted"] is False


PAGE = """<!doctype html>
<html lang="en">
  <head><script>/* theme */</script><link rel="stylesheet" href="/assets/x.css"></head>
  <body><div id="root"></div></body>
</html>
"""


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the built frontend (``npm run build``), which tests cannot rely on."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(PAGE, encoding="utf-8")
    (static / "assets" / "x.css").write_text("body {}", encoding="utf-8")
    monkeypatch.setattr(app_module, "STATIC_DIR", static)
    return static


def test_index_carries_the_saved_setting(built: Path, project: Path, trust_file: Path) -> None:
    with make_client(project, trust_file) as c:
        for url in ("/", "/index.html"):
            r = c.get(url)
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
            assert '<html data-theme-setting="system" lang="en">' in r.text
        c.patch("/api/settings", json={"theme": "dark"})
        for url in ("/", "/index.html"):
            assert '<html data-theme-setting="dark" lang="en">' in c.get(url).text
        assert c.get("/assets/x.css").text == "body {}"  # the rest is still the static mount


def test_placeholder_without_a_build(
    tmp_path: Path, project: Path, trust_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "STATIC_DIR", tmp_path / "missing")
    with make_client(project, trust_file) as c:
        r = c.get("/")
        assert r.status_code == 200 and "npm run build" in r.text


def test_update_keeps_keys_when_the_file_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read error other than a missing file refuses the update instead of dropping keys."""
    path = tmp_path / "settings.json"
    path.write_text('{"theme": "light", "other": 1}', encoding="utf-8")
    settings = UserSettings(path)
    real = Path.read_text

    def locked(self: Path, *args: object, **kwargs: object) -> str:
        if self == path:
            raise PermissionError("locked")
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", locked)
    with pytest.raises(PermissionError):
        settings.update({"theme": "dark"})
    monkeypatch.undo()
    assert json.loads(path.read_text(encoding="utf-8")) == {"theme": "light", "other": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_update_writes_no_temp_files_and_skips_empty_changes(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = UserSettings(path)
    assert settings.update({}) == {"theme": "system"}
    assert not path.exists()
    settings.update({"theme": "dark"})
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]
