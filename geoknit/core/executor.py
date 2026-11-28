"""In-process executor: runs a plan inside the current Python process.

Used by tests and by the headless path until the worker process (Phase 2)
takes over. Events mirror the worker protocol of SPEC 6.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geoknit.core import types, views
from geoknit.core.cache import compute_keys
from geoknit.core.component import PRINT_PORT, run_component
from geoknit.core.graph import (
    PARAM_LAYER,
    PARAM_MAP,
    PARAM_PANEL,
    VALUE_PARAMS,
    Graph,
    Node,
    param_output,
)
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
        self.views: dict[str, dict[str, dict[str, Any]]] = {}
        """Panel view of each output, per node (change 01, section 11)."""
        self.logs: dict[str, list[str]] = {}
        self.errors: dict[str, str] = {}
        graph.subscribe(self._on_change)

    def _on_change(self, changed: set[str], removed: set[str]) -> None:
        for n in removed:
            for store in (self.results, self.summaries, self.views, self.logs, self.errors):
                store.pop(n, None)

    def _emit(self, kind: str, node_id: str, **data: Any) -> None:
        if self.on_event is not None:
            self.on_event(Event(kind, node_id, data))

    def run(self, mode: str = RUN_ALL, node_id: str | None = None) -> RunReport:
        report = RunReport()
        self.refresh_views()
        for nid in self.solver.plan(mode, node_id):
            self._run_node(self.graph.node(nid), report, test=mode == RUN_TEST)
            self.refresh_views()
        return report

    def output(self, node_id: str, port: str) -> Any:
        return self.results[node_id][port]

    # ── view nodes (change 03, section 4) ──
    def refresh_views(self) -> None:
        """States of the view nodes, and each done Map Layer's layer as its result."""
        self.solver.refresh_views()
        layers = [n for n, v in self.graph.nodes.items() if v.component == PARAM_LAYER]
        if not layers:
            return
        keys = compute_keys(self.graph, self.base_dir, self)
        for nid in layers:
            layer = keys.layers[nid].layer
            if self.solver.states.get(nid) == DONE and layer is not None:
                self.results[nid] = {"layer": layer}
                summary = types.describe(layer)
                self.summaries[nid] = {"layer": summary}
                self.views[nid] = {"layer": views.safe_view(layer, summary)}
            else:
                for store in (self.results, self.summaries, self.views):
                    store.pop(nid, None)

    def value(self, node_id: str, port: str) -> Any:
        """``DoneResults``: a done node's output held in memory."""
        if self.solver.states.get(node_id) != DONE or node_id not in self.results:
            raise LookupError(f"{self.graph.node(node_id).title} has no result yet; run it")
        return self.results[node_id][port]

    def data_type(self, node_id: str, port: str) -> str | None:
        try:
            return types.type_of(self.value(node_id, port))
        except LookupError:
            return None

    def band_names(self, node_id: str, port: str) -> list[str] | None:
        try:
            value = self.value(node_id, port)
        except LookupError:
            return None
        return types.raster_band_names(value) if types.type_of(value) == types.RASTER else None

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
                print_port=PRINT_PORT,
                output_types=self.graph.resolved_output_types(nid),
                list_outputs=self.graph.list_outputs(nid),
            )
            if not result.ok:
                assert result.error is not None
                self._finish_error(nid, result.error, ERROR, report)
                return
            outputs = result.outputs

        self.results[nid] = outputs
        self.summaries[nid] = {port: types.describe(v) for port, v in outputs.items()}
        # Params nodes (also a Panel passing its input through) get theirs here too.
        self.views[nid] = {
            port: views.safe_view(v, self.summaries[nid][port]) for port, v in outputs.items()
        }
        self.solver.states[nid] = DONE
        report.ran.append(nid)
        self._emit("done", nid, outputs=self.summaries[nid], views=self.views[nid])

    def _log(self, nid: str, line: str) -> None:
        self.logs[nid].append(line)
        self._emit("log", nid, line=line)

    def _finish_error(self, nid: str, message: str, state: str, report: RunReport) -> None:
        self.solver.states[nid] = state
        self.errors[nid] = message
        self.results.pop(nid, None)
        self.summaries.pop(nid, None)
        self.views.pop(nid, None)
        (report.skipped if state == SKIPPED else report.failed).append(nid)
        self._emit("skipped" if state == SKIPPED else "error", nid, traceback=message)

    def _gather_inputs(self, node: Node) -> dict[str, Any]:
        inputs: dict[str, Any] = {}
        for name, port in node.inputs.items():
            wires = self.graph.wires_into(node.id, name)
            if not wires:
                continue
            values: list[Any] = []
            for w in wires:
                if w.src not in self.results or self.solver.states.get(w.src) != DONE:
                    raise _MissingInput(f'input "{name}": {w.src} has no result yet; run it first')
                value = self.results[w.src][w.src_port]
                if port.access == "list" and self.graph.output_is_list(w.src, w.src_port):
                    # A list wire adds all its elements (decided by the port, SPEC 3).
                    values.extend(types.convert_for_input(v, port.types) for v in value)
                else:
                    values.append(types.convert_for_input(value, port.types))
            inputs[name] = values if port.access == "list" else values[0]
        return inputs

    @staticmethod
    def _run_param(node: Node, inputs: dict[str, Any]) -> dict[str, Any]:
        if node.component in VALUE_PARAMS:
            return {"value": param_output(node)}
        if node.component == PARAM_PANEL:
            return {"data": inputs.get("data")}
        if node.component == PARAM_MAP:
            return {}
        raise AssertionError(node.component)  # pragma: no cover
