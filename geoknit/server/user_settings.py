"""The user's own settings, ``settings.json`` next to the trust file (change 02).

They belong to the user, not to a workflow: today only ``theme``
(``system`` | ``light`` | ``dark``). A missing or unreadable file means the
defaults; keys GeoKnit does not know are kept and written back.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

THEMES = ("system", "light", "dark")
DEFAULTS: dict[str, Any] = {"theme": "system"}


class UserSettings:
    """Read and update ``settings.json`` (written atomically)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
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
        with self._lock:
            data = self._read()
            data.update(changes)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        return self.get()
