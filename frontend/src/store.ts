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
  NodePatch,
  NodeState,
  RunReport,
  ServerEvent,
  Status,
} from "./apiTypes";

export interface Toast {
  id: number;
  message: string;
  x?: number;
  y?: number;
}

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
};

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

  constructor(readonly api: Api = defaultApi) {}

  getState = (): AppState => this.state;

  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  private set(patch: Partial<AppState>): void {
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

  /** Move nodes locally at once, then tell the server. */
  async moveNodes(moves: { id: string; position: [number, number] }[]): Promise<void> {
    const g = this.state.graph;
    if (g) {
      const nodes = { ...g.nodes };
      for (const m of moves) if (nodes[m.id]) nodes[m.id] = { ...nodes[m.id], position: m.position };
      this.set({ graph: { ...g, nodes } });
    }
    await this.mutate(() =>
      Promise.all(moves.map((m) => this.api.patchNode(m.id, { position: m.position }))),
    );
  }

  async removeNodes(ids: string[]): Promise<void> {
    await this.mutate(async () => {
      for (const id of ids) await this.api.removeNode(id);
    });
  }

  async addWire(from: [string, string], to: [string, string], at?: Point): Promise<boolean> {
    const ok = await this.mutate(() => this.api.addWire(from, to).then(() => true), at);
    if (ok) {
      const node = this.state.graph?.nodes[to[0]];
      this.set({ lastChange: node ? node.title : null });
    }
    return ok === true;
  }

  async removeWires(wires: { from: [string, string]; to: [string, string] }[]): Promise<void> {
    await this.mutate(async () => {
      for (const w of wires) await this.api.removeWire(w.from, w.to);
    });
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
