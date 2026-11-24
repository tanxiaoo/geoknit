// App state: the server's graph view plus run results streamed over /ws.
//
// Every edit goes to the API and is followed by a fresh GET /api/graph, so the
// canvas always shows what the server holds (it is local and cheap).

import { useSyncExternalStore } from "react";
import { api as defaultApi, type Api } from "./api";
import type {
  ComponentEntry,
  Display,
  FileNode,
  GraphView,
  NodeJson,
  NodePatch,
  NodeState,
  RunReport,
  ServerEvent,
  Status,
  WireJson,
} from "./apiTypes";
import { strings } from "./strings";

export interface Toast {
  id: number;
  message: string;
  x?: number;
  y?: number;
}

export interface Tip {
  text: string;
  x: number;
  y: number;
}

export type FileMenu = "closed" | "menu" | "saveAs";

export interface AppState {
  graph: GraphView | null;
  components: ComponentEntry[];
  files: FileNode | null;
  status: Status | null;
  connected: boolean;
  summaries: Record<string, Record<string, string>>;
  errors: Record<string, string>;
  lastChange: string | null;
  toast: Toast | null;
  lastReport: RunReport | null;
  /** Finished runs since the page loaded. */
  runCount: number;
  /** Hover tooltip with a port's describe() summary. */
  tip: Tip | null;
  fileMenu: FileMenu;
  /** Node ids the canvas selects once the next graph arrives (after paste). */
  pendingSelect: string[] | null;
}

export const initialState: AppState = {
  graph: null,
  components: [],
  files: null,
  status: null,
  connected: false,
  summaries: {},
  errors: {},
  lastChange: null,
  toast: null,
  lastReport: null,
  runCount: 0,
  tip: null,
  fileMenu: "closed",
  pendingSelect: null,
};

/** What a port carries after a run: its own output, or the output wired into it. */
export function portSummary(
  state: AppState,
  nodeId: string,
  side: "in" | "out",
  name: string,
): string | null {
  const g = state.graph;
  if (!g) return null;
  let src: [string, string] = [nodeId, name];
  if (side === "in") {
    const wire = g.workflow.wires.find((w) => w.to[0] === nodeId && w.to[1] === name);
    if (!wire) return null;
    src = wire.from;
  }
  if (g.nodes[src[0]]?.state !== "done") return null;
  return state.summaries[src[0]]?.[src[1]] ?? null;
}

/** The nodes and the wires among them, as POST /api/paste takes them. */
export interface Clip {
  nodes: NodeJson[];
  wires: WireJson[];
}

export function clipOf(graph: GraphView, ids: string[]): Clip {
  const keep = new Set(ids);
  return {
    nodes: graph.workflow.nodes.filter((n) => keep.has(n.id)),
    wires: graph.workflow.wires.filter((w) => keep.has(w.from[0]) && keep.has(w.to[0])),
  };
}

export interface Point {
  x: number;
  y: number;
}

function withStates(graph: GraphView, states: Record<string, NodeState>): GraphView {
  const nodes = { ...graph.nodes };
  for (const [id, state] of Object.entries(states)) {
    if (nodes[id]) nodes[id] = { ...nodes[id], state };
  }
  return { ...graph, nodes };
}

/** Apply one /ws event to the state (pure, for tests). */
export function reduceEvent(state: AppState, ev: ServerEvent): AppState {
  const g = state.graph;
  switch (ev.type) {
    case "states":
      return g
        ? { ...state, graph: { ...withStates(g, ev.states), out_of_date: ev.out_of_date } }
        : state;
    case "started":
      return g ? { ...state, graph: withStates(g, { [ev.node]: "running" }) } : state;
    case "done": {
      const errors = { ...state.errors };
      delete errors[ev.node];
      return {
        ...state,
        graph: g ? withStates(g, { [ev.node]: "done" }) : g,
        summaries: { ...state.summaries, [ev.node]: ev.outputs },
        errors,
      };
    }
    case "error":
    case "skipped": {
      const summaries = { ...state.summaries };
      delete summaries[ev.node];
      return {
        ...state,
        graph: g ? withStates(g, { [ev.node]: ev.type === "error" ? "error" : "skipped" }) : g,
        errors: { ...state.errors, [ev.node]: ev.traceback },
        summaries,
      };
    }
    case "run_finished":
      return { ...state, lastReport: ev.report, runCount: state.runCount + 1 };
    case "worker":
      return { ...state, status: { python: ev.python, worker: ev.worker, pid: ev.pid } };
    default:
      return state;
  }
}

