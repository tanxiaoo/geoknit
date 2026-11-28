"""Node states, out-of-date propagation and run plans (SPEC 6).

View nodes (Map Layer, Map Viewer; change 03, section 4) are never run: their
state follows their sources (``view_state``), they are left out of run plans
and of the out-of-date count. Out-of-date does not travel along wires into a
Map Layer's style inputs (``Graph.carries``).
"""

from __future__ import annotations

from geoknit.core.graph import PARAM_LAYER, PARAM_MAP, Graph, GraphError

NEVER_RUN = "never_run"
OUT_OF_DATE = "out_of_date"
RUNNING = "running"
DONE = "done"
ERROR = "error"
SKIPPED = "skipped"
STATES = (NEVER_RUN, OUT_OF_DATE, RUNNING, DONE, ERROR, SKIPPED)

RUN_ALL = "all"
RUN_TO_NODE = "to_node"
RUN_TEST = "test"
RUN_MODES = (RUN_ALL, RUN_TO_NODE, RUN_TEST)


class Solver:
    """Tracks the state of every node and decides what a run must execute."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph
        self.states: dict[str, str] = {n: NEVER_RUN for n in graph.nodes}
        graph.subscribe(self._on_change)
        self.refresh_views()

    def _on_change(self, changed: set[str], removed: set[str]) -> None:
        for n in removed:
            self.states.pop(n, None)
        for n in changed:
            self.states.setdefault(n, NEVER_RUN)
        self.invalidate(changed)

    def invalidate(self, node_ids: set[str]) -> set[str]:
        """Mark ``node_ids`` and everything downstream out of date; return them."""
        affected = set(node_ids)
        for n in node_ids:
            if n in self.graph.nodes:
                affected |= self.downstream(n)
        for n in affected:
            if n in self.states and self.states[n] != NEVER_RUN and not self._is_view(n):
                self.states[n] = OUT_OF_DATE
        self.refresh_views()
        return affected

    def downstream(self, node_id: str) -> set[str]:
        """Nodes a change of ``node_id`` makes out of date: ``Graph.downstream`` without
        crossing a wire into a Map Layer's style inputs."""
        seen: set[str] = set()
        todo = [node_id]
        while todo:
            n = todo.pop()
            for w in self.graph.wires:
                if w.src == n and w.dst not in seen and self.graph.carries(w):
                    seen.add(w.dst)
                    todo.append(w.dst)
        seen.discard(node_id)
        return seen

    def _is_view(self, node_id: str) -> bool:
        node = self.graph.nodes.get(node_id)
        return node is not None and node.is_view

    def view_sources(self, node_id: str) -> list[str]:
        """The nodes a view node shows: a Map Layer's ``data``, a Map Viewer's layers."""
        node = self.graph.node(node_id)
        port = "data" if node.component == PARAM_LAYER else None
        return list(dict.fromkeys(w.src for w in self.graph.wires_into(node_id, port)))

    def view_state(self, node_id: str) -> str:
        """A Map Viewer is always ``done``: it draws whichever layers work (decided
        28 Nov 2026). A Map Layer follows its data: ``done`` when it is; ``skipped``
        when it failed; ``never_run`` without data or before a run; otherwise
        ``out_of_date``."""
        if self.graph.node(node_id).component == PARAM_MAP:
            return DONE
        found = [self.states.get(s, NEVER_RUN) for s in self.view_sources(node_id)]
        if not found:
            return NEVER_RUN
        if any(s in (ERROR, SKIPPED) for s in found):
            return SKIPPED
        if NEVER_RUN in found:
            return NEVER_RUN
        return DONE if all(s == DONE for s in found) else OUT_OF_DATE

    def refresh_views(self) -> None:
        """Set every view node's state from its sources (after any state change)."""
        for n in self.graph.topological_order(n for n, v in self.graph.nodes.items() if v.is_view):
            self.states[n] = self.view_state(n)

    def needs_run(self, node_id: str) -> bool:
        if self._is_view(node_id):
            return False
        return self.states.get(node_id, NEVER_RUN) != DONE

    @property
    def out_of_date_count(self) -> int:
        """For the "N components out of date · Run" banner: components only, so
        Params nodes (inputs, Panels, view nodes) never count (decided 28 Nov 2026)."""
        return sum(self.needs_run(n) and not v.is_param for n, v in self.graph.nodes.items())

    def _order(self, wanted: set[str]) -> list[str]:
        """``wanted`` in topological order. View nodes are left out of plans, so with
        any in the graph the order comes from the whole graph: a Panel on a Map Layer
        then still runs after a component that styles the layer."""
        if not any(node.is_view for node in self.graph.nodes.values()):
            return self.graph.topological_order(wanted)
        return [n for n in self.graph.topological_order() if n in wanted]

    def plan(self, mode: str = RUN_ALL, node_id: str | None = None) -> list[str]:
        """Node ids to execute, in topological order."""
        if mode == RUN_ALL:
            return self._order({n for n in self.graph.nodes if self.needs_run(n)})
        if node_id is None:
            raise GraphError(f'run mode "{mode}" needs a node')
        self.graph.node(node_id)
        if mode == RUN_TO_NODE:
            wanted = {n for n in self.graph.upstream(node_id) if self.needs_run(n)}
            if not self._is_view(node_id):
                wanted.add(node_id)
            return self._order(wanted)
        if mode == RUN_TEST:
            return [] if self._is_view(node_id) else [node_id]
        raise GraphError(f'unknown run mode "{mode}" (use {", ".join(RUN_MODES)})')
