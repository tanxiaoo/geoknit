"""Trusted workflow hashes (SPEC 11)."""

import json
from pathlib import Path

from geoknit.core.trust import TrustStore, content_hash


def test_trust_store_round_trip(tmp_path: Path) -> None:
    store = TrustStore(tmp_path / "home" / "trusted.json")
    assert not store.is_trusted(b"abc")
    store.add(b"abc")
    store.add(b"abc")
    assert store.is_trusted(b"abc")
    assert not store.is_trusted(b"abd")
    assert TrustStore(store.path).is_trusted(b"abc")
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data == {"format": 1, "hashes": [content_hash(b"abc")]}


def test_a_broken_trust_file_trusts_nothing(tmp_path: Path) -> None:
    path = tmp_path / "trusted.json"
    path.write_text("not json", encoding="utf-8")
    store = TrustStore(path)
    assert not store.is_trusted(b"abc")
    store.add(b"abc")
    assert store.is_trusted(b"abc")
