"""Open in VS Code (SPEC 4, 8): edit a component's file in an external editor.

The component's source is written to a temporary file and the editor is
started on it. A background thread polls the watched files: when a file
changes on disk, its text becomes the node's source (one undo step, as if it
were applied from the Code tab); when the node changes in GeoKnit (Settings
tab, undo), the file is rewritten so the two never drift apart.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from geoknit.server.session import Session

POLL_SECONDS = 0.5


class EditorError(RuntimeError):
    """The external editor could not be started."""


def slugify(name: str) -> str:
    """``"My Reclassify!"`` → ``"my_reclassify"`` (file and reference names)."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return s or "component"


def launch_vscode(path: Path) -> None:
    """Start VS Code (its ``code`` command) on ``path``."""
    exe = shutil.which("code")
    if exe is None:
        raise EditorError('VS Code was not found: put its "code" command on the PATH')
    try:
        subprocess.Popen(  # noqa: S603  (fixed program, our own temp file)
            [exe, str(path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise EditorError(f"could not start VS Code: {exc}") from None


@dataclass
class Watch:
    node_id: str
    path: Path
    last: str
    """The text the file and the node last agreed on."""


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n")


class ExternalEditors:
    """Temp files of nodes open in an external editor, kept in sync both ways."""

    def __init__(
        self,
        session: Session,
        *,
        launch: Callable[[Path], None] = launch_vscode,
        interval: float = POLL_SECONDS,
    ) -> None:
        self.session = session
        self.launch = launch
        self.interval = interval
        self.watches: dict[str, Watch] = {}
        self._folder: Path | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def folder(self) -> Path:
        if self._folder is None:
            self._folder = Path(tempfile.mkdtemp(prefix="geoknit-edit-"))
        return self._folder

    def open(self, node_id: str, title: str, source: str) -> Path:
        """Write the node's file (or reuse it) and start the editor on it."""
        text = _normalize(source)
        with self._lock:
            watch = self.watches.get(node_id)
            if watch is None:
                path = self.folder / f"{node_id}_{slugify(title)}.py"
                watch = Watch(node_id, path, text)
                self.watches[node_id] = watch
            watch.path.write_text(text, encoding="utf-8", newline="")
            watch.last = text
        self.launch(watch.path)
        self._start()
        return watch.path

    def clear(self) -> None:
        """Stop watching every file (another workflow was opened)."""
        with self._lock:
            self.watches.clear()

    def poll(self) -> list[str]:
        """One sync round; returns the ids of nodes whose source came from a file."""
        changed: list[str] = []
        with self._lock:
            watches = list(self.watches.values())
        for w in watches:
            if self._sync(w):
                changed.append(w.node_id)
        return changed

    def _sync(self, w: Watch) -> bool:
        from geoknit.server.session import Conflict, SessionError

        s = self.session
        with s.lock:
            node = s.graph.nodes.get(w.node_id)
            if node is None or node.source is None:
                with self._lock:
                    self.watches.pop(w.node_id, None)
                return False
            try:
                text = _normalize(w.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                return False  # being written, or deleted: try again next round
            if text != w.last:
                try:
                    s.patch_node(w.node_id, {"source": text})
                except Conflict:
                    return False  # a run is active: apply once it ends
                except SessionError:
                    pass  # e.g. read-only workflow: the file change is ignored
                w.last = text
                s.events.publish({"type": "node_changed", "node": w.node_id})
                return True
            current = _normalize(node.source)
            if current != w.last:
                try:
                    w.path.write_text(current, encoding="utf-8", newline="")
                except OSError:
                    return False
                w.last = current
        return False

    # ── background thread ──
    def _start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="geoknit-editor", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.poll()
            except Exception:  # noqa: BLE001, S110  (the watcher must never die)
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
