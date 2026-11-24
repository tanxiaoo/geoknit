"""Which workflow files may run their code (SPEC 11).

A workflow contains Python code. A file is trusted when the sha256 of its
bytes is listed in ``~/.geoknit/trusted.json``: GeoKnit adds the hash of every
file it saves, and the user adds others by answering "Trust and allow
running?".
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

TRUST_FILE = Path.home() / ".geoknit" / "trusted.json"
TRUST_FILE_ENV = "GEOKNIT_TRUST_FILE"
"""Environment variable that moves the trust file (used by end-to-end tests)."""
FORMAT = 1


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TrustStore:
    """The set of trusted workflow content hashes, kept in a JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            env = os.environ.get(TRUST_FILE_ENV)
            path = Path(env) if env else TRUST_FILE
        self.path = Path(path)

    def _load(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        hashes = data.get("hashes") if isinstance(data, dict) else None
        return [h for h in hashes if isinstance(h, str)] if isinstance(hashes, list) else []

    def is_trusted(self, data: bytes) -> bool:
        return content_hash(data) in self._load()

    def add(self, data: bytes) -> None:
        hashes = self._load()
        h = content_hash(data)
        if h in hashes:
            return
        hashes.append(h)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        text = json.dumps({"format": FORMAT, "hashes": hashes}, indent=2) + "\n"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.path)
