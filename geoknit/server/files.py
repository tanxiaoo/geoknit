"""The project folder tree for the left panel (SPEC 8, ``GET /api/files``)."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

HIDDEN = {".geoknit"}


def file_tree(project: Path) -> dict[str, Any]:
    """Nested ``{name, path, kind, children}``; folders first, ``.geoknit/`` hidden."""
    project = Path(project)
    return {"name": project.name, "path": "", "kind": "dir", "children": _children(project, ())}


def _children(folder: Path, rel: tuple[str, ...]) -> list[dict[str, Any]]:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    dirs, files = [], []
    for entry in entries:
        if entry.name in HIDDEN:
            continue
        parts = (*rel, entry.name)
        path = PurePosixPath(*parts).as_posix()
        try:
            is_dir = entry.is_dir()
        except OSError:
            continue
        if is_dir:
            dirs.append(
                {
                    "name": entry.name,
                    "path": path,
                    "kind": "dir",
                    "children": _children(entry, parts),
                }
            )
        else:
            files.append({"name": entry.name, "path": path, "kind": "file"})
    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda d: d["name"].lower())
    return dirs + files
