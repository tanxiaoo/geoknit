"""Component icons: prefixed names and ``.svg`` files of packs (change 01, section 9)."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from geoknit.components.layout import PARAM_ICONS
from geoknit.components.registry import default_registry
from geoknit.core.graph import PARAMS
from geoknit.server.app import create_app

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle r="9"/></svg>\n'

PREFIXED = re.compile(r"^(gis|lucide|tabler):[a-z0-9]+(-[a-z0-9]+)*$")


def _component(name: str, icon: str) -> str:
    return (
        "# geoknit: component\n"
        f"# name: {name}\n"
        "# category: Icons\n"
        f"# icon: {icon}\n"
        "# outputs:\n"
        "#   out: Number\n"
        "\n"
        "# --- code ---\n"
        "out = 1\n"
    )


def _pack(folder: Path) -> Path:
    """A pack folder with components naming good and bad ``.svg`` paths."""
    pack = folder / "pack"
    (pack / "Icons" / "icons").mkdir(parents=True)
    (pack / "shared").mkdir()
    for path in (pack / "Icons" / "icons" / "x.svg", pack / "shared" / "y.svg"):
        path.write_bytes(SVG.encode())
    (folder / "secret.svg").write_bytes(SVG.encode())
    sources = {
        "own": "icons/x.svg",
        "shared": "../shared/y.svg",
        "outside": "../../secret.svg",
        "absolute": str((folder / "secret.svg").resolve()),
        "missing": "icons/nope.svg",
        "named": "gis:buffer",
    }
    for name, icon in sources.items():
        (pack / "Icons" / f"{name}.py").write_text(_component(name, icon), encoding="utf-8")
    return pack


def _client(tmp_path: Path) -> TestClient:
    project = tmp_path / "project"
    project.mkdir()
    registry = default_registry(tmp_path / "no-user-components", packs=False)
    registry.add_folder(_pack(tmp_path), "fakepack", "1.0", origin="pack")
    return TestClient(create_app(project, registry=registry, trust_file=tmp_path / "t.json"))


def test_pack_svg_icon_is_served(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        r = client.get("/api/components/fakepack/Icons/own/icon")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert r.text == SVG
        # hardened: never sniffed as another type, no scripts, nothing loaded
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-security-policy"] == (
            "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        )
        # A file elsewhere inside the pack folder is fine too.
        assert client.get("/api/components/fakepack/Icons/shared/icon").status_code == 200
        entry = next(
            e
            for e in client.get("/api/components").json()["components"]
            if e["ref"] == "fakepack/Icons/own"
        )
        assert entry["icon"] == "icons/x.svg"


def test_icon_outside_the_pack_or_missing_is_404(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        for name in ("outside", "absolute", "missing", "named"):
            r = client.get(f"/api/components/fakepack/Icons/{name}/icon")
            assert r.status_code == 404, name
        assert client.get("/api/components/nope/x/y/icon").status_code == 404
        assert client.get("/api/components/builtin/raster/reclassify/icon").status_code == 404


def test_builtin_and_params_icons_are_prefixed(tmp_path: Path) -> None:
    registry = default_registry(tmp_path / "none", packs=False)
    for ref in registry.refs():
        icon = registry.spec(ref).icon
        assert icon is not None and PREFIXED.match(icon), (ref, icon)
    assert set(PARAM_ICONS) == set(PARAMS)
    for kind, icon in PARAM_ICONS.items():
        assert PREFIXED.match(icon), (kind, icon)
