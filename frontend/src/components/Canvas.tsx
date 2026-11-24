import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type FinalConnectionState,
  type NodeChange,
  type OnConnectStartParams,
} from "@xyflow/react";
import type { ComponentEntry, GraphView, PortType } from "../apiTypes";
import { fittingPort, type WireFrom } from "../catalog";
import { store, useStore } from "../store";
import { strings } from "../strings";
import { needsRun, PARAM_TEXT, PORT_COLOURS } from "../types";
import { ComponentNode } from "./nodes/ComponentNode";
import { nodeKind, PANEL_SIZE, type GkNode } from "./nodes/kinds";
import { PanelNode } from "./nodes/PanelNode";
import { DragContext, portName, type DragFrom } from "./nodes/Port";
import { SliderNode } from "./nodes/SliderNode";
import { TextNode } from "./nodes/TextNode";
import { SearchPopup } from "./SearchPopup";
import { TypedEdge, type GkEdge } from "./TypedEdge";

export const MIME_COMPONENT = "application/x-geoknit-component";
export const MIME_PATH = "application/x-geoknit-path";

const nodeTypes = {
  component: ComponentNode,
  text: TextNode,
  slider: SliderNode,
  panel: PanelNode,
};
const edgeTypes = { typed: TypedEdge };

function toNodes(graph: GraphView, previous: GkNode[]): GkNode[] {
  const prev = new Map(previous.map((n) => [n.id, n]));
  return Object.values(graph.nodes).map((view) => {
    const old = prev.get(view.id);
    const kind = nodeKind(view);
    const node: GkNode = {
      id: view.id,
      type: kind,
      // keep the local position while the node is being dragged
      position: old?.dragging ? old.position : { x: view.position[0], y: view.position[1] },
      data: { view },
      selected: old?.selected ?? false,
      dragging: old?.dragging,
      // keep the measured size, or React Flow hides the node's wires until it re-measures
      measured: old?.measured,
    };
    if (kind === "panel") {
      const [w, h] = view.size ?? PANEL_SIZE;
      node.width = w;
      node.height = h;
    }
    return node;
  });
}

function portType(graph: GraphView, nodeId: string, side: "in" | "out", name: string): PortType {
  const view = graph.nodes[nodeId];
  const ports = side === "in" ? view?.inputs : view?.outputs;
  return ports?.find((p) => p.name === name)?.type ?? "Any";
}

function toEdges(graph: GraphView, previous: GkEdge[]): GkEdge[] {
  const selected = new Set(previous.filter((e) => e.selected).map((e) => e.id));
  return graph.workflow.wires.map((w) => {
    const id = `${w.from[0]}.${w.from[1]}>${w.to[0]}.${w.to[1]}`;
    return {
      id,
      type: "typed",
      source: w.from[0],
      sourceHandle: `out:${w.from[1]}`,
      target: w.to[0],
      targetHandle: `in:${w.to[1]}`,
      selected: selected.has(id),
      data: {
        colour: PORT_COLOURS[portType(graph, w.from[0], "out", w.from[1])],
        faded: needsRun(graph.nodes[w.to[0]]?.state),
      },
    };
  });
}

function edgeWire(e: GkEdge): { from: [string, string]; to: [string, string] } {
  return {
    from: [e.source, portName(e.sourceHandle)],
    to: [e.target, portName(e.targetHandle)],
  };
}

interface Search {
  screen: { x: number; y: number };
  flow: { x: number; y: number };
  from?: WireFrom;
}

interface Menu {
  x: number;
  y: number;
  nodeId: string;
}

