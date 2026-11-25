"""Component registry: resolves references such as ``builtin/raster/reclassify``.

Three sources, loaded in this order (SPEC 4):

- built-ins: ``geoknit/components/builtin/<category>/<name>.py`` →
  ``builtin/<category>/<name>``;
- the user folder ``~/.geoknit/components/<category>/<name>.py`` →
  ``user/<category>/<name>``;
- community packs: every entry point in the group ``geoknit.components``
  gives a folder (the entry point is a path string, or a callable returning
  one) → ``<entry point name>/<category>/<name>``.

A file that does not parse, or a pack that fails to load, is skipped with a
warning; it never stops GeoKnit from starting.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from geoknit import __version__
from geoknit.core.component import (
    ComponentParseError,
    ComponentSpec,
    LibraryEntry,
    parse_component,
)

BUILTIN_DIR = Path(__file__).parent / "builtin"
USER_DIR = Path.home() / ".geoknit" / "components"
USER_DIR_ENV = "GEOKNIT_USER_COMPONENTS"
"""Environment variable that moves the user component folder (used by end-to-end tests)."""
ENTRY_POINT_GROUP = "geoknit.components"
RESERVED_PREFIXES = ("builtin", "user", "inline", "param")


class RegistryWarning(UserWarning):
    """A component file or pack was skipped."""


@dataclass(frozen=True)
class RegisteredComponent:
    """A library entry together with its parsed header, for the ribbon."""

    entry: LibraryEntry
    spec: ComponentSpec
    origin: str
    """``builtin``, ``user`` or ``pack``."""
    path: Path


class Registry:
    """All components available by reference."""

    def __init__(self, user_dir: Path | None = None) -> None:
        self._items: dict[str, RegisteredComponent] = {}
        self.user_dir = user_dir
        """Where "Save as component…" writes (``user/<category>/<name>``); ``None`` = nowhere."""

    def reload_user(self) -> None:
        """Re-read the user folder after a component was saved there."""
        if self.user_dir is None:
            return
        for ref in [r for r, item in self._items.items() if item.origin == "user"]:
            del self._items[ref]
        if self.user_dir.is_dir():
            self.add_folder(self.user_dir, "user", "0", origin="user")

    def add_folder(self, folder: Path, prefix: str, version: str, origin: str = "builtin") -> int:
        """Register ``<folder>/<category>/<name>.py`` as ``<prefix>/<category>/<name>``.

        Returns how many components were added; broken files are skipped with
        a ``RegistryWarning``.
        """
        added = 0
        for path in sorted(Path(folder).glob("*/*.py")):
            if path.name.startswith("_"):
                continue
            ref = f"{prefix}/{path.parent.name}/{path.stem}"
            try:
                source = path.read_text(encoding="utf-8")
                spec = parse_component(source)
            except (OSError, UnicodeDecodeError, ComponentParseError) as exc:
                warnings.warn(f"skipped component {path}: {exc}", RegistryWarning, stacklevel=2)
                continue
            entry = LibraryEntry(ref=ref, source=source, version=version)
            self._items[ref] = RegisteredComponent(entry, spec, origin, path)
            added += 1
        return added

    def add_packs(self, entry_points: Callable[[], Any] | None = None) -> list[str]:
        """Load every pack in the ``geoknit.components`` entry-point group; return their names."""
        found = (
            entry_points()
            if entry_points is not None
            else metadata.entry_points(group=ENTRY_POINT_GROUP)
        )
        loaded: list[str] = []
        for ep in found:
            name = ep.name
            if name in RESERVED_PREFIXES or "/" in name:
                warnings.warn(
                    f'skipped component pack "{name}": the name is reserved or contains "/"',
                    RegistryWarning,
                    stacklevel=2,
                )
                continue
            try:
                target = ep.load()
                folder = Path(target() if callable(target) else target)
                if not folder.is_dir():
                    raise FileNotFoundError(f"{folder} is not a folder")
            except Exception as exc:  # noqa: BLE001  (a broken pack must not stop startup)
                warnings.warn(
                    f'skipped component pack "{name}": {exc}', RegistryWarning, stacklevel=2
                )
                continue
            dist = getattr(ep, "dist", None)
            version = getattr(dist, "version", None) or "0"
            self.add_folder(folder, name, version, origin="pack")
            loaded.append(name)
        return loaded

    # ── lookups ──
    def get(self, ref: str) -> LibraryEntry:
        try:
            return self._items[ref].entry
        except KeyError:
            raise KeyError(f'unknown component "{ref}"') from None

    def item(self, ref: str) -> RegisteredComponent:
        try:
            return self._items[ref]
        except KeyError:
            raise KeyError(f'unknown component "{ref}"') from None

    def spec(self, ref: str) -> ComponentSpec:
        return self.item(ref).spec

    def refs(self) -> list[str]:
        return sorted(self._items)

    def entries(self) -> list[dict[str, Any]]:
        """Header metadata of every component, for the ribbon (``GET /api/components``)."""
        out: list[dict[str, Any]] = []
        for ref in self.refs():
            item = self._items[ref]
            spec = item.spec
            out.append(
                {
                    "ref": ref,
                    "version": item.entry.version,
                    "origin": item.origin,
                    "name": spec.name,
                    "category": spec.category,
                    "icon": spec.icon,
                    "description": spec.description,
                    "inputs": [
                        {"name": p.name, "type": p.type, "access": p.access}
                        for p in spec.inputs.values()
                    ],
                    "outputs": [{"name": p.name, "type": p.type} for p in spec.outputs.values()],
                    "requires": list(spec.requires),
                }
            )
        return out


def default_registry(
    user_dir: Path | None = None,
    *,
    packs: bool = True,
    entry_points: Callable[[], Any] | None = None,
) -> Registry:
    """Built-ins, then the user folder, then installed packs."""
    folder = user_components_dir() if user_dir is None else Path(user_dir)
    reg = Registry(folder)
    reg.add_folder(BUILTIN_DIR, "builtin", __version__)
    if folder.is_dir():
        reg.add_folder(folder, "user", "0", origin="user")
    if packs:
        reg.add_packs(entry_points)
    return reg


def user_components_dir() -> Path:
    """``~/.geoknit/components``, or ``$GEOKNIT_USER_COMPONENTS`` when set."""
    env = os.environ.get(USER_DIR_ENV)
    return Path(env) if env else USER_DIR
