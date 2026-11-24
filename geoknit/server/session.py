"""The server's state: one workflow, its solver, the worker, trust (SPEC 9, 11).

All UI actions land here through ``app.py``. Edits happen under one lock;
runs execute on a background thread and report through the event
broadcaster, so ``POST /api/run`` returns at once and ``POST /api/stop`` can
interrupt it.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

from geoknit.components.registry import Registry, default_registry
from geoknit.core.executor import Event, RunReport
from geoknit.core.graph import (
    INLINE,
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
    dumps,
    graph_from_dict,
    graph_to_dict,
    is_modified,
)
from geoknit.runtime.client import WorkerExecutor
from geoknit.server.events import Broadcaster

UNTRUSTED = "This workflow contains Python code. Trust and allow running?"
RUNNING_MSG = "stop the run first"


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

    def close(self) -> None:
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

    def graph_view(self) -> dict[str, Any]:
        with self.lock:
            return {
                "workflow": graph_to_dict(self.graph, self.base_dir),
                "nodes": {nid: self.node_view(nid) for nid in self.graph.nodes},
                "out_of_date": self.solver.out_of_date_count,
                "path": self._rel(self.workflow_path) if self.workflow_path else None,
                "trusted": self.trusted,
                "running": self._running,
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
            node = self.graph.add_component(
                component, self.registry, position=position, source=source
            )
            self._publish_states()
            return self.node_view(node.id)

    def patch_node(self, node_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply ``source``, ``settings``, slider fields / ``value``, ``position``, ``display``."""
        with self.lock:
            self._check_trusted()
            node = self._node(node_id)
            affects_results = set(changes) - {"position", "display"}
            if affects_results:
                self._check_idle()
            g = self.graph
            if "source" in changes:
                g.set_source(node_id, changes["source"])
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
            if affects_results:
                self._publish_states()
            return self.node_view(node_id)

    def remove_node(self, node_id: str) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            self._node(node_id)
            self.graph.remove_node(node_id)
            self._publish_states()

    def add_wire(self, src: str, src_port: str, dst: str, dst_port: str) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            self._node(src)
            self._node(dst)
            self.graph.add_wire(src, src_port, dst, dst_port)
            self._publish_states()

    def remove_wire(self, src: str, src_port: str, dst: str, dst_port: str) -> None:
        with self.lock:
            self._check_trusted()
            self._check_idle()
            self.graph.remove_wire(src, src_port, dst, dst_port)
            self._publish_states()

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
            self.executor.attach(graph, solver, base_dir=self.base_dir)
            self.events.publish({"type": "workflow_opened", "path": self._rel(target)})
            self._publish_states()
            return self.graph_view()

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