export function Canvas() {
  const graph = useStore((s) => s.graph);
  const flow = useReactFlow<GkNode, GkEdge>();
  const [nodes, setNodes] = useState<GkNode[]>([]);
  const [edges, setEdges] = useState<GkEdge[]>([]);
  const [drag, setDrag] = useState<DragFrom | null>(null);
  const [search, setSearch] = useState<Search | null>(null);
  const [menu, setMenu] = useState<Menu | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const fitted = useRef(false);

  useEffect(() => {
    if (!graph) return;
    setNodes((prev) => toNodes(graph, prev));
    setEdges((prev) => toEdges(graph, prev));
    if (!fitted.current) {
      // Fit once, when the page first gets the workflow; never zoom past 100 %.
      fitted.current = true;
      if (Object.keys(graph.nodes).length)
        requestAnimationFrame(() => void flow.fitView({ padding: 0.1, maxZoom: 1 }));
    }
  }, [graph, flow]);

  const onNodesChange = useCallback(
    (changes: NodeChange<GkNode>[]) => setNodes((ns) => applyNodeChanges(changes, ns)),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange<GkEdge>[]) => setEdges((es) => applyEdgeChanges(changes, es)),
    [],
  );

  const local = (clientX: number, clientY: number) => {
    const rect = wrapper.current?.getBoundingClientRect();
    return { x: clientX - (rect?.left ?? 0), y: clientY - (rect?.top ?? 0) };
  };

  // ── wiring ──
  const onConnectStart = useCallback(
    (_: unknown, p: OnConnectStartParams) => {
      if (!graph || !p.nodeId || !p.handleId) return;
      const side = p.handleType === "source" ? "out" : "in";
      setDrag({ nodeId: p.nodeId, side, type: portType(graph, p.nodeId, side, portName(p.handleId)) });
    },
    [graph],
  );

  const lastPointer = useRef<{ x: number; y: number } | null>(null);

  const onConnect = useCallback((c: Connection) => {
    void store.addWire(
      [c.source, portName(c.sourceHandle)],
      [c.target, portName(c.targetHandle)],
      lastPointer.current ?? undefined,
    );
  }, []);

  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
      const from = drag;
      setDrag(null);
      const point = "changedTouches" in event ? event.changedTouches[0] : event;
      if (state.toHandle || !state.fromHandle || !from || !graph) return;
      // Dropped in empty space: search, filtered to what fits (SPEC 8).
      const port = portName(state.fromHandle.id);
      setSearch({
        screen: local(point.clientX, point.clientY),
        flow: flow.screenToFlowPosition({ x: point.clientX, y: point.clientY }),
        from: { nodeId: from.nodeId, port, side: from.side, type: from.type },
      });
    },
    [drag, graph, flow],
  );

  const pick = async (entry: ComponentEntry) => {
    const s = search;
    setSearch(null);
    if (!s) return;
    const id = await store.addNode(entry.ref, [Math.round(s.flow.x), Math.round(s.flow.y)]);
    if (!id || !s.from) return;
    const port = fittingPort(entry, s.from);
    if (!port) return;
    if (s.from.side === "out") await store.addWire([s.from.nodeId, s.from.port], [id, port]);
    else await store.addWire([id, port], [s.from.nodeId, s.from.port]);
  };

  // ── drop from the ribbon or the folder tree ──
  const onDragOver = (e: DragEvent) => {
    if (e.dataTransfer.types.includes(MIME_COMPONENT) || e.dataTransfer.types.includes(MIME_PATH)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    }
  };
  const onDrop = (e: DragEvent) => {
    const ref = e.dataTransfer.getData(MIME_COMPONENT);
    const path = e.dataTransfer.getData(MIME_PATH);
    if (!ref && !path) return;
    e.preventDefault();
    const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const pos: [number, number] = [Math.round(p.x), Math.round(p.y)];
    if (ref) void store.addNode(ref, pos);
    else void store.addNode(PARAM_TEXT, pos, { value: path });
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    if (!(e.target as Element).closest(".react-flow__pane")) return;
    setSearch({
      screen: local(e.clientX, e.clientY),
      flow: flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }),
    });
  };

  const onBeforeDelete = useCallback(
    async ({ nodes: ns, edges: es }: { nodes: GkNode[]; edges: GkEdge[] }) => {
      const gone = new Set(ns.map((n) => n.id));
      const wires = es.filter((e) => !gone.has(e.source) && !gone.has(e.target)).map(edgeWire);
      if (wires.length) await store.removeWires(wires);
      if (ns.length) await store.removeNodes(ns.map((n) => n.id));
      return false; // the refreshed graph removes them
    },
    [],
  );

  const runToHere = useMemo(
    () => (id: string) => {
      setMenu(null);
      void store.run("to_node", id);
    },
    [],
  );

  return (
    <DragContext.Provider value={drag}>
      <div
        className="gk-canvas"
        ref={wrapper}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onDoubleClick={onDoubleClick}
        onPointerUpCapture={(e) => (lastPointer.current = { x: e.clientX, y: e.clientY })}
        data-testid="canvas"
      >
        <ReactFlow<GkNode, GkEdge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeDragStop={(_, __, dragged) =>
            void store.moveNodes(
              dragged.map((n) => ({
                id: n.id,
                position: [Math.round(n.position.x), Math.round(n.position.y)],
              })),
            )
          }
          onConnectStart={onConnectStart}
          onConnect={onConnect}
          onConnectEnd={onConnectEnd}
          onBeforeDelete={onBeforeDelete}
          onNodeContextMenu={(e, n) => {
            e.preventDefault();
            setMenu({ ...local(e.clientX, e.clientY), nodeId: n.id });
          }}
          onPaneClick={() => setMenu(null)}
          deleteKeyCode={["Delete", "Backspace"]}
          panOnDrag={[1]}
          selectionOnDrag
          panActivationKeyCode="Space"
          zoomOnDoubleClick={false}
          minZoom={0.1}
          maxZoom={3}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Lines} gap={24} color="#d4d8de" />
        </ReactFlow>
        {search && (
          <SearchPopup
            x={search.screen.x}
            y={search.screen.y}
            from={search.from}
            onPick={(e) => void pick(e)}
            onClose={() => setSearch(null)}
          />
        )}
        {menu && (
          <div className="gk-popover gk-menu" style={{ left: menu.x, top: menu.y }}>
            <button onClick={() => runToHere(menu.nodeId)} data-testid="menu-run-to-here">
              {strings.runToHere}
            </button>
            <button
              onClick={() => {
                setMenu(null);
                void store.removeNodes([menu.nodeId]);
              }}
            >
              {strings.deleteNode}
            </button>
          </div>
        )}
      </div>
    </DragContext.Provider>
  );
}
