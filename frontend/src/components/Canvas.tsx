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
import type { ComponentEntry, GraphView, GroupJson, PortType } from "../apiTypes";
import { fittingPort, type WireFrom } from "../catalog";
import { store, useStore } from "../store";
import { strings } from "../strings";
import {
  carriesList,
  needsRun,
  PARAM_PANEL,
  PARAM_TEXT,
  PORT_COLOURS,
  portTypes as viewTypes,
  sameTypeWires,
} from "../types";
import { ColorNode } from "./nodes/ColorNode";
import { ColormapNode } from "./nodes/ColormapNode";
import { ComponentNode } from "./nodes/ComponentNode";
import { nodeKind, PANEL_SIZE, type GkNode } from "./nodes/kinds";
import { LayerNode } from "./nodes/LayerNode";
import { MapNode } from "./nodes/MapNode";
import { NumberNode } from "./nodes/NumberNode";
import { PanelNode } from "./nodes/PanelNode";
import { DragContext, hideTip, portName, type DragFrom } from "./nodes/Port";
import { SliderNode } from "./nodes/SliderNode";
import { TextNode } from "./nodes/TextNode";
import { ToggleNode } from "./nodes/ToggleNode";
import { ValueListNode } from "./nodes/ValueListNode";
import { Groups } from "./Groups";
import { SearchPopup } from "./SearchPopup";
import { TypedEdge, type GkEdge } from "./TypedEdge";

export const MIME_COMPONENT = "application/x-geoknit-component";
export const MIME_PATH = "application/x-geoknit-path";

const nodeTypes = {
  component: ComponentNode,
  text: TextNode,
  number: NumberNode,
  slider: SliderNode,
  toggle: ToggleNode,
  value_list: ValueListNode,
  color: ColorNode,
  colormap: ColormapNode,
  panel: PanelNode,
  layer: LayerNode,
  map: MapNode,
};
const edgeTypes = { typed: TypedEdge };
const NO_GROUPS: GroupJson[] = [];

