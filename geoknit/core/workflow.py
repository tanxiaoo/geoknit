"""Save and load ``.geoknit`` workflow files (SPEC 5).

JSON, UTF-8, sorted keys, 2-space indent. Unmodified library components are
stored by reference plus their settings; anything whose code differs from the
library is stored inline with ``based_on``. Saving the result of a load gives
back the same bytes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from geoknit import __version__
from geoknit.core.component import ComponentLibrary, ComponentParseError, find_blocks
from geoknit.core.graph import (
    INLINE,
    PARAM_MAP,
    PARAM_PANEL,
    PARAM_SLIDER,
    PARAM_TEXT,
    PARAMS,
    Graph,
    GraphError,
    Node,
    Wire,
)
from geoknit.core.settings_edit import set_settings

FORMAT = 1
"""Current workflow file format. Bump on breaking changes and add a migration."""

MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}
"""``MIGRATIONS[n]`` upgrades a format ``n`` document to format ``n + 1``."""

_NODE_KEYS = {
    "id", "component", "version", "settings", "source", "based_on", "position", "display",
    "value", "min", "max", "step",
}  # fmt: skip


class WorkflowError(ValueError):
    """A workflow file that cannot be loaded."""


# ── helpers ──


def code_signature(source: str) -> str:
    """The file without its settings block: what "modified" is judged on."""
    lines = source.splitlines(keepends=True)
    try:
        blocks = find_blocks(source)
    except ComponentParseError:
        return source
    if blocks.settings_start is None:
        return source
    return "".join(lines[: blocks.settings_start] + lines[blocks.code_start - 1 :])


def is_modified(node: Node) -> bool:
    """True when the code outside the settings block differs from the library.

    An inline node ``based_on`` a component the library no longer has counts
    as modified: it was stored inline because it had been edited.
    """
    if node.source is None:
        return False
    if node.library_source is None:
        return node.component == INLINE and node.based_on is not None
    return code_signature(node.source) != code_signature(node.library_source)


def relativize(value: str, base_dir: Path | None) -> str:
    """An absolute path inside ``base_dir`` becomes relative with ``/`` separators."""
    if base_dir is None or not value:
        return value
    try:
        p = Path(value)
        if not p.is_absolute():
            return value
        rel = p.resolve().relative_to(base_dir.resolve())
    except (ValueError, OSError):
        return value
    return PurePosixPath(*rel.parts).as_posix()


def dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# ── graph → dict ──


def graph_to_dict(graph: Graph, base_dir: Path | None = None) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "geoknit_version": __version__,
        "nodes": [node_to_dict(n, base_dir) for n in graph.nodes.values()],
        "wires": [{"from": [w.src, w.src_port], "to": [w.dst, w.dst_port]} for w in graph.wires],
        "groups": graph.groups,
        "view": graph.view,
    }


def node_to_dict(node: Node, base_dir: Path | None = None) -> dict[str, Any]:
    d: dict[str, Any] = dict(node.extra)
    d.update(id=node.id, component=node.component, position=node.position)
    if node.component == PARAM_TEXT:
        d["value"] = relativize(node.value, base_dir)
    elif node.component == PARAM_SLIDER:
        d.update(min=node.min, max=node.max, step=node.step, value=node.value)
    elif node.component in (PARAM_PANEL, PARAM_MAP):
        pass  # layout and map styles live in ``extra``
    elif node.component == INLINE or is_modified(node) or node.parse_error is not None:
        d["component"] = INLINE
        d["source"] = node.source
        based_on = node.based_on
        if based_on is None and node.component != INLINE:
            based_on = f"{node.component}@{node.version}"
        if based_on is not None:
            d["based_on"] = based_on
    else:
        assert node.spec is not None
        d["version"] = node.version
        d["settings"] = node.spec.settings_values
    if not node.is_param:
        d["display"] = node.display
    elif node.display != "default":
        d["display"] = node.display
    return d


# ── dict → graph ──


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    fmt = data.get("format")
    if not isinstance(fmt, int):
        raise WorkflowError('not a GeoKnit workflow: missing "format"')
    if fmt > FORMAT:
        raise WorkflowError(
            f"this workflow uses format {fmt}, newer than this GeoKnit supports ({FORMAT}); "
            "please update GeoKnit"
        )
    while fmt < FORMAT:
        if fmt not in MIGRATIONS:
            raise WorkflowError(f"no migration from workflow format {fmt}")
        data = MIGRATIONS[fmt](data)
        fmt += 1
        data["format"] = fmt
    return data


def graph_from_dict(data: dict[str, Any], library: ComponentLibrary | None = None) -> Graph:
    data = migrate(dict(data))
    graph = Graph()
    for raw in data.get("nodes", []):
        try:
            graph.add_node(node_from_dict(raw, library))
        except GraphError as exc:
            raise WorkflowError(str(exc)) from None
    # Types are checked once every wire is in: a wire leaving a ``like:`` output
    # can come before the wire that resolves it (SPEC 4).
    with graph.deferred_checks():
        for raw in data.get("wires", []):
            try:
                (src, src_port), (dst, dst_port) = raw["from"], raw["to"]
                graph.add_wire(src, src_port, dst, dst_port)
            except (KeyError, TypeError, ValueError) as exc:
                raise WorkflowError(f"bad wire {raw}: {exc}") from None
        bad = graph.bad_wires()
        if bad:
            wire, problem = bad[0]
            raise WorkflowError(f"bad wire {wire}: {problem}")
    graph.groups = list(data.get("groups", []))
    graph.view = dict(data.get("view", {}))
    return graph


def node_from_dict(raw: dict[str, Any], library: ComponentLibrary | None = None) -> Node:
    try:
        node = Node(id=str(raw["id"]), component=str(raw["component"]))
    except KeyError as exc:
        raise WorkflowError(f"node without {exc.args[0]}: {raw}") from None
    node.position = list(raw.get("position", [0, 0]))
    node.display = raw.get("display", "default")
    node.extra = {k: v for k, v in raw.items() if k not in _NODE_KEYS}

    if node.component in PARAMS:
        if node.component == PARAM_TEXT:
            node.value = raw.get("value", "")
        elif node.component == PARAM_SLIDER:
            node.min, node.max = raw.get("min", 0), raw.get("max", 100)
            node.step, node.value = raw.get("step", 1), raw.get("value", 50)
        return node

    if node.component == INLINE:
        if "source" not in raw:
            raise WorkflowError(f'inline node "{node.id}" has no source')
        node.based_on = raw.get("based_on")
        node.set_source(raw["source"])
        node.library_source = _based_on_source(node.based_on, library)
        return node

    if library is None:
        raise WorkflowError(f'node "{node.id}" uses "{node.component}" but no library was given')
    try:
        entry = library.get(node.component)
    except KeyError as exc:
        raise WorkflowError(f'node "{node.id}": {exc.args[0]}') from None
    node.version = raw.get("version", entry.version)
    node.library_source = entry.source
    node.set_source(entry.source)
    if node.spec is None:
        raise WorkflowError(f'library component "{node.component}": {node.parse_error}')
    current = node.spec.settings_values
    wanted = {
        k: v
        for k, v in (raw.get("settings") or {}).items()
        if k in current and _normalize(v) != _normalize(current[k])
    }
    if wanted:
        node.set_source(set_settings(entry.source, wanted))
    return node


def _based_on_source(based_on: str | None, library: ComponentLibrary | None) -> str | None:
    """Library source of ``ref@version``, to judge "modified" (``None`` if unknown)."""
    if not based_on or library is None:
        return None
    try:
        return library.get(based_on.rsplit("@", 1)[0]).source
    except KeyError:
        return None


# ── change a live graph to match a document ──

LAYOUT_KEYS = ("position", "display", "size")
"""Node keys that never change results."""


def _content(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in LAYOUT_KEYS}


def apply_dict(
    graph: Graph,
    data: dict[str, Any],
    library: ComponentLibrary | None = None,
    *,
    view: bool = False,
) -> None:
    """Change ``graph`` in place to match the workflow document ``data``.

    Undo, redo and autosave recovery use this instead of building a new
    graph, so only the nodes that really differ (and their downstream nodes)
    go out of date. Layout-only differences never invalidate anything.
    ``view`` also copies the canvas view.
    """
    data = migrate(dict(data))
    target: dict[str, dict[str, Any]] = {}
    for raw in data.get("nodes", []):
        target[str(raw["id"])] = raw
    try:
        wanted = [
            Wire(str(w["from"][0]), str(w["from"][1]), str(w["to"][0]), str(w["to"][1]))
            for w in data.get("wires", [])
        ]
    except (KeyError, IndexError, TypeError) as exc:
        raise WorkflowError(f"bad wire in workflow: {exc}") from None
    # Wire types are checked once the graph matches the document (SPEC 4: a wire
    # leaving a ``like:`` output can come before the wire that resolves it).
    with graph.deferred_checks():
        try:
            for w in [w for w in graph.wires if w not in wanted]:
                graph.remove_wire(w.src, w.src_port, w.dst, w.dst_port)
            for nid in [n for n in graph.nodes if n not in target]:
                graph.remove_node(nid)
            for nid, raw in target.items():
                new = node_from_dict(raw, library)
                old = graph.nodes.get(nid)
                if old is None:
                    graph.add_node(new)
                elif _content(node_to_dict(old)) != _content(node_to_dict(new)):
                    _update_node(graph, old, new)
                old = graph.nodes[nid]
                old.position, old.display, old.extra = list(new.position), new.display, new.extra
            for w in wanted:
                if w not in graph.wires:
                    graph.add_wire(w.src, w.src_port, w.dst, w.dst_port)
        except GraphError as exc:
            raise WorkflowError(str(exc)) from None
        # same order as the document, so saving gives the same bytes
        ordered = {nid: graph.nodes[nid] for nid in target}
        graph.nodes.clear()
        graph.nodes.update(ordered)
        graph.wires[:] = wanted
    graph.groups = json.loads(json.dumps(data.get("groups", [])))
    if view:
        graph.view = dict(data.get("view", {}))


def _update_node(graph: Graph, old: Node, new: Node) -> None:
    """Change ``old`` to ``new``'s content with the graph's own edits."""
    if old.component == new.component == PARAM_TEXT:
        graph.set_value(old.id, new.value)
    elif old.component == new.component == PARAM_SLIDER:
        graph.set_slider(old.id, min=new.min, max=new.max, step=new.step, value=new.value)
    elif old.component == new.component and old.component in (PARAM_PANEL, PARAM_MAP):
        pass  # no content beyond layout and map styles (``extra``)
    elif old.component == new.component and not old.is_param:
        old.version, old.based_on = new.version, new.based_on
        graph.set_source(old.id, new.source or "")
    else:  # a different kind of node under the same id
        graph.remove_node(old.id)
        graph.add_node(new)


def _normalize(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


# ── files ──


def save_workflow(graph: Graph, path: Path) -> None:
    path = Path(path)
    text = dumps(graph_to_dict(graph, base_dir=path.parent))
    path.write_text(text, encoding="utf-8", newline="\n")


def load_workflow(path: Path, library: ComponentLibrary | None = None) -> Graph:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{path.name} is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise WorkflowError(f"{path.name} is not a GeoKnit workflow")
    return graph_from_dict(data, library)
