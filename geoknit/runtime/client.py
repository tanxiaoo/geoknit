"""Runs a graph through the worker process (SPEC 6).

``WorkerExecutor`` has the same surface as ``geoknit.core.executor.InProcessExecutor``
(``run``, ``summaries``, ``logs``, ``errors``, ``solver``, events) but sends each
component to a spawned worker, keyed by cache keys, and can ``stop()`` a run
from another thread.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from geoknit.core import types
from geoknit.core.cache import DEFAULT_LIMIT, GraphKeys, compute_keys
from geoknit.core.executor import Event, EventFn, RunReport
from geoknit.core.graph import PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, Node
from geoknit.core.solver import DONE, ERROR, RUN_ALL, RUN_TEST, RUNNING, SKIPPED, Solver
from geoknit.runtime import protocol as p
from geoknit.runtime.worker import worker_main

STOPPED = "stopped"
READY_TIMEOUT = 120.0
"""Seconds to wait for a new worker to start (imports can be slow on a cold disk)."""
_POLL = 0.05


class WorkerStartError(RuntimeError):
    """The worker process did not start."""


class _Stopped(Exception):
    pass


class _Crashed(Exception):
    pass


class WorkerExecutor:
    """Plans runs with the solver and executes components in a worker process."""

    def __init__(
        self,
        graph: Graph,
        solver: Solver | None = None,
        *,
        base_dir: Path | None = None,
        cache_dir: Path | None = None,
        cache_limit: int = DEFAULT_LIMIT,
        use_disk_cache: bool = True,
        on_event: EventFn | None = None,
    ) -> None:
        self.graph = graph
        self.solver = solver or Solver(graph)
        self.base_dir = base_dir
        if cache_dir is None and base_dir is not None and use_disk_cache:
            cache_dir = base_dir / ".geoknit" / "cache"
        self.cache_dir = cache_dir if use_disk_cache else None
        self.cache_limit = cache_limit
        self.on_event = on_event
        self.summaries: dict[str, dict[str, str]] = {}
        self.logs: dict[str, list[str]] = {}
        self.errors: dict[str, str] = {}
        self._done_ports: dict[str, dict[str, str]] = {}
        """Port keys each node had when it last finished, to spot changed files."""

        self._lock = threading.Lock()
        self._proc: BaseProcess | None = None
        self._conn: Connection | None = None
        self._ready = False
        self._running = False
        self._stop_requested = False
        graph.subscribe(self._on_change)
        self._start()

    # ── process management ──
    def _start(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        proc = ctx.Process(
            target=worker_main,
            args=(
                child,
                str(self.base_dir) if self.base_dir is not None else None,
                str(self.cache_dir) if self.cache_dir is not None else None,
                self.cache_limit,
            ),
            name="geoknit-worker",
            daemon=True,
        )
        proc.start()
        child.close()
        self._proc, self._conn, self._ready = proc, parent, False

    def _kill(self) -> None:
        proc, conn = self._proc, self._conn
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(1)
            if proc.is_alive():  # pragma: no cover
                proc.kill()
                proc.join(1)
        if conn is not None:
            conn.close()
        self._proc, self._conn, self._ready = None, None, False

    def clear_cache(self) -> bool:
        """ "Clear cache": empty worker memory and the disk cache; every node becomes
        out of date. ``False`` if some cache files could not be deleted yet."""
        with self._lock:
            if self._running:
                raise RuntimeError("stop the run before clearing the cache")
            self._running = True
        try:
            self._ensure_ready()
            self._send(p.ClearCache())
            while True:
                msg = self._recv()
                if isinstance(msg, p.Cleared):
                    complete = msg.complete
                    break
        except (_Stopped, _Crashed):
            self._recover()
            complete = False
        finally:
            with self._lock:
                self._running = False
        self._done_ports.clear()
        self.solver.invalidate(set(self.graph.nodes))
        return complete

    def restart(self) -> None:
        """Replace the worker with a fresh one (in-memory results are lost)."""
        with self._lock:
            self._kill()
            self._start()

    def stop(self) -> None:
        """Stop: terminate the worker; the running node ends ``error: stopped``.

        Safe to call from another thread while ``run`` is executing. A fresh
        worker is started; the disk cache stays.
        """
        with self._lock:
            if not self._running:
                self._kill()
                self._start()
                return
            self._stop_requested = True
            proc = self._proc
        if proc is not None and proc.is_alive():
            proc.terminate()

    def close(self) -> None:
        """Shut the worker down."""
        with self._lock:
            if self._conn is not None and self._proc is not None and self._proc.is_alive():
                try:
                    self._conn.send(p.Shutdown())
                    self._proc.join(2)
                except OSError:
                    pass
            self._kill()

    def __enter__(self) -> WorkerExecutor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    # ── messaging ──
    def _send(self, msg: p.ToWorker) -> None:
        assert self._conn is not None
        try:
            self._conn.send(msg)
        except OSError:
            if self._stop_requested:
                raise _Stopped from None
            raise _Crashed from None

    def _recv(self, timeout: float | None = None) -> p.FromWorker:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._stop_requested:
                raise _Stopped
            conn, proc = self._conn, self._proc
            assert conn is not None and proc is not None
            try:
                if conn.poll(_POLL):
                    return conn.recv()
            except (EOFError, OSError):
                if self._stop_requested:
                    raise _Stopped from None
                raise _Crashed from None
            if not proc.is_alive() and not conn.poll(0):
                if self._stop_requested:
                    raise _Stopped
                raise _Crashed
            if deadline is not None and time.monotonic() > deadline:
                raise WorkerStartError("the worker process did not start in time")

    def _ensure_ready(self) -> None:
        if self._ready:
            return
        msg = self._recv(READY_TIMEOUT)
        if not isinstance(msg, p.Ready):  # pragma: no cover
            raise WorkerStartError(f"unexpected first message from the worker: {msg!r}")
        self._ready = True

    # ── graph changes ──
    def _on_change(self, changed: set[str], removed: set[str]) -> None:
        for n in removed:
            for store in (self.summaries, self.logs, self.errors, self._done_ports):
                store.pop(n, None)

    def _emit(self, kind: str, node_id: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(Event(kind, node_id, data))

    # ── running ──
    def run(self, mode: str = RUN_ALL, node_id: str | None = None) -> RunReport:
        report = RunReport()
        keys = compute_keys(self.graph, self.base_dir)
        stale = {
            n
            for n, ports in self._done_ports.items()
            if self.solver.states.get(n) == DONE and keys.ports.get(n) != ports
        }
        if stale:  # a file it reads changed on disk (SPEC 6 "Out of date")
            self.solver.invalidate(stale)
        plan = self.solver.plan(mode, node_id)

        with self._lock:
            self._running, self._stop_requested = True, False
        try:
            try:
                self._ensure_ready()
                for key, value in keys.values.items():
                    self._send(p.PutValue(key, value))
            except (_Stopped, _Crashed):
                self._recover()
                return report
            for nid in plan:
                if not self._run_node(self.graph.node(nid), keys, report, test=mode == RUN_TEST):
                    break
        finally:
            with self._lock:
                self._running, self._stop_requested = False, False
        return report

    def _recover(self) -> None:
        with self._lock:
            self._kill()
            self._start()

    def _run_node(self, node: Node, keys: GraphKeys, report: RunReport, *, test: bool) -> bool:
        """Run one node; ``False`` when the run must end (stopped)."""
        nid = node.id
        failed_parent = next(
            (n for n in self.graph.parents(nid) if self.solver.states.get(n) in (ERROR, SKIPPED)),
            None,
        )
        if failed_parent is not None and not test:
            self._finish_error(nid, f"skipped: upstream {failed_parent} failed", SKIPPED, report)
            return True
        if not test:
            for w in self.graph.wires_into(nid):
                if self.solver.states.get(w.src) != DONE:
                    self._finish_error(
                        nid, f'input "{w.dst_port}": {w.src} has no result yet; run it first',
                        ERROR, report,
                    )  # fmt: skip
                    return True

        self.solver.states[nid] = RUNNING
        self.logs[nid] = []
        self.errors.pop(nid, None)

        if node.is_param:
            self._emit("started", nid)
            self._finish_param(node, keys, report)
            return True
        if node.parse_error is not None or node.source is None:
            self._finish_error(nid, str(node.parse_error), ERROR, report)
            return True

        inputs: dict[str, str | list[str]] = {}
        for name, upstream in keys.inputs[nid].items():
            inputs[name] = upstream if node.inputs[name].access == "list" else upstream[0]
        node_key = keys.nodes[nid]
        assert node_key is not None
        try:
            self._send(p.RunNode(nid, node.source, inputs, node_key))
            while True:
                msg = self._recv()
                if isinstance(msg, p.Started):
                    self._emit("started", nid)
                elif isinstance(msg, p.Log):
                    self.logs[nid].append(msg.line)
                    self._emit("log", nid, line=msg.line)
                elif isinstance(msg, p.Done):
                    self.summaries[nid] = {port: o["summary"] for port, o in msg.outputs.items()}
                    self.solver.states[nid] = DONE
                    self._done_ports[nid] = dict(keys.ports[nid])
                    (report.cached if msg.cached else report.ran).append(nid)
                    self._emit("done", nid, outputs=self.summaries[nid], cached=msg.cached)
                    return True
                elif isinstance(msg, p.Error):
                    self._finish_error(nid, msg.traceback, ERROR, report)
                    return True
        except _Stopped:
            self._finish_error(nid, STOPPED, ERROR, report)
            self._recover()
            return False
        except _Crashed:
            code = self._proc.exitcode if self._proc is not None else None
            self._finish_error(
                nid, f"the worker process stopped unexpectedly (exit code {code})", ERROR, report
            )
            self._recover()
            self._ensure_ready()
            # The new worker needs the parameter values again.
            for key, value in keys.values.items():
                self._send(p.PutValue(key, value))
            return True

    def _finish_param(self, node: Node, keys: GraphKeys, report: RunReport) -> None:
        nid = node.id
        if node.component in (PARAM_TEXT, PARAM_SLIDER):
            summary = types.describe(node.value)
            self.summaries[nid] = {"value": summary}
        else:
            assert node.component == PARAM_PANEL
            wires = self.graph.wires_into(nid, "data")
            upstream = (
                self.summaries.get(wires[0].src, {}).get(wires[0].src_port) if wires else None
            )
            self.summaries[nid] = {
                "data": upstream if upstream is not None else types.describe(None)
            }
        self.solver.states[nid] = DONE
        self._done_ports[nid] = dict(keys.ports[nid])
        report.ran.append(nid)
        self._emit("done", nid, outputs=self.summaries[nid], cached=False)

    def _finish_error(self, nid: str, message: str, state: str, report: RunReport) -> None:
        self.solver.states[nid] = state
        self.errors[nid] = message
        self.summaries.pop(nid, None)
        self._done_ports.pop(nid, None)
        (report.skipped if state == SKIPPED else report.failed).append(nid)
        self._emit("skipped" if state == SKIPPED else "error", nid, traceback=message)
