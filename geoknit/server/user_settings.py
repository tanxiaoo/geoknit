"""The user's own settings, ``settings.json`` next to the trust file (change 02).

They belong to the user, not to a workflow: today only ``theme``
(``system`` | ``light`` | ``dark``). A missing or unreadable file means the
defaults; keys GeoKnit does not know are kept and written back.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

THEMES = ("system", "light", "dark")
DEFAULTS: dict[str, Any] = {"theme": "system"}

# Windows refuses to replace a file another process (or reader) has open; retry briefly.
_REPLACE_TRIES = 10
_REPLACE_WAIT = 0.05


class UserSettings:
    """Read and update ``settings.json`` (written atomically)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self, strict: bool = False) -> dict[str, Any]:
        """The file's object; ``{}`` when missing or not valid JSON. With ``strict``, an
        ``OSError`` other than a missing file is raised, so an update never drops the
        keys of a file it could not read."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            if strict:
                raise
            return {}
        try:
            data = json.loads(text)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def get(self) -> dict[str, Any]:
        """The known settings, with defaults for missing or invalid values."""
        data = self._read()
        theme = data.get("theme")
        return {"theme": theme if theme in THEMES else DEFAULTS["theme"]}

    @property
    def theme(self) -> str:
        return str(self.get()["theme"])

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Merge ``changes`` (already validated) into the file; other keys stay."""
        if not changes:
            return self.get()
        with self._lock:
            data = self._read(strict=True)
            data.update(changes)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # a unique temp name: two servers sharing the folder never share a temp file
            fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix="settings.", suffix=".tmp")
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(json.dumps(data, indent=2) + "\n")
                self._replace(tmp)
            finally:
                tmp.unlink(missing_ok=True)
        return self.get()

    def _replace(self, tmp: Path) -> None:
        for attempt in range(_REPLACE_TRIES):
            try:
                tmp.replace(self.path)
                return
            except PermissionError:
                if attempt == _REPLACE_TRIES - 1:
                    raise
                time.sleep(_REPLACE_WAIT)
