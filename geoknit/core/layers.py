"""Building a Map Layer's ``MapLayer`` (change 03, section 3).

The server builds the layer itself; nothing runs in the worker. Each style
input (``LAYER_STYLE_INPUTS``) takes, in order:

1. the current value of a Params node wired into it (through Panels too);
2. the last done result of a component wired into it, which only the caller
   can read (``DoneResults``, from the disk cache in the server);
3. the value saved in the node's ``style`` (set in its window);
4. the Map Viewer's default (``None``; opacity ``1``; name: the data source's
   title and port).

A wired input whose value cannot be had (the component has not run, the disk
cache is off, the value has the wrong type) counts as unwired, and
``LayerBuild.issues`` says why, for the Map Layer's window.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from geoknit.core import types
from geoknit.core.graph import (
    LAYER_STYLE_INPUTS,
    PARAM_LAYER,
    PARAM_PANEL,
    VALUE_PARAMS,
    Graph,
    GraphError,
    Wire,
    param_output,
    parse_bands,
)

DEFAULT_OPACITY = 1.0


class DoneResults(Protocol):
    """What the caller knows of components' last done results."""

    def value(self, node_id: str, port: str) -> Any:
        """The value of ``node_id.port``; raises ``LookupError`` when there is none."""

    def data_type(self, node_id: str, port: str) -> str | None:
        """The type of a done result (``Raster`` …), or ``None`` when unknown."""

    def band_names(self, node_id: str, port: str) -> list[str] | None:
        """The band names of a done Raster result, or ``None`` when unknown."""


@dataclass
class LayerBuild:
    """A Map Layer's layer, or ``None`` without data, and what the window shows."""

    layer: types.MapLayer | None = None
    issues: dict[str, str] = field(default_factory=dict)
    """Input or style field → why its wired or saved value is not used."""
    wired: dict[str, str] = field(default_factory=dict)
    """Style input → ``params`` (a Params node's value) or ``component`` (a done result)
    for each wired style input whose value is used."""

    def to_json(self) -> dict[str, Any]:
        return {
            "value": self.layer.to_json() if self.layer is not None else None,
            "issues": dict(self.issues),
            "wired": dict(self.wired),
        }


