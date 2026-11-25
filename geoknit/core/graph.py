"""Nodes, ports and wires, with type and cycle checks (SPEC 3, 5).

The graph knows nothing about run state; it reports every change that can
affect results to its listeners (the solver), so out-of-date marking lives in
one place.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from geoknit.core import types
from geoknit.core.component import (
    ComponentLibrary,
    ComponentParseError,
    ComponentSpec,
    Port,
    parse_component,
)
from geoknit.core.settings_edit import set_ports, set_setting

PARAM_TEXT = "param/text"
PARAM_SLIDER = "param/slider"
PARAM_PANEL = "param/panel"
PARAMS = (PARAM_TEXT, PARAM_SLIDER, PARAM_PANEL)
INLINE = "inline"

_PARAM_PORTS: dict[str, tuple[dict[str, Port], dict[str, Port]]] = {
    PARAM_TEXT: ({}, {"value": Port("value", types.TEXT)}),
    PARAM_SLIDER: ({}, {"value": Port("value", types.NUMBER)}),
    PARAM_PANEL: ({"data": Port("data", types.ANY)}, {"data": Port("data", types.ANY)}),
}

DISPLAYS = ("default", "text", "icon")

ChangeListener = Callable[[set[str], set[str]], None]
"""Called with (changed node ids, removed node ids) after each mutation."""


class GraphError(ValueError):
    """A refused graph edit, with a message meant for the user."""


@dataclass
class Node:
    """One node on the canvas: a component or a Params node."""

    id: str
    component: str
    """Library reference, ``inline``, or one of ``param/text|slider|panel``."""
    position: list[float] = field(default_factory=lambda: [0, 0])
    display: str = "default"
    source: str | None = None
    """Full component file text (settings baked in); ``None`` for Params."""
    version: str | None = None
    based_on: str | None = None
    library_source: str | None = None
    """Source of the library component this node came from, to detect edits."""
    value: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    """Unknown keys from the workflow file, written back unchanged."""
    spec: ComponentSpec | None = None
    """Last successfully parsed spec (kept when the current source is broken)."""
    parse_error: ComponentParseError | None = None

    @property
    def is_param(self) -> bool:
        return self.component in PARAMS

    @property
    def inputs(self) -> dict[str, Port]:
        if self.is_param:
            return _PARAM_PORTS[self.component][0]
        return self.spec.inputs if self.spec else {}

    @property
    def outputs(self) -> dict[str, Port]:
        if self.is_param:
            return _PARAM_PORTS[self.component][1]
        return self.spec.outputs if self.spec else {}

    @property
    def title(self) -> str:
        if self.spec is not None:
            return self.spec.name
        return {PARAM_TEXT: "Text", PARAM_SLIDER: "Number Slider", PARAM_PANEL: "Panel"}.get(
            self.component, self.component
        )

    def set_source(self, source: str) -> None:
        """Replace the source; on a parse error keep the last good ports."""
        self.source = source
        try:
            self.spec = parse_component(source)
            self.parse_error = None
        except ComponentParseError as exc:
            self.parse_error = exc


@dataclass(frozen=True)
class Wire:
    """A connection from an output port to an input port."""

    src: str
    src_port: str
    dst: str
    dst_port: str

    def __str__(self) -> str:
        return f"{self.src}.{self.src_port} → {self.dst}.{self.dst_port}"


class Graph:
    """The workflow: nodes, wires, and the canvas-only data (groups, view)."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.wires: list[Wire] = []
        self.groups: list[dict[str, Any]] = []
        self.view: dict[str, Any] = {}
        self._listeners: list[ChangeListener] = []

    # ── listeners ──
    def subscribe(self, listener: ChangeListener) -> None:
        self._listeners.append(listener)

    def _changed(self, changed: Iterable[str] = (), removed: Iterable[str] = ()) -> None:
        c, r = set(changed), set(removed)
        for listener in self._listeners:
            listener(c, r)

    # ── nodes ──
    def new_id(self) -> str:
        used = [int(m.group(1)) for k in self.nodes if (m := re.fullmatch(r"n(\d+)", k))]
        return f"n{max(used, default=0) + 1}"

    def node(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise GraphError(f'no node "{node_id}"') from None

    def add_node(self, node: Node) -> Node:
        """Add a fully built node (used by the workflow loader)."""
        if node.id in self.nodes:
            raise GraphError(f'a node "{node.id}" already exists')
        if node.display not in DISPLAYS:
            raise GraphError(f"display must be one of {', '.join(DISPLAYS)}")
        if not node.is_param and node.source is None:
            raise GraphError(f'node "{node.id}" has no source')
        if not node.is_param and node.spec is None and node.parse_error is None:
            node.set_source(node.source or "")
        if node.spec is None and not node.is_param:
            raise GraphError(f'node "{node.id}": {node.parse_error}')
        self.nodes[node.id] = node
        self._changed(changed=[node.id])
        return node

    def add_component(
        self,
        component: str,
        library: ComponentLibrary | None = None,
        *,
        position: Iterable[float] = (0, 0),
        source: str | None = None,
        node_id: str | None = None,
    ) -> Node:
        """Add a library component, an inline component (``source``) or a Params node."""
        node = Node(id=node_id or self.new_id(), component=component, position=list(position))
        if component == PARAM_TEXT:
            node.value = ""
        elif component == PARAM_SLIDER:
            node.min, node.max, node.step, node.value = 0, 100, 1, 50
        elif component == PARAM_PANEL:
            pass
        elif component == INLINE:
            if source is None:
                raise GraphError("an inline component needs its source")
            node.set_source(source)
        else:
            if library is None:
                raise GraphError(f'cannot resolve "{component}" without a component library')
            try:
                entry = library.get(component)
            except KeyError as exc:
                raise GraphError(str(exc.args[0])) from None
            node.version = entry.version
            node.library_source = entry.source
            node.set_source(entry.source)
        if node.parse_error is not None:
            raise GraphError(f"{component}: {node.parse_error}")
        return self.add_node(node)

    def remove_node(self, node_id: str) -> None:
        self.node(node_id)
        children = {w.dst for w in self.wires if w.src == node_id}
        self.wires = [w for w in self.wires if node_id not in (w.src, w.dst)]
        del self.nodes[node_id]
        for g in self.groups:
            if node_id in g.get("nodes", []):
                g["nodes"] = [n for n in g["nodes"] if n != node_id]
        self.groups = [g for g in self.groups if g.get("nodes")]  # an empty group is gone
        self._changed(changed=children - {node_id}, removed=[node_id])

    # ── edits that change results ──
    def set_setting(self, node_id: str, name: str, value: Any) -> None:
        node = self.node(node_id)
        if node.is_param or node.source is None:
            raise GraphError(f"{node.title} has no settings")
        if node.parse_error is not None:
            raise GraphError(f"fix the code first: {node.parse_error}")
        try:
            new_source = set_setting(node.source, name, value)
        except (KeyError, ValueError) as exc:
            raise GraphError(str(exc.args[0])) from None
        node.set_source(new_source)
        self._changed(changed=[node_id])

    def set_source(self, node_id: str, source: str) -> None:
        node = self.node(node_id)
        if node.is_param:
            raise GraphError(f"{node.title} has no code")
        old_inputs, old_outputs = dict(node.inputs), dict(node.outputs)
        node.set_source(source)
        if node.parse_error is None:
            self._drop_broken_wires(node_id, old_inputs, old_outputs)
        self._changed(changed=[node_id])

    def set_ports(
        self,
        node_id: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
    ) -> None:
        """Rewrite the node's declared ports (Python component window, SPEC 4).

        A port dict may carry ``was``: its old name. Wires on a renamed port
        follow it; wires on removed ports, or ports whose type no longer fits,
        are dropped.
        """
        node = self.node(node_id)
        if node.is_param or node.source is None:
            raise GraphError(f"{node.title} has no ports to edit")
        if node.parse_error is not None:
            raise GraphError(f"fix the code first: {node.parse_error}")
        try:
            new_source = set_ports(node.source, inputs, outputs)
        except ValueError as exc:
            raise GraphError(str(exc)) from None
        renamed_in = {str(p["was"]): str(p["name"]) for p in inputs if p.get("was")}
        renamed_out = {str(p["was"]): str(p["name"]) for p in outputs if p.get("was")}
        old_inputs, old_outputs = dict(node.inputs), dict(node.outputs)
        node.set_source(new_source)
        rewired: list[Wire] = []
        for w in self.wires:
            if w.dst == node_id and w.dst_port in renamed_in:
                w = Wire(w.src, w.src_port, w.dst, renamed_in[w.dst_port])
            elif w.src == node_id and w.src_port in renamed_out:
                w = Wire(w.src, renamed_out[w.src_port], w.dst, w.dst_port)
            rewired.append(w)
        self.wires = rewired
        old_inputs = {renamed_in.get(k, k): v for k, v in old_inputs.items()}
        old_outputs = {renamed_out.get(k, k): v for k, v in old_outputs.items()}
        self._drop_broken_wires(node_id, old_inputs, old_outputs)
        self._changed(changed=[node_id])

    def set_value(self, node_id: str, value: Any) -> None:
        node = self.node(node_id)
        if node.component == PARAM_TEXT:
            if not isinstance(value, str):
                raise GraphError("a Text value must be text")
        elif node.component == PARAM_SLIDER:
            if types.type_of(value) != types.NUMBER:
                raise GraphError("a slider value must be a number")
            assert node.min is not None and node.max is not None
            if not node.min <= value <= node.max:
                raise GraphError(f"value {value} is outside {node.min}..{node.max}")
        else:
            raise GraphError(f"{node.title} has no value")
        node.value = value
        self._changed(changed=[node_id])

    def set_slider(
        self,
        node_id: str,
        *,
        min: float | None = None,
        max: float | None = None,
        step: float | None = None,
        value: float | None = None,
    ) -> None:
        node = self.node(node_id)
        if node.component != PARAM_SLIDER:
            raise GraphError(f"{node.title} is not a slider")
        lo = node.min if min is None else min
        hi = node.max if max is None else max
        st = node.step if step is None else step
        val = node.value if value is None else value
        assert lo is not None and hi is not None and st is not None
        if not lo < hi:
            raise GraphError("slider min must be below max")
        if st <= 0:
            raise GraphError("slider step must be positive")
        val = _clamp(val, lo, hi)
        changed = val != node.value
        node.min, node.max, node.step, node.value = lo, hi, st, val
        if changed:
            self._changed(changed=[node_id])

    # ── edits that do not change results ──
    def set_position(self, node_id: str, position: Iterable[float]) -> None:
        self.node(node_id).position = list(position)

    def set_display(self, node_id: str, display: str) -> None:
        if display not in DISPLAYS:
            raise GraphError(f"display must be one of {', '.join(DISPLAYS)}")
        self.node(node_id).display = display

    # ── wires ──
    def add_wire(self, src: str, src_port: str, dst: str, dst_port: str) -> Wire:
        """Connect ``src.src_port`` → ``dst.dst_port``, refusing bad wires."""
        a, b = self.node(src), self.node(dst)
        out = a.outputs.get(src_port)
        if out is None:
            raise GraphError(f'{a.title} has no output "{src_port}"')
        inp = b.inputs.get(dst_port)
        if inp is None:
            raise GraphError(f'{b.title} has no input "{dst_port}"')
        problem = types.connection_error(out.type, inp.type)
        if problem:
            raise GraphError(problem)
        wire = Wire(src, src_port, dst, dst_port)
        if wire in self.wires:
            raise GraphError("these ports are already connected")
        if inp.access == "item" and self.wires_into(dst, dst_port):
            raise GraphError(f'input "{dst_port}" of {b.title} is already connected')
        if src == dst or src in self.downstream(dst):
            raise GraphError(f"connecting {a.title} → {b.title} would create a cycle")
        self.wires.append(wire)
        self._changed(changed=[dst])
        return wire

    def remove_wire(self, src: str, src_port: str, dst: str, dst_port: str) -> None:
        wire = Wire(src, src_port, dst, dst_port)
        if wire not in self.wires:
            raise GraphError(f"no wire {wire}")
        self.wires.remove(wire)
        self._changed(changed=[dst])

    def wires_into(self, node_id: str, port: str | None = None) -> list[Wire]:
        return [w for w in self.wires if w.dst == node_id and (port is None or w.dst_port == port)]

    def _drop_broken_wires(
        self, node_id: str, old_inputs: dict[str, Port], old_outputs: dict[str, Port]
    ) -> None:
        """After a code change, remove wires whose ports vanished or changed type."""
        node = self.nodes[node_id]
        keep: list[Wire] = []
        affected: set[str] = set()
        for w in self.wires:
            if w.dst == node_id:
                p = node.inputs.get(w.dst_port)
                src_type = self.nodes[w.src].outputs[w.src_port].type
                ok = p is not None and types.can_connect(src_type, p.type)
            elif w.src == node_id:
                p = node.outputs.get(w.src_port)
                dst_type = self.nodes[w.dst].inputs[w.dst_port].type
                ok = p is not None and types.can_connect(p.type, dst_type)
                if not ok:
                    affected.add(w.dst)
            else:
                ok = True
            if ok:
                keep.append(w)
        self.wires = keep
        if affected:
            self._changed(changed=affected)

    # ── structure ──
    def parents(self, node_id: str) -> list[str]:
        return list(dict.fromkeys(w.src for w in self.wires if w.dst == node_id))

    def children(self, node_id: str) -> list[str]:
        return list(dict.fromkeys(w.dst for w in self.wires if w.src == node_id))

    def downstream(self, node_id: str) -> set[str]:
        """All nodes reachable from ``node_id`` (not including it)."""
        return self._reach(node_id, self.children)

    def upstream(self, node_id: str) -> set[str]:
        """All nodes ``node_id`` depends on (not including it)."""
        return self._reach(node_id, self.parents)

    @staticmethod
    def _reach(start: str, step: Callable[[str], list[str]]) -> set[str]:
        seen: set[str] = set()
        todo = step(start)
        while todo:
            n = todo.pop()
            if n not in seen:
                seen.add(n)
                todo.extend(step(n))
        return seen

    def topological_order(self, subset: Iterable[str] | None = None) -> list[str]:
        """Nodes in dependency order; ties keep insertion order."""
        chosen = None if subset is None else set(subset)
        wanted = [n for n in self.nodes if chosen is None or n in chosen]
        wanted_set = set(wanted)
        indegree = {n: 0 for n in wanted}
        for src, dst in {(w.src, w.dst) for w in self.wires}:
            if src in wanted_set and dst in wanted_set:
                indegree[dst] += 1
        order: list[str] = []
        ready = [n for n in wanted if indegree[n] == 0]
        while ready:
            n = ready.pop(0)
            order.append(n)
            for c in self.children(n):
                if c in wanted_set:
                    indegree[c] -= 1
                    if indegree[c] == 0:
                        ready.append(c)
            ready.sort(key=wanted.index)
        if len(order) != len(wanted):  # pragma: no cover  (cycles are refused on wiring)
            raise GraphError("the graph has a cycle")
        return order


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value
