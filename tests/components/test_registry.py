"""Registry: built-ins, the user folder and entry-point packs (SPEC 4)."""

import sys
from pathlib import Path

import pytest

from geoknit.components.registry import RegistryWarning, default_registry
from geoknit.core.graph import Graph
from tests.core.sources import LENGTH, REPEAT


def _write(folder: Path, category: str, name: str, source: str) -> None:
    (folder / category).mkdir(parents=True, exist_ok=True)
    (folder / category / f"{name}.py").write_text(source, encoding="utf-8")


def test_builtins_are_registered(tmp_path: Path) -> None:
    reg = default_registry(tmp_path / "none", packs=False)
    assert "builtin/raster/reclassify" in reg.refs()
    assert "builtin/script/python" in reg.refs()
    meta = {e["ref"]: e for e in reg.entries()}["builtin/raster/write_raster"]
    assert meta["category"] == "Raster" and meta["origin"] == "builtin"
    assert meta["inputs"] == [
        {"name": "map", "type": "Raster", "access": "item"},
        {"name": "path", "type": "Text", "access": "item"},
    ]


def test_user_folder(tmp_path: Path) -> None:
    _write(tmp_path, "Text", "repeat", REPEAT)
    _write(tmp_path, "Text", "_private", LENGTH)  # leading underscore: ignored
    _write(tmp_path, "Text", "broken", "print('no header')\n")
    with pytest.warns(RegistryWarning, match="broken.py"):
        reg = default_registry(tmp_path, packs=False)
    assert "user/Text/repeat" in reg.refs()
    assert not [r for r in reg.refs() if "broken" in r or "_private" in r]
    assert reg.item("user/Text/repeat").origin == "user"
    g = Graph()
    node = g.add_component("user/Text/repeat", reg)
    assert node.title == "Repeat"


@pytest.fixture
def fake_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An installed distribution ``fakepack`` declaring a ``geoknit.components`` entry point."""
    site = tmp_path / "site"
    pkg = site / "fakepack"
    _write(pkg / "components", "Text", "repeat", REPEAT)
    (pkg / "__init__.py").write_text(
        "from pathlib import Path\n\n"
        "def components():\n    return Path(__file__).parent / 'components'\n",
        encoding="utf-8",
    )
    dist = site / "fakepack-0.3.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fakepack\nVersion: 0.3.0\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(
        "[geoknit.components]\n"
        "fake = fakepack:components\n"
        "missing = fakepack:no_such_function\n"
        "builtin = fakepack:components\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(site))
    yield site
    sys.modules.pop("fakepack", None)


def test_entry_point_pack(fake_pack: Path, tmp_path: Path) -> None:
    with pytest.warns(RegistryWarning) as record:
        reg = default_registry(tmp_path / "none")
    messages = " ".join(str(w.message) for w in record)
    assert '"missing"' in messages  # a broken entry point is skipped
    assert '"builtin"' in messages and "reserved" in messages
    assert "fake/Text/repeat" in reg.refs()
    item = reg.item("fake/Text/repeat")
    assert (item.origin, item.entry.version) == ("pack", "0.3.0")
    assert reg.get("builtin/raster/reclassify").ref == "builtin/raster/reclassify"  # untouched


def test_unknown_reference(tmp_path: Path) -> None:
    reg = default_registry(tmp_path, packs=False)
    with pytest.raises(KeyError, match='unknown component "nope/x/y"'):
        reg.get("nope/x/y")