def layer_key(data_key: str, layer: types.MapLayer) -> str:
    """Node key of a Map Layer: ``sha256("layer" + data port key + style JSON)``."""
    style = {k: v for k, v in layer.to_json().items() if k != "source"}
    text = json.dumps(style, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(("layer" + data_key + text).encode("utf-8")).hexdigest()


def _origin(graph: Graph, wire: Wire) -> Wire:
    """Follow Panels back to the wire that brings the value to the first of them."""
    seen: set[str] = set()
    while True:
        src = graph.nodes.get(wire.src)
        if src is None or src.component != PARAM_PANEL or wire.src in seen:
            return wire
        seen.add(wire.src)
        upstream = graph.wires_into(wire.src, "data")
        if not upstream:
            return wire
        wire = upstream[0]


_UNWIRED = object()


def _wired_value(graph: Graph, wire: Wire, results: DoneResults | None, build: LayerBuild) -> Any:
    """The value a style wire brings, or ``_UNWIRED`` (with an issue) when it has none."""
    name = wire.dst_port
    origin = _origin(graph, wire)
    src = graph.nodes.get(origin.src)
    if src is None:
        return _UNWIRED
    if src.component == PARAM_PANEL:
        build.issues[name] = "the Panel wired here has no input"
        return _UNWIRED
    if src.component in VALUE_PARAMS:
        value, how = param_output(src), "params"
    else:
        if results is None:
            build.issues[name] = f"{src.title} has no result yet; run it"
            return _UNWIRED
        try:
            value = results.value(origin.src, origin.src_port)
        except LookupError as exc:
            reason = str(exc.args[0]) if exc.args else f"{src.title} has no result yet; run it"
            build.issues[name] = reason
            return _UNWIRED
        how = "component"
    port = graph.nodes[wire.dst].inputs[name]
    value = types.convert_for_input(value, port.types)
    problem = types.check_value(port.types, value)
    if problem:
        build.issues[name] = problem
        return _UNWIRED
    build.wired[name] = how
    return value


def _style_inputs(
    graph: Graph, node_id: str, results: DoneResults | None, build: LayerBuild
) -> dict[str, Any]:
    """Each style input's value: wired, else saved in ``style``; missing → default."""
    node = graph.node(node_id)
    saved = node.style
    out: dict[str, Any] = {}
    for name in LAYER_STYLE_INPUTS:
        wires = graph.wires_into(node_id, name)
        value = _wired_value(graph, wires[0], results, build) if wires else _UNWIRED
        if value is not _UNWIRED:
            out[name] = value
        elif name == "colormap" and "colormap" in saved:
            out[name] = types.Colormap.from_json(saved["colormap"])
        elif name == "color" and "color" in saved:
            out[name] = types.Color(saved["color"])
        elif name in saved:
            out[name] = saved[name]
    return out


def _kind(graph: Graph, data: Wire, results: DoneResults | None) -> str | None:
    found = [
        t for t in graph.output_types(data.src, data.src_port) if t in (types.RASTER, types.VECTOR)
    ]
    if len(found) != 1 and results is not None:
        origin = _origin(graph, data)
        known = results.data_type(origin.src, origin.src_port)
        found = [known] if known in (types.RASTER, types.VECTOR) else []
    return found[0].lower() if len(found) == 1 else None


def _bands(
    graph: Graph, data: Wire, text: str, results: DoneResults | None, build: LayerBuild
) -> tuple[int, ...] | None:
    try:
        wanted = parse_bands(text)
    except GraphError as exc:
        build.issues["bands"] = str(exc)
        return None
    if all(isinstance(b, int) for b in wanted):
        return tuple(int(b) for b in wanted)
    origin = _origin(graph, data)
    names = results.band_names(origin.src, origin.src_port) if results is not None else None
    if names is None:
        build.issues["bands"] = "band names are known once the raster has a result"
        return None
    out: list[int] = []
    for b in wanted:
        if isinstance(b, int):
            out.append(b)
        elif b in names:
            out.append(names.index(b) + 1)
        else:
            build.issues["bands"] = f'no band "{b}" (bands: {", ".join(names)})'
            return None
    return tuple(out)


def build_layer(
    graph: Graph, node_id: str, data_key: str | None, results: DoneResults | None = None
) -> LayerBuild:
    """The ``MapLayer`` of Map Layer ``node_id`` whose ``data`` has port key ``data_key``."""
    node = graph.node(node_id)
    if node.component != PARAM_LAYER:
        raise GraphError(f"{node.title} is not a Map Layer")
    build = LayerBuild()
    data_wires = graph.wires_into(node_id, "data")
    style = _style_inputs(graph, node_id, results, build)
    if not data_wires or data_key is None:
        build.issues["data"] = "wire a Raster or Vector into data"
        return build
    data = data_wires[0]
    kind = _kind(graph, data, results)
    if kind is None:
        build.issues["data"] = "the data's type (Raster or Vector) is known once it has a result"
        return build
    src = graph.node(data.src)
    name = style.get("name")
    if not isinstance(name, str) or not name.strip():
        name = f"{src.title} › {data.src_port}"
    opacity = style.get("opacity", DEFAULT_OPACITY)
    if not 0 <= opacity <= 1:
        build.issues["opacity"] = f"opacity {opacity:g} is not between 0 and 1"
        build.wired.pop("opacity", None)
        opacity = DEFAULT_OPACITY
    bands = None
    if kind == "raster" and "bands" in style:
        bands = _bands(graph, data, style["bands"], results, build)
        if bands is None:
            build.wired.pop("bands", None)
    layer_field = node.style.get("field") if kind == "vector" else None
    build.layer = types.MapLayer(
        source=data_key,
        kind=kind,
        name=name,
        colormap=style.get("colormap"),
        color=style.get("color"),
        opacity=opacity,
        bands=bands,
        field=layer_field,
    )
    return build