let toastId = 0;

export class Store {
  private state: AppState = initialState;
  private listeners = new Set<() => void>();
  private clip: Clip | null = null;
  private pastes = 0;

  constructor(readonly api: Api = defaultApi) {}

  getState = (): AppState => this.state;

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  set(patch: Partial<AppState>): void {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  setConnected(connected: boolean): void {
    this.set({ connected });
  }

  applyEvent(ev: ServerEvent): void {
    this.state = reduceEvent(this.state, ev);
    this.listeners.forEach((fn) => fn());
    if (ev.type === "run_finished") {
      if (ev.error) this.showToast(ev.error);
      void this.refreshGraph();
      void this.refreshFiles();
    } else if (ev.type === "workflow_opened") {
      this.set({ summaries: {}, errors: {}, lastChange: null });
      void this.refreshGraph();
    }
  }

  // ── loading ──
  async load(): Promise<void> {
    try {
      const [components, graph, files, status] = await Promise.all([
        this.api.components(),
        this.api.graph(),
        this.api.files(),
        this.api.status(),
      ]);
      this.set({ components, graph, files, status });
      await this.loadResults();
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  async refreshGraph(): Promise<void> {
    try {
      this.set({ graph: await this.api.graph() });
      await this.loadResults();
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  async refreshFiles(): Promise<void> {
    try {
      this.set({ files: await this.api.files() });
    } catch {
      /* the tree simply stays as it was */
    }
  }

  /** Fetch summaries / errors the page has not seen (after a reload, or a run). */
  private async loadResults(): Promise<void> {
    const g = this.state.graph;
    if (!g) return;
    const wanted = Object.values(g.nodes).filter(
      (n) =>
        (n.state === "done" && !this.state.summaries[n.id]) ||
        ((n.state === "error" || n.state === "skipped") && !this.state.errors[n.id]),
    );
    if (!wanted.length) return;
    const results = await Promise.all(
      wanted.map((n) => this.api.output(n.id).then((o) => [n.id, o] as const, () => null)),
    );
    const summaries = { ...this.state.summaries };
    const errors = { ...this.state.errors };
    for (const r of results) {
      if (!r) continue;
      const [id, out] = r;
      if (out.error) errors[id] = out.error;
      else summaries[id] = out.outputs;
    }
    this.set({ summaries, errors });
  }

  // ── toasts ──
  showToast(message: string, at?: Point): void {
    const toast = { id: ++toastId, message, x: at?.x, y: at?.y };
    this.set({ toast });
    setTimeout(() => {
      if (this.state.toast?.id === toast.id) this.set({ toast: null });
    }, 4000);
  }

  private async mutate<T>(fn: () => Promise<T>, at?: Point): Promise<T | undefined> {
    try {
      const result = await fn();
      await this.refreshGraph();
      return result;
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e), at);
      await this.refreshGraph();
      return undefined;
    }
  }

  // ── edits ──
  async addNode(
    component: string,
    position: [number, number],
    init?: NodePatch,
  ): Promise<string | undefined> {
    return this.mutate(async () => {
      const node = await this.api.addNode(component, position);
      if (init) await this.api.patchNode(node.id, init);
      return node.id;
    });
  }

  /** What the banner names after an edit ("n_trees changed"). */
  changeLabel(id: string, patch: NodePatch): string | null {
    const g = this.state.graph;
    const node = g?.nodes[id];
    if (!g || !node) return null;
    if (patch.settings) return Object.keys(patch.settings)[0] ?? node.title;
    if ("value" in patch || "min" in patch || "max" in patch || "step" in patch) {
      const wire = g.workflow.wires.find((w) => w.from[0] === id);
      return wire ? wire.to[1] : node.title;
    }
    if (patch.source !== undefined) return node.title;
    return null;
  }

  async patchNode(id: string, patch: NodePatch): Promise<void> {
    const label = this.changeLabel(id, patch);
    await this.mutate(() => this.api.patchNode(id, patch));
    if (label) this.set({ lastChange: label });
  }

  /** Move nodes locally at once, then tell the server (one undo step). */
  async moveNodes(moves: { id: string; position: [number, number] }[]): Promise<void> {
    const g = this.state.graph;
    if (g) {
      const nodes = { ...g.nodes };
      for (const m of moves) if (nodes[m.id]) nodes[m.id] = { ...nodes[m.id], position: m.position };
      this.set({ graph: { ...g, nodes } });
    }
    const positions = Object.fromEntries(moves.map((m) => [m.id, m.position]));
    await this.mutate(() => this.api.move(positions));
  }

  /** Delete nodes and wires as one undo step. */
  async remove(ids: string[], wires: WireJson[] = []): Promise<void> {
    if (!ids.length && !wires.length) return;
    await this.mutate(() => this.api.remove(ids, wires));
  }

  async removeNodes(ids: string[]): Promise<void> {
    await this.remove(ids);
  }

  async addWire(from: [string, string], to: [string, string], at?: Point): Promise<boolean> {
    const ok = await this.mutate(() => this.api.addWire(from, to).then(() => true), at);
    if (ok) {
      const node = this.state.graph?.nodes[to[0]];
      this.set({ lastChange: node ? node.title : null });
    }
    return ok === true;
  }

  async removeWires(wires: WireJson[]): Promise<void> {
    await this.remove([], wires);
  }

  async undo(): Promise<void> {
    if (this.state.graph?.can_undo) await this.mutate(() => this.api.undo());
  }

  async redo(): Promise<void> {
    if (this.state.graph?.can_redo) await this.mutate(() => this.api.redo());
  }

  // ── clipboard and groups ──
  copy(ids: string[]): void {
    const g = this.state.graph;
    if (!g || !ids.length) return;
    this.clip = clipOf(g, ids);
    this.pastes = 0;
  }

  get hasClip(): boolean {
    return this.clip !== null && this.clip.nodes.length > 0;
  }

  /** Paste the copied nodes; with ``at``, their top-left corner goes there. */
  async paste(at?: Point): Promise<string[] | undefined> {
    const clip = this.clip;
    if (!clip?.nodes.length) return undefined;
    let offset: [number, number];
    if (at) {
      const x0 = Math.min(...clip.nodes.map((n) => n.position[0]));
      const y0 = Math.min(...clip.nodes.map((n) => n.position[1]));
      offset = [Math.round(at.x - x0), Math.round(at.y - y0)];
    } else {
      this.pastes += 1;
      offset = [30 * this.pastes, 30 * this.pastes];
    }
    return this.mutate(async () => {
      const { ids } = await this.api.paste(clip.nodes, clip.wires, offset);
      this.set({ pendingSelect: ids });
      return ids;
    });
  }

  async group(ids: string[]): Promise<void> {
    if (ids.length) await this.mutate(() => this.api.addGroup(strings.newGroup, ids));
  }

  async renameGroup(index: number, title: string): Promise<void> {
    await this.mutate(() => this.api.patchGroup(index, { title }));
  }

  async ungroup(index: number): Promise<void> {
    await this.mutate(() => this.api.removeGroup(index));
  }

  // ── files ──
  /** Save to the open file, or to ``path`` (relative to the project folder). */
  async save(path?: string): Promise<boolean> {
    const g = this.state.graph;
    if (!path && !g?.path) {
      this.set({ fileMenu: "saveAs" });
      return false;
    }
    const target = path && !path.toLowerCase().endsWith(".geoknit") ? `${path}.geoknit` : path;
    const ok = await this.mutate(() => this.api.save(target).then(() => true));
    if (ok) {
      this.set({ fileMenu: "closed" });
      void this.refreshFiles();
    }
    return ok === true;
  }

  async open(path: string): Promise<void> {
    this.set({ fileMenu: "closed" });
    await this.mutate(() => this.api.open(path));
  }

  async recover(restore: boolean): Promise<void> {
    await this.mutate(() => this.api.recover(restore));
  }

  async setDisplay(display: Exclude<Display, "default">): Promise<void> {
    await this.mutate(() => this.api.patchView({ display }));
  }

  // ── running ──
  async run(mode: "all" | "to_node" = "all", nodeId?: string): Promise<void> {
    try {
      this.set({ lastChange: null });
      await this.api.run(mode, nodeId);
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  async stop(): Promise<void> {
    try {
      await this.api.stop();
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  async trust(): Promise<void> {
    await this.mutate(() => this.api.trust());
  }

  /** Panels show their wired value's summary. */
  panelText(id: string): string | null {
    return this.state.summaries[id]?.data ?? null;
  }
}

export const store = new Store();

declare global {
  interface Window {
    __geoknit?: Store;
  }
}
if (typeof window !== "undefined") window.__geoknit = store; // for end-to-end tests

export function useStore<T>(select: (s: AppState) => T, s: Store = store): T {
  return useSyncExternalStore(s.subscribe, () => select(s.getState()));
}
