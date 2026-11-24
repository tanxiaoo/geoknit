"""In-process executor: runs a plan inside the current Python process.

Used by tests and by the headless path until the worker process (Phase 2)
takes over. Events mirror the worker protocol of SPEC 6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geoknit.core import types
from geoknit.core.component import run_component
from geoknit.core.graph import PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, Node
from geoknit.core.solver import DONE, ERROR, RUN_ALL, RUN_TEST, RUNNING, SKIPPED, Solver


@dataclass(frozen=True)
class Event:
    """``started``, ``log``, ``done``, ``error`` or ``skipped`` for one node."""

    kind: str
    node_id: str
    data: dict[str, Any] = field(default_factory=dict)


EventFn = Callable[[Event], None]


@dataclass
class RunReport:
    ran: list[str] = field(default_factory=list)
    cached: list[str] = field(default_factory=list)
    """Nodes whose results came from the worker's memory or the disk cache."""
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed and not self.skipped


class _MissingInput(Exception):
    pass


class InProcessExecutor:
    """Runs nodes and keeps their results in memory."""

    def __init__(
        self,
        graph: Graph,
        solver: Solver | None = None,
        *,
        base_dir: Path | None = None,
        on_event: EventFn | None = None,
    ) -> None:
        self.graph = graph
        self.solver = solver or Solver(graph)
        self.base_dir = base_dir
        self.on_event = on_event
        self.results: dict[str, dict[str, Any]] = {}
        self.summaries: dict[str, dict[str, str]] = {}
        self.logs: dict[str, list[str]] = {}
        self.errors: dict[str, str] = {}
        graph.subscribe(self._on_change)

    def _on_change(self, changed: set[str], removed: set[str]) -> None:
        for n in removed:
            for store in (self.results, self.summaries, self.logs, self.errors):
                store.pop(n, None)

    def _emit(self, kind: str, node_id: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(Event(kind, node_id, data))

    def run(self, mode: str = RUN_ALL, node_id: str | None = None) -> RunReport:
        report = RunReport()
        for nid in self.solver.plan(mode, node_id):
            self._run_node(self.graph.node(nid), report, test=mode == RUN_TEST)
        return report

    def output(self, node_id: str, port: str) -> Any:
        return self.results[node_id][port]

    # ── one node ──
    def _run_node(self, node: Node, report: RunReport, *, test: bool) -> None:
        nid = node.id
        failed_parent = next(
            (p for p in self.graph.parents(nid) if self.solver.states.get(p) in (ERROR, SKIPPED)),
            None,
        )
        if failed_parent is not None and not test:
            self._finish_error(nid, f"skipped: upstream {failed_parent} failed", SKIPPED, report)
            return

        self.solver.states[nid] = RUNNING
        self.logs[nid] = []
        self.errors.pop(nid, None)
        self._emit("started", nid)
        try:
            inputs = self._gather_inputs(node)
        except _MissingInput as exc:
            self._finish_error(nid, str(exc), ERROR, report)
            return

        if node.is_param:
            outputs = self._run_param(node, inputs)
        else:
            if node.parse_error is not None:
                self._finish_error(nid, str(node.parse_error), ERROR, report)
                return
            assert node.spec is not None
            result = run_component(
                node.spec,
                inputs,
                filename=f"<{nid} {node.spec.name}>",
                log=lambda line: self._log(nid, line),
                cwd=self.base_dir,
            )
            if not result.ok:
                assert result.error is not None
                self._finish_error(nid, result.error, ERROR, report)
                return
            outputs = result.outputs

        self.results[nid] = outputs
        self.summaries[nid] = {port: types.describe(v) for port, v in outputs.items()}
        self.solver.states[nid] = DONE
        report.ran.append(nid)
        self._emit("done", nid, outputs=self.summaries[nid])

    def _log(self, nid: str, line: str) -> None:
        self.logs[nid].append(line)
        self._emit("log", nid, line=line)

    def _finish_error(self, nid: str, message: str, state: str, report: RunReport) -> None:
        self.solver.states[nid] = state
        self.errors[nid] = message
        self.results.pop(nid, None)
        self.summaries.pop(nid, None)
        (report.skipped if state == SKIPPED else report.failed).append(nid)
        self._emit("skipped" if state == SKIPPED else "error", nid, traceback=message)

    def _gather_inputs(self, node: Node) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for name, port in node.inputs.items():
            wires = self.graph.wires_into(node.id, name)
            if not wires:
                continue
            values = []
            for w in wires:
                if w.src not in self.results or self.solver.states.get(w.src) != DONE:
                    raise _MissingInput(f'input "{name}": {w.src} has no result yet; run it first')
                values.append(types.convert_for_input(self.results[w.src][w.src_port], port.type))
            inputs[name] = values if port.access == "list" else values[0]
        return inputs

    @staticmethod
    def _run_param(node: Node, inputs: dict[str, Any]) -> dict[str, Any]:
        if node.component in (PARAM_TEXT, PARAM_SLIDER):
            return {"value": node.value}
        if node.component == PARAM_PANEL:
            return {"data": inputs.get("data")}
        raise AssertionError(node.component)  # pragma: no cover
