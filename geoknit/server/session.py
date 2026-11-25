"""The server's state: one workflow, its solver, the worker, trust (SPEC 9, 11).

All UI actions land here through ``app.py``. Edits happen under one lock;
runs execute on a background thread and report through the event
broadcaster, so ``POST /api/run`` returns at once and ``POST /api/stop`` can
interrupt it.

Every edit of the workflow is one undo step (SPEC 8): the session keeps
snapshots of the document and moves the live graph back with ``apply_dict``,
so only what really changed goes out of date. After each edit an unsaved
workflow is autosaved next to the trust file, never into the project folder.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import platform
import threading
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

from geoknit.components.registry import Registry, default_registry
from geoknit.core.component import ComponentParseError, parse_component
from geoknit.core.executor import Event, RunReport
from geoknit.core.graph import (
    INLINE,
    PARAM_PANEL,
    PARAM_SLIDER,
    PARAM_TEXT,
    Graph,
    GraphError,
    Node,
)
from geoknit.core.solver import RUN_ALL, Solver
from geoknit.core.trust import TrustStore
from geoknit.core.workflow import (
    WorkflowError,
    apply_dict,
    dumps,
    graph_from_dict,
    graph_to_dict,
    is_modified,
    node_from_dict,
)
from geoknit.runtime.client import WorkerExecutor
from geoknit.server.editor import EditorError, ExternalEditors, slugify
from geoknit.server.events import Broadcaster

UNTRUSTED = "This workflow contains Python code. Trust and allow running?"
RUNNING_MSG = "stop the run first"
HISTORY_LIMIT = 200
"""Undo steps kept per workflow."""


class SessionError(Exception):
    """A refused request; ``status`` is the HTTP status code."""

    status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequest(SessionError):
    status = 400


class Forbidden(SessionError):
    status = 403


class NotFound(SessionError):
    status = 404


class Conflict(SessionError):
    status = 409


def _ports(ports: Iterable[Any]) -> list[dict[str, Any]]:
    return [{"name": p.name, "type": p.type, "access": p.access, "file": p.file} for p in ports]


def _setting_view(s: Any) -> dict[str, Any]:
    return {
        "name": s.name,
        "value": s.value,
        "widget": s.widget,
        "options": list(s.options) if s.options is not None else None,
        "range": list(s.range) if s.range is not None else None,
    }


def report_dict(report: RunReport) -> dict[str, Any]:
    return {
        "ran": report.ran,
        "cached": report.cached,
        "failed": report.failed,
        "skipped": report.skipped,
        "ok": report.ok,
    }


class Session:
    """One open workflow in one project folder."""

    def __init__(
        self,
        project: Path,
        *,
        registry: Registry | None = None,
        trust: TrustStore | None = None,
        workflow: Path | None = None,
    ) -> None:
        self.project = Path(project).resolve()
        self.registry = registry if registry is not None else default_registry()
        self.trust = trust if trust is not None else TrustStore()
        self.events = Broadcaster()
        self.lock = threading.RLock()
        self.graph = Graph()
        self.solver = Solver(self.graph)
        self.workflow_path: Path | None = None
        self.trusted = True
        self._opened_bytes: bytes | None = None
        self._initial = workflow
        self._executor: WorkerExecutor | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []
        self.recovery = False
        """An autosave that differs from the opened workflow exists (SPEC 8)."""
        self.editors = ExternalEditors(self)
        """Nodes open in VS Code, synced through temp files."""

    # ── lifecycle ──
    @property
    def base_dir(self) -> Path:
        """Folder relative paths resolve against: the workflow's folder (SPEC 5)."""
        return self.workflow_path.parent if self.workflow_path is not None else self.project

    @property
    def executor(self) -> WorkerExecutor:
        if self._executor is None:
            raise RuntimeError("the session has not been started")
        return self._executor

    def start(self) -> None:
        self._executor = WorkerExecutor(
            self.graph, self.solver, base_dir=self.base_dir, on_event=self._on_event
        )
        if self._initial is not None:
            self.open(str(self._initial))
        else:
            self._check_recovery()

    def close(self) -> None:
        self.editors.stop()
        if self._running:
            self.executor.stop()
        if self._thread is not None:
            self._thread.join(10)
        if self._executor is not None:
            self._executor.close()

    @property
    def running(self) -> bool:
        return self._running

    def wait(self, timeout: float | None = None) -> None:
        """Wait for the current run to finish (for tests and the CLI)."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ── events ──
    def _on_event(self, e: Event) -> None:
        self.events.publish({"type": e.kind, "node": e.node_id, **e.data})

    def states_message(self) -> dict[str, Any]:
        return {
            "type": "states",
            "states": dict(self.solver.states),
            "out_of_date": self.solver.out_of_date_count,
        }

    def _publish_states(self) -> None:
        self.events.publish(self.states_message())

    # ── guards ──
    def _check_trusted(self) -> None:
        if not self.trusted:
            raise Forbidden(UNTRUSTED)

    def _check_idle(self) -> None:
        if self._running:
            raise Conflict(RUNNING_MSG)

    def _node(self, node_id: str) -> Node:
        try:
            return self.graph.nodes[node_id]
        except KeyError:
            raise NotFound(f'no node "{node_id}"') from None

    def _resolve(self, path: str, *, suffix: str | None = None) -> Path:
        p = Path(path)
        full = (p if p.is_absolute() else self.project / p).resolve()
        try:
            full.relative_to(self.project)
        except ValueError:
            raise BadRequest(f"{path} is outside the project folder") from None
        if suffix is not None and full.suffix.lower() != suffix:
            raise BadRequest(f"{path} is not a {suffix} file")
        return full

    def _rel(self, path: Path) -> str:
        return PurePosixPath(*path.relative_to(self.project).parts).as_posix()

    # ── history ──
    def _snapshot(self) -> dict[str, Any]:
        """The workflow document without its view (zoom and display are not undone)."""
        doc = graph_to_dict(self.graph)
        doc.pop("view", None)
        return copy.deepcopy(doc)

    @contextlib.contextmanager
    def _edit(self) -> Iterator[None]:
        """Record whatever the block changes as one undo step, even if it then fails."""
        before = self._snapshot()
        try:
            yield
        finally:
            if self._snapshot() != before:
                self._undo.append(before)
                del self._undo[:-HISTORY_LIMIT]
                self._redo.clear()
                self.recovery = False  # the autosave now holds this session's edits
                self._autosave()

    def _step(self, source: list[dict[str, Any]], target: list[dict[str, Any]]) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            if not source:
                return
            doc = source.pop()
            target.append(self._snapshot())
            apply_dict(self.graph, doc, self.registry)
            self._autosave()
            self._publish_states()

    def undo(self) -> None:
        self._step(self._undo, self._redo)

    def redo(self) -> None:
        self._step(self._redo, self._undo)

    # ── unsaved changes and autosave ──
    def _comparable(self, doc: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in doc.items() if k != "geoknit_version"}

    @property
    def dirty(self) -> bool:
        """The workflow differs from its file (has any content, when new)."""
        doc = graph_to_dict(self.graph, self.base_dir)
        if self._opened_bytes is None:
            return bool(doc["nodes"] or doc["groups"])
        try:
            saved = json.loads(self._opened_bytes.decode("utf-8"))
        except ValueError:
            return True
        return self._comparable(doc) != self._comparable(saved)

    def autosave_path(self, workflow: Path | None = None) -> Path:
        """``<trust folder>/autosave/<name>-<hash>.geoknit``, one per workflow file.

        Outside the project folder on purpose: a shared folder cannot plant
        an autosave that would skip the trust question.
        """
        key = str(workflow) if workflow is not None else str(self.project / "untitled")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        stem = workflow.stem if workflow is not None else "untitled"
        return self.trust.path.parent / "autosave" / f"{stem}-{digest}.geoknit"

    def _autosave(self) -> None:
        path = self.autosave_path(self.workflow_path)
        try:
            if self.dirty:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                text = dumps(graph_to_dict(self.graph, self.base_dir))
                tmp.write_text(text, encoding="utf-8", newline="\n")
                tmp.replace(path)
            else:
                path.unlink(missing_ok=True)
        except OSError:
            pass  # best effort: autosave must never break an edit

    def _read_autosave(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.autosave_path(self.workflow_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _check_recovery(self) -> None:
        """After opening: offer the autosave if it holds something else."""
        data = self._read_autosave()
        current = graph_to_dict(self.graph, self.base_dir)
        self.recovery = data is not None and self._comparable(data) != self._comparable(current)
        if not self.recovery:
            self.autosave_path(self.workflow_path).unlink(missing_ok=True)

    def recover(self, restore: bool) -> None:
        """Restore the autosave as one undo step, or discard it."""
        with self.lock:
            self._check_trusted()
            if not self.recovery:
                raise BadRequest("there is no autosave to recover")
            if not restore:
                self.autosave_path(self.workflow_path).unlink(missing_ok=True)
                self.recovery = False
                return
            self._check_idle()
            data = self._read_autosave()
            if data is None:
                self.recovery = False
                raise BadRequest("the autosave can no longer be read")
            with self._edit():
                apply_dict(self.graph, data, self.registry, view=True)
            self.recovery = False
            self._publish_states()

    # ── views ──
    def node_view(self, node_id: str) -> dict[str, Any]:
        node = self._node(node_id)
        view: dict[str, Any] = {
            "id": node.id,
            "component": node.component,
            "title": node.title,
            "state": self.solver.states.get(node.id),
            "position": node.position,
            "display": node.display,
            "inputs": _ports(node.inputs.values()),
            "outputs": _ports(node.outputs.values()),
        }
        if node.component == PARAM_TEXT:
            view["value"] = node.value
        elif node.component == PARAM_SLIDER:
            view.update(min=node.min, max=node.max, step=node.step, value=node.value)
        elif node.component == PARAM_PANEL:
            view["size"] = node.extra.get("size")
        elif not node.is_param:
            spec = node.spec
            view.update(
                source=node.source,
                version=node.version,
                based_on=node.based_on,
                modified=is_modified(node),
                parse_error=str(node.parse_error) if node.parse_error is not None else None,
                category=spec.category if spec else None,
                icon=spec.icon if spec else None,
                settings=[_setting_view(s) for s in spec.settings.values()] if spec else [],
            )
        return view

    def status(self) -> dict[str, Any]:
        """Python version and worker state, for the top bar."""
        return {
            "python": ".".join(platform.python_version_tuple()[:2]),
            "worker": "running" if self._running else "idle",
            "pid": self._executor.pid if self._executor is not None else None,
        }

    def _publish_worker(self) -> None:
        self.events.publish({"type": "worker", **self.status()})

    def set_view(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Canvas-wide view: ``display`` (text | icon), ``zoom``, ``offset``."""
        with self.lock:
            self._check_trusted()
            if "display" in changes and changes["display"] not in ("text", "icon"):
                raise BadRequest("display must be text or icon")
            self.graph.view.update(changes)
            self._autosave()
            return dict(self.graph.view)

    def graph_view(self) -> dict[str, Any]:
        with self.lock:
            return {
                "workflow": graph_to_dict(self.graph, self.base_dir),
                "nodes": {nid: self.node_view(nid) for nid in self.graph.nodes},
                "out_of_date": self.solver.out_of_date_count,
                "path": self._rel(self.workflow_path) if self.workflow_path else None,
                "trusted": self.trusted,
                "running": self._running,
                "dirty": self.dirty,
                "can_undo": bool(self._undo),
                "can_redo": bool(self._redo),
                "recovery": self.recovery,
            }

    def components(self) -> list[dict[str, Any]]:
        out = self.registry.entries()
        for entry in out:
            spec = self.registry.spec(entry["ref"])
            entry["settings"] = [_setting_view(s) for s in spec.settings.values()]
        return out

    def output(self, node_id: str) -> dict[str, Any]:
        self._node(node_id)
        ex = self.executor
        return {
            "state": self.solver.states.get(node_id),
            "log": list(ex.logs.get(node_id, [])),
            "error": ex.errors.get(node_id),
            "outputs": dict(ex.summaries.get(node_id, {})),
        }

    # ── edits ──
    def add_node(
        self, component: str, position: Iterable[float], source: str | None = None
    ) -> dict[str, Any]:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            if source is not None and component != INLINE:
                raise BadRequest('"source" is only for inline components')
            with self._edit():
                node = self.graph.add_component(
                    component, self.registry, position=position, source=source
                )
            self._publish_states()
            return self.node_view(node.id)

    def patch_node(self, node_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply ``source``, ``ports``, ``settings``, slider fields / ``value``, ``position``,
        ``display``."""
        with self.lock:
            self._check_trusted()
            node = self._node(node_id)
            affects_results = set(changes) - {"position", "display", "size"}
            if affects_results:
                self._check_idle()
            with self._edit():
                self._apply_patch(node, changes)
            if affects_results:
                self._publish_states()
            return self.node_view(node_id)

    def _apply_patch(self, node: Node, changes: dict[str, Any]) -> None:
        node_id, g = node.id, self.graph
        if "source" in changes:
            g.set_source(node_id, changes["source"])
        if changes.get("ports") is not None:
            ports = changes["ports"]
            g.set_ports(node_id, list(ports.get("inputs", [])), list(ports.get("outputs", [])))
        for name, value in (changes.get("settings") or {}).items():
            g.set_setting(node_id, name, value)
        slider = {k: changes[k] for k in ("min", "max", "step") if k in changes}
        if slider:
            if "value" in changes:
                slider["value"] = changes["value"]
            g.set_slider(node_id, **slider)
        elif "value" in changes:
            if node.component == PARAM_SLIDER:
                g.set_slider(node_id, value=changes["value"])
            else:
                g.set_value(node_id, changes["value"])
        if "position" in changes:
            g.set_position(node_id, changes["position"])
        if "display" in changes:
            g.set_display(node_id, changes["display"])
        if "size" in changes:
            if node.component != PARAM_PANEL:
                raise BadRequest(f"{node.title} has no size")
            size = changes["size"]
            if size is None:
                node.extra.pop("size", None)
            elif len(size) != 2 or min(size) <= 0:
                raise BadRequest("size must be [width, height] above 0")
            else:
                node.extra["size"] = list(size)

    def remove_node(self, node_id: str) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            self._node(node_id)
            with self._edit():
                self.graph.remove_node(node_id)
            self._publish_states()

    def add_wire(self, src: str, src_port: str, dst: str, dst_port: str) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            self._node(src)
            self._node(dst)
            with self._edit():
                self.graph.add_wire(src, src_port, dst, dst_port)
            self._publish_states()

    def remove_wire(self, src: str, src_port: str, dst: str, dst_port: str) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            with self._edit():
                self.graph.remove_wire(src, src_port, dst, dst_port)
            self._publish_states()

    # ── edits of several things at once (one undo step each) ──
    def delete(self, nodes: Iterable[str], wires: Iterable[tuple[str, str, str, str]]) -> None:
        """Remove wires, then nodes together with their wires."""
        node_ids, wire_list = list(nodes), list(wires)
        with self.lock:
            self._check_trusted()
            self._check_idle()
            for nid in node_ids:
                self._node(nid)
            with self._edit():
                for w in wire_list:
                    if w[0] not in node_ids and w[2] not in node_ids:
                        self.graph.remove_wire(*w)
                for nid in node_ids:
                    self.graph.remove_node(nid)
            self._publish_states()

    def move(self, positions: dict[str, list[float]]) -> None:
        """Move several nodes; allowed during a run."""
        with self.lock:
            self._check_trusted()
            for nid, pos in positions.items():
                self._node(nid)
                if len(pos) != 2:
                    raise BadRequest("a position is [x, y]")
            with self._edit():
                for nid, pos in positions.items():
                    self.graph.set_position(nid, pos)

    def paste(
        self,
        nodes: list[dict[str, Any]],
        wires: list[dict[str, Any]],
        offset: Iterable[float] = (20, 20),
    ) -> list[str]:
        """Add copies of workflow-format nodes under new ids, with the wires among them."""
        dx, dy = list(offset)
        with self.lock:
            self._check_trusted()
            self._check_idle()
            ids: dict[str, str] = {}
            with self._edit():
                for raw in nodes:
                    if not isinstance(raw, dict) or "id" not in raw:
                        raise BadRequest("each pasted node needs an id")
                    x, y = raw.get("position", [0, 0])
                    new_id = self.graph.new_id()
                    copied = {**copy.deepcopy(raw), "id": new_id, "position": [x + dx, y + dy]}
                    try:
                        self.graph.add_node(node_from_dict(copied, self.registry))
                    except (GraphError, WorkflowError) as exc:
                        raise BadRequest(f"cannot paste: {exc}") from None
                    ids[str(raw["id"])] = new_id
                for w in wires:
                    try:
                        (src, sp), (dst, dp) = w["from"], w["to"]
                    except (KeyError, TypeError, ValueError):
                        raise BadRequest(f"bad wire {w}") from None
                    if src in ids and dst in ids:
                        self.graph.add_wire(ids[src], sp, ids[dst], dp)
            self._publish_states()
            return list(ids.values())

    # ── groups (canvas only, so allowed during a run) ──
    def _members(self, nodes: Iterable[str]) -> list[str]:
        members = list(dict.fromkeys(nodes))
        if not members:
            raise BadRequest("a group needs at least one node")
        for nid in members:
            self._node(nid)
        return members

    def _group(self, index: int) -> dict[str, Any]:
        if not 0 <= index < len(self.graph.groups):
            raise NotFound(f"no group {index}")
        return self.graph.groups[index]

    def add_group(self, title: str, nodes: Iterable[str]) -> int:
        """Add a labelled box around ``nodes``; return its index."""
        with self.lock:
            self._check_trusted()
            members = self._members(nodes)
            with self._edit():
                self.graph.groups.append({"title": title, "nodes": members})
            return len(self.graph.groups) - 1

    def patch_group(
        self, index: int, title: str | None = None, nodes: Iterable[str] | None = None
    ) -> dict[str, Any]:
        with self.lock:
            self._check_trusted()
            group = self._group(index)
            members = self._members(nodes) if nodes is not None else None
            with self._edit():
                if title is not None:
                    group["title"] = title
                if members is not None:
                    group["nodes"] = members
            return dict(group)

    def remove_group(self, index: int) -> None:
        """Ungroup; the nodes stay."""
        with self.lock:
            self._check_trusted()
            self._group(index)
            with self._edit():
                del self.graph.groups[index]

    # ── running ──
    def run(self, mode: str = RUN_ALL, node_id: str | None = None) -> list[str]:
        """Start a run in the background; return the planned node ids."""
        with self.lock:
            self._check_trusted()
            self._check_idle()
            if node_id is not None:
                self._node(node_id)
            plan = self.solver.plan(mode, node_id)
            self._running = True
            self._publish_worker()
            self._thread = threading.Thread(
                target=self._run, args=(mode, node_id), name="geoknit-run", daemon=True
            )
            self._thread.start()
            return plan

    def _run(self, mode: str, node_id: str | None) -> None:
        report: RunReport | None = None
        message: str | None = None
        try:
            report = self.executor.run(mode, node_id)
        except Exception as exc:  # noqa: BLE001  (reported to the browser, never lost)
            message = f"{type(exc).__name__}: {exc}"
        finally:
            with self.lock:
                self._running = False
            self._publish_states()
            self._publish_worker()
            finished: dict[str, Any] = {"type": "run_finished"}
            finished["report"] = report_dict(report) if report is not None else None
            if message is not None:
                finished["error"] = message
            self.events.publish(finished)

    def stop(self) -> None:
        self.executor.stop()

    def clear_cache(self) -> bool:
        with self.lock:
            self._check_idle()
            complete = self.executor.clear_cache()
            self._publish_states()
            return complete

    # ── files ──
    def save(self, path: str | None = None) -> str:
        with self.lock:
            if path is None:
                if self.workflow_path is None:
                    raise BadRequest("give a path to save a new workflow")
                target = self.workflow_path
            else:
                target = self._resolve(path, suffix=".geoknit")
            if target.parent != self.base_dir:
                self._check_idle()
            text = dumps(graph_to_dict(self.graph, base_dir=target.parent))
            data = text.encode("utf-8")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.trust.add(data)
            old_base = self.base_dir
            for p in {self.autosave_path(self.workflow_path), self.autosave_path(target)}:
                p.unlink(missing_ok=True)
            self.recovery = False
            self.workflow_path, self._opened_bytes, self.trusted = target, data, True
            if self.base_dir != old_base:
                self.executor.attach(self.graph, self.solver, base_dir=self.base_dir)
                self._publish_states()
            return self._rel(target)

    def open(self, path: str) -> dict[str, Any]:
        with self.lock:
            self._check_idle()
            target = self._resolve(path, suffix=".geoknit")
            try:
                data = target.read_bytes()
            except OSError as exc:
                raise BadRequest(f"cannot open {path}: {exc.strerror or exc}") from None
            try:
                raw = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise BadRequest(f"{target.name} is not valid JSON: {exc}") from None
            if not isinstance(raw, dict):
                raise BadRequest(f"{target.name} is not a GeoKnit workflow")
            graph = graph_from_dict(raw, self.registry)
            solver = Solver(graph)
            self.graph, self.solver = graph, solver
            self.workflow_path, self._opened_bytes = target, data
            self.trusted = self.trust.is_trusted(data)
            self._undo.clear()
            self._redo.clear()
            self.editors.clear()
            self._check_recovery()
            self.executor.attach(graph, solver, base_dir=self.base_dir)
            self.events.publish({"type": "workflow_opened", "path": self._rel(target)})
            self._publish_states()
            return self.graph_view()

    # ── component files (SPEC 4) ──
    def save_component(self, node_id: str, overwrite: bool = False) -> dict[str, Any]:
        """Write the node's code to ``<user folder>/<category>/<name>.py`` (Save as component…)."""
        with self.lock:
            self._check_trusted()
            node = self._node(node_id)
            if node.is_param or node.source is None:
                raise BadRequest(f"{node.title} is not a component")
            folder = self.registry.user_dir
            if folder is None:
                raise BadRequest("there is no user component folder")
            try:
                spec = parse_component(node.source)
            except ComponentParseError as exc:
                raise BadRequest(f"fix the code first: {exc}") from None
            category, name = slugify(spec.category), slugify(spec.name)
            target = folder / category / f"{name}.py"
            ref = f"user/{category}/{name}"
            if target.exists() and not overwrite:
                raise Conflict(f'a user component "{spec.name}" ({ref}) already exists')
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(node.source, encoding="utf-8", newline="")
            except OSError as exc:
                raise BadRequest(f"cannot write {target}: {exc.strerror or exc}") from None
            self.registry.reload_user()
            return {"ref": ref, "path": str(target)}

    def open_in_editor(self, node_id: str) -> dict[str, Any]:
        """Write the node's file to a temp folder, start VS Code, keep both in sync."""
        with self.lock:
            self._check_trusted()
            node = self._node(node_id)
            if node.is_param or node.source is None:
                raise BadRequest(f"{node.title} has no code")
            try:
                path = self.editors.open(node_id, node.title, node.source)
            except EditorError as exc:
                raise BadRequest(str(exc)) from None
            return {"path": str(path)}

    def trust_current(self) -> None:
        with self.lock:
            if self._opened_bytes is not None:
                self.trust.add(self._opened_bytes)
            self.trusted = True


__all__ = [
    "BadRequest",
    "Conflict",
    "Forbidden",
    "GraphError",
    "NotFound",
    "Session",
    "SessionError",
    "WorkflowError",
]
