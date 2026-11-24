"""Cache keys and the disk cache (SPEC 6 "Cache").

Keys depend only on the graph and on the files it refers to, so every node can
be keyed in topological order without running anything:

- component node: ``sha256`` of the cache format, the component source (which
  already holds its settings), the upstream port keys of each input (ports
  sorted by name, wires in wire order), and a fingerprint of every file named
  by a text setting;
- ``param/text``: its value plus the fingerprint of the file it names, if any;
- ``param/slider``: its value;
- ``param/panel``: no key of its own; its ``data`` output reuses the key of the
  wire feeding it.

A port key is ``<node key>.<port>``. A file fingerprint is the absolute path
(``/`` separators), size and modification time of a text value that resolves
to an existing file relative to the project folder.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geoknit.core.graph import PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, Node

CACHE_FORMAT = 1
"""Bump when the key recipe or the disk layout changes; old entries then miss."""

EMPTY_KEY = hashlib.sha256(b"geoknit:empty").hexdigest()
"""Port key of an unconnected Panel's output (value ``None``)."""


def _sha(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def port_key(node_key: str, port: str) -> str:
    return f"{node_key}.{port}"


def file_fingerprint(value: str, base_dir: Path | None) -> list[Any] | None:
    """``[path, size, mtime_ns]`` if ``value`` names an existing file, else ``None``."""
    if not value or "\n" in value or len(value) > 1024:
        return None
    try:
        p = Path(value)
        if not p.is_absolute():
            if base_dir is None:
                return None
            p = base_dir / p
        if not p.is_file():
            return None
        st = p.stat()
        return [p.resolve().as_posix(), st.st_size, st.st_mtime_ns]
    except (OSError, ValueError):
        return None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [v for v in value if isinstance(v, str)]
    return []


def node_files(node: Node, base_dir: Path | None) -> list[list[Any]]:
    """Fingerprints of the files named by a node's text value or text settings."""
    texts: list[str] = []
    if node.component == PARAM_TEXT:
        texts = _strings(node.value)
    elif node.spec is not None and not node.is_param:
        for s in node.spec.settings.values():
            texts.extend(_strings(s.value))
    found = (file_fingerprint(t, base_dir) for t in texts)
    return [f for f in found if f is not None]


@dataclass
class GraphKeys:
    """Cache keys for every node and output port of a graph."""

    nodes: dict[str, str | None] = field(default_factory=dict)
    """Node key, or ``None`` for a Panel (it has no work of its own)."""
    ports: dict[str, dict[str, str]] = field(default_factory=dict)
    inputs: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    """Upstream port keys feeding each input, in wire order."""
    values: dict[str, Any] = field(default_factory=dict)
    """Port key → value for Text, Slider and empty Panel outputs."""


def compute_keys(graph: Graph, base_dir: Path | None = None) -> GraphKeys:
    """Key every node of ``graph`` in topological order."""
    keys = GraphKeys()
    for nid in graph.topological_order():
        node = graph.nodes[nid]
        inputs: dict[str, list[str]] = {}
        for name in sorted(node.inputs):
            wires = graph.wires_into(nid, name)
            if wires:
                inputs[name] = [keys.ports[w.src][w.src_port] for w in wires]
        keys.inputs[nid] = inputs

        if node.component == PARAM_PANEL:
            keys.nodes[nid] = None
            upstream = inputs.get("data")
            data_key = upstream[0] if upstream else EMPTY_KEY
            if not upstream:
                keys.values[EMPTY_KEY] = None
            keys.ports[nid] = {"data": data_key}
            continue

        if node.component in (PARAM_TEXT, PARAM_SLIDER):
            kind = "text" if node.component == PARAM_TEXT else "number"
            nkey = _sha(
                {
                    "format": CACHE_FORMAT,
                    kind: node.value,
                    "files": node_files(node, base_dir),
                }
            )
            pkey = port_key(nkey, "value")
            keys.values[pkey] = node.value
        else:
            nkey = _sha(
                {
                    "format": CACHE_FORMAT,
                    "source": node.source,
                    "inputs": inputs,
                    "files": node_files(node, base_dir),
                }
            )
        keys.nodes[nid] = nkey
        keys.ports[nid] = {p: port_key(nkey, p) for p in node.outputs}
    return keys