function toNodes(graph: GraphView, previous: GkNode[], select: string[] | null): GkNode[] {
  const prev = new Map(previous.map((n) => [n.id, n]));
  const chosen = select ? new Set(select) : null;
  return Object.values(graph.nodes).map((view) => {
    const old = prev.get(view.id);
    const kind = nodeKind(view);
    const node: GkNode = {
      id: view.id,
      type: kind,
      // keep the local position while the node is being dragged
      position: old?.dragging ? old.position : { x: view.position[0], y: view.position[1] },
      data: { view },
      selected: chosen ? chosen.has(view.id) : (old?.selected ?? false),
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

/** What a port can carry; outputs use the type the server resolved (`like:`, SPEC 4). */
function portTypes(graph: GraphView, nodeId: string, side: "in" | "out", name: string): PortType[] {
  const view = graph.nodes[nodeId];
  const ports = side === "in" ? view?.inputs : view?.outputs;
  const port = ports?.find((p) => p.name === name);
  return port ? viewTypes(port) : ["Any"];
}

/** Whether a port carries a list (SPEC 3 "List values"); a Panel's input follows its output. */
function portList(graph: GraphView, nodeId: string, side: "in" | "out", name: string): boolean {
  const view = graph.nodes[nodeId];
  if (!view) return false;
  if (side === "in" && view.component === PARAM_PANEL) {
    return view.outputs[0] ? carriesList(view.outputs[0]) : false;
  }
  const port = (side === "in" ? view.inputs : view.outputs).find((p) => p.name === name);
  return port ? carriesList(port) : false;
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
        colour: PORT_COLOURS[portTypes(graph, w.from[0], "out", w.from[1])[0]],
        list: portList(graph, w.from[0], "out", w.from[1]),
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
  nodeId?: string;
  group?: number;
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
  const groups = useStore((s) => s.graph?.workflow.groups ?? NO_GROUPS);

  useEffect(() => {
    if (!graph) return;
    const select = store.getState().pendingSelect;
    if (select) store.set({ pendingSelect: null });
    setNodes((prev) => toNodes(graph, prev, select));
    if (select) setEdges((prev) => prev.map((e) => ({ ...e, selected: false })));
    setEdges((prev) => toEdges(graph, prev));
    if (!fitted.current) {
      // Fit once, when the page first gets the workflow; never zoom past 100 %.
      fitted.current = true;
      if (Object.keys(graph.nodes).length)
        requestAnimationFrame(() => void flow.fitView({ padding: 0.1, maxZoom: 1 }));
    }
  }, [graph, flow]);

  // a selection asked for without a new graph (Go to Map Layer): select and show the nodes
  const pending = useStore((s) => s.pendingSelect);
  useEffect(() => {
    if (!pending || !graph || !pending.every((id) => id in graph.nodes)) return;
    if (store.getState().pendingSelect !== pending) return; // taken by a new graph (paste)
    store.set({ pendingSelect: null });
    setNodes((prev) => prev.map((n) => ({ ...n, selected: pending.includes(n.id) })));
    setEdges((prev) => prev.map((e) => ({ ...e, selected: false })));
    void flow.fitView({ nodes: pending.map((id) => ({ id })), padding: 0.5, maxZoom: 1, duration: 200 });
  }, [pending, graph, flow]);

  const onNodesChange = useCallback(
    (changes: NodeChange<GkNode>[]) => setNodes((ns) => applyNodeChanges(changes, ns)),
    [],
  );

  // ── keyboard (SPEC 8): Ctrl+Z / Ctrl+Y, Ctrl+C / Ctrl+V, Ctrl+G, Ctrl+S ──
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const nodesRef = useRef(nodes);
  nodesRef.current = nodes;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "s") {
        e.preventDefault(); // even while typing
        void store.save();
        return;
      }
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      const selected = nodesRef.current.filter((n) => n.selected).map((n) => n.id);
      if (key === "z" && !e.shiftKey) void store.undo();
      else if (key === "y" || (key === "z" && e.shiftKey)) void store.redo();
      else if (key === "c") store.copy(selected);
      else if (key === "v") void store.paste(pointer.current ?? undefined);
      else if (key === "g") void store.group(selected);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
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
      const name = portName(p.handleId);
      setDrag({
        nodeId: p.nodeId,
        side,
        types: portTypes(graph, p.nodeId, side, name),
        name,
        title: graph.nodes[p.nodeId]?.title ?? "",
        list: portList(graph, p.nodeId, side, name),
        wired: side === "in" ? sameTypeWires(graph, p.nodeId, name) : undefined,
      });
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
        from: {
          nodeId: from.nodeId,
          port,
          side: from.side,
          types: from.types,
          list: from.list,
          wired: from.wired,
        },
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
      await store.remove(ns.map((n) => n.id), wires); // one undo step
      return false; // the refreshed graph removes them
    },
    [],
  );

  /** A right-clicked selected node acts on the whole selection. */
  const menuTargets = (id: string): string[] => {
    const node = nodes.find((n) => n.id === id);
    return node?.selected ? nodes.filter((n) => n.selected).map((n) => n.id) : [id];
  };

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
        onMouseMove={(e) =>
          (pointer.current = flow.screenToFlowPosition({
            x: e.clientX,
            y: e.clientY,
          }))
        }
        onMouseLeave={() => (pointer.current = null)}
        onPointerDown={hideTip}
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
          onNodeDoubleClick={(e, n) => {
            // Text and Number edit inline; Slider, Value List, Color Swatch, Colormap and
            // Map Layer open their own small window (SPEC 8, change 01 section 8)
            if (n.type === "map") {
              e.stopPropagation();
              store.openMap(n.id);
              return;
            }
            if (n.type !== "component") return;
            e.stopPropagation();
            store.openWindow(n.id);
          }}
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
          <Background variant={BackgroundVariant.Lines} gap={24} color="var(--gk-canvas-grid)" />
          <Groups
            groups={groups}
            nodes={nodes}
            onSelect={(ids) => {
              setNodes((ns) => ns.map((n) => ({ ...n, selected: ids.includes(n.id) })));
              setEdges((es) => es.map((e) => ({ ...e, selected: false })));
            }}
            onMenu={(group, x, y) => setMenu({ ...local(x, y), group })}
          />
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
            {menu.group !== undefined ? (
              <button
                onClick={() => {
                  setMenu(null);
                  void store.ungroup(menu.group!);
                }}
                data-testid="menu-ungroup"
              >
                {strings.ungroup}
              </button>
            ) : (
              <>
                <button onClick={() => runToHere(menu.nodeId!)} data-testid="menu-run-to-here">
                  {strings.runToHere}
                </button>
                <button
                  onClick={() => {
                    setMenu(null);
                    store.copy(menuTargets(menu.nodeId!));
                  }}
                  data-testid="menu-copy"
                >
                  {strings.shortcut(strings.copy, "Ctrl+C")}
                </button>
                <button
                  onClick={() => {
                    setMenu(null);
                    void store.group(menuTargets(menu.nodeId!));
                  }}
                  data-testid="menu-group"
                >
                  {strings.shortcut(strings.group, "Ctrl+G")}
                </button>
                <button
                  onClick={() => {
                    setMenu(null);
                    void store.removeNodes(menuTargets(menu.nodeId!));
                  }}
                  data-testid="menu-delete"
                >
                  {strings.deleteNode}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </DragContext.Provider>
  );
}
