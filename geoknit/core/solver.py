"""Node states, out-of-date propagation and run plans (SPEC 6)."""

from __future__ import annotations

from geoknit.core.graph import Graph, GraphError

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
                affected |= self.graph.downstream(n)
        for n in affected:
            if n in self.states and self.states[n] != NEVER_RUN:
                self.states[n] = OUT_OF_DATE
        return affected

    def needs_run(self, node_id: str) -> bool:
        return self.states.get(node_id, NEVER_RUN) != DONE

    @property
    def out_of_date_count(self) -> int:
        """For the "N components out of date · Run" banner."""
        return sum(self.needs_run(n) for n in self.graph.nodes)

    def plan(self, mode: str = RUN_ALL, node_id: str | None = None) -> list[str]:
        """Node ids to execute, in topological order."""
        if mode == RUN_ALL:
            return self.graph.topological_order(n for n in self.graph.nodes if self.needs_run(n))
        if node_id is None:
            raise GraphError(f'run mode "{mode}" needs a node')
        self.graph.node(node_id)
        if mode == RUN_TO_NODE:
            wanted = {n for n in self.graph.upstream(node_id) if self.needs_run(n)}
            wanted.add(node_id)
            return self.graph.topological_order(wanted)
        if mode == RUN_TEST:
            return [node_id]
        raise GraphError(f'unknown run mode "{mode}" (use {", ".join(RUN_MODES)})')
