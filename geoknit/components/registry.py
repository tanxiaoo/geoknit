"""Component registry: resolves references such as ``builtin/raster/reclassify``.

Phase 2 loads the built-ins only (``builtin/<category>/<name>.py``). The user
folder ``~/.geoknit/components/`` and entry-point packs come in Phase 3.
"""

from __future__ import annotations

from pathlib import Path

from geoknit import __version__
from geoknit.core.component import LibraryEntry

BUILTIN_DIR = Path(__file__).parent / "builtin"


class Registry:
    """All components available by reference."""

    def __init__(self) -> None:
        self._entries: dict[str, LibraryEntry] = {}

    def add_folder(self, folder: Path, prefix: str, version: str) -> None:
        """Register ``<folder>/<category>/<name>.py`` as ``<prefix>/<category>/<name>``."""
        for path in sorted(folder.glob("*/*.py")):
            if path.name.startswith("_"):
                continue
            ref = f"{prefix}/{path.parent.name}/{path.stem}"
            source = path.read_text(encoding="utf-8")
            self._entries[ref] = LibraryEntry(ref=ref, source=source, version=version)

    def get(self, ref: str) -> LibraryEntry:
        try:
            return self._entries[ref]
        except KeyError:
            raise KeyError(f'unknown component "{ref}"') from None

    def refs(self) -> list[str]:
        return sorted(self._entries)


def default_registry() -> Registry:
    """The built-in components."""
    reg = Registry()
    reg.add_folder(BUILTIN_DIR, "builtin", __version__)
    return reg
