// App state: the server's graph view plus run results streamed over /ws.
//
// Every edit goes to the API and is followed by a fresh GET /api/graph, so the
// canvas always shows what the server holds (it is local and cheap).

import { useSyncExternalStore } from "react";
import { ApiError, api as defaultApi, type Api } from "./api";
import type {
  ComponentEntry,
  Display,
  ExportResult,
  FileNode,
  GraphView,
  NodeJson,
  NodeOutput,
  NodePatch,
  NodeState,
  NamedRamps,
  PanelView,
  RunReport,
  ServerEvent,
  Status,
  TabView,
  WireJson,
} from "./apiTypes";
import { strings } from "./strings";
import { applyThemeSetting, pageThemeSetting, type ThemeSetting } from "./theme";
import { categoryColour } from "./types";

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
  /** Components and Params nodes in ribbon order (`GET /api/components`). */
  components: ComponentEntry[];
  /** Ribbon tabs with their colours and groups. */
  tabs: TabView[];
  files: FileNode | null;
  status: Status | null;
  connected: boolean;
  summaries: Record<string, Record<string, string>>;
  /** Per node and port, the Panel view of the last result (change 01, section 11). */
  views: Record<string, Record<string, PanelView>>;
  /** Per Panel, where later table pages come from (`GET /api/nodes/{id}/output`). */
  paging: Record<string, Paging>;
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
  /** Output log lines per node: the last run, streamed while it runs. */
  logs: Record<string, string[]>;
  /** The node whose component window is open (SPEC 8). */
  windowNode: string | null;
  /** The Map Viewer whose map window is open (SPEC 8). */
  mapNode: string | null;
  /** `map_changed` events so far: the open map re-reads its layers on each (change 03). */
  mapVersion: number;
  /** The Colormap node whose editor window is open (change 03, section 2). */
  colormapNode: string | null;
  /** The Map Layer whose style window is open (change 03, section 3). */
  layerNode: string | null;
  /** The named colormap ramps (`GET /api/colormaps`), loaded when a Colormap node needs them. */
  ramps: NamedRamps | null;
  /** The user's theme setting (`GET /api/settings`, change 02). */
  theme: ThemeSetting;
}

/** A Panel's table paging: the port key of the table feeding it, and whether the disk
 * cache can serve later pages. */
export interface Paging {
  key: string | null;
  diskCache: boolean;
}

export const initialState: AppState = {
  graph: null,
  components: [],
  tabs: [],
  files: null,
  status: null,
  connected: false,
  summaries: {},
  views: {},
  paging: {},
  errors: {},
  lastChange: null,
  toast: null,
  lastReport: null,
  runCount: 0,
  tip: null,
  fileMenu: "closed",
  pendingSelect: null,
  logs: {},
  windowNode: null,
  mapNode: null,
  mapVersion: 0,
  colormapNode: null,
  layerNode: null,
  ramps: null,
  theme: "system",
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
      return {
        ...state,
        graph: g ? withStates(g, { [ev.node]: "running" }) : g,
        logs: { ...state.logs, [ev.node]: [] },
      };
    case "log":
      return {
        ...state,
        logs: { ...state.logs, [ev.node]: [...(state.logs[ev.node] ?? []), ev.line] },
      };
    case "done": {
      const errors = { ...state.errors };
      delete errors[ev.node];
      const paging = { ...state.paging };
      delete paging[ev.node]; // a new result: fetched again when a Panel pages it
      return {
        ...state,
        graph: g ? withStates(g, { [ev.node]: "done" }) : g,
        summaries: { ...state.summaries, [ev.node]: ev.outputs },
        views: { ...state.views, [ev.node]: ev.views ?? {} },
        paging,
        errors,
      };
    }
    case "error":
    case "skipped": {
      const summaries = { ...state.summaries };
      delete summaries[ev.node];
      const views = { ...state.views };
      delete views[ev.node];
      return {
        ...state,
        graph: g ? withStates(g, { [ev.node]: ev.type === "error" ? "error" : "skipped" }) : g,
        errors: { ...state.errors, [ev.node]: ev.traceback },
        summaries,
        views,
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

function pagingOf(out: NodeOutput): Paging {
  return { key: out.keys?.data ?? null, diskCache: out.disk_cache ?? true };
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
      if (this.state.windowNode) void this.loadOutput(this.state.windowNode);
      void this.refreshFiles();
    } else if (ev.type === "workflow_opened") {
      this.set({
        summaries: {},
        views: {},
        paging: {},
        errors: {},
        logs: {},
        lastChange: null,
        windowNode: null,
        mapNode: null,
        colormapNode: null,
        layerNode: null,
      });
      void this.refreshGraph();
    } else if (ev.type === "node_changed") {
      void this.refreshGraph(); // edited in VS Code
    } else if (ev.type === "map_changed") {
      void this.refreshGraph(); // the Map Layer's `layer` (also when another page edited it)
      // an open map that shows this layer redraws at once, without a Run
      if (this.state.mapNode && ev.viewers.includes(this.state.mapNode)) {
        this.set({ mapVersion: this.state.mapVersion + 1 });
      }
    }
  }

  // ── loading ──
  async load(): Promise<void> {
    try {
      const [library, graph, files, status] = await Promise.all([
        this.api.components(),
        this.api.graph(),
        this.api.files(),
        this.api.status(),
      ]);
      this.set({ components: library.components, tabs: library.tabs, graph, files, status });
      await this.loadResults();
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  async refreshGraph(): Promise<void> {
    try {
      const graph = await this.api.graph();
      const open = this.state.windowNode;
      const map = this.state.mapNode;
      const cm = this.state.colormapNode;
      const layer = this.state.layerNode;
      this.set({
        graph,
        windowNode: open && graph.nodes[open] ? open : null,
        mapNode: map && graph.nodes[map] ? map : null,
        colormapNode: cm && graph.nodes[cm] ? cm : null,
        layerNode: layer && graph.nodes[layer] ? layer : null,
      });
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
    const views = { ...this.state.views };
    const paging = { ...this.state.paging };
    const errors = { ...this.state.errors };
    for (const r of results) {
      if (!r) continue;
      const [id, out] = r;
      if (out.error) errors[id] = out.error;
      else {
        summaries[id] = out.outputs;
        views[id] = out.views ?? {};
        paging[id] = pagingOf(out);
      }
    }
    this.set({ summaries, views, paging, errors });
  }

  private pagingLoading = new Map<string, Promise<void>>();

  /** Where a Panel's later table pages come from: fetched once per result. */
  loadPaging(id: string): Promise<void> {
    if (this.state.paging[id]) return Promise.resolve();
    let p = this.pagingLoading.get(id);
    if (!p) {
      p = this.api
        .output(id)
        .then((out) => this.set({ paging: { ...this.state.paging, [id]: pagingOf(out) } }))
        .catch(() => undefined)
        .finally(() => this.pagingLoading.delete(id));
      this.pagingLoading.set(id, p);
    }
    return p;
  }

  /** The Output of one node (log and error), for the component window. */
  async loadOutput(id: string): Promise<void> {
    try {
      const out = await this.api.output(id);
      const errors = { ...this.state.errors };
      if (out.error) errors[id] = out.error;
      else delete errors[id];
      this.set({ logs: { ...this.state.logs, [id]: out.log }, errors });
    } catch {
      /* the Output simply stays as it was */
    }
  }

  private rampsLoading: Promise<void> | null = null;

  /** Load the named colormap ramps once (Colormap nodes draw their gradient from them). */
  loadRamps(): Promise<void> {
    if (this.state.ramps) return Promise.resolve();
    this.rampsLoading ??= this.api
      .colormaps()
      .then((ramps) => this.set({ ramps }))
      .catch(() => {
        this.rampsLoading = null; // try again next time
      });
    return this.rampsLoading;
  }

  async refreshComponents(): Promise<void> {
    try {
      const library = await this.api.components();
      this.set({ components: library.components, tabs: library.tabs });
    } catch {
      /* the ribbon stays as it was */
    }
  }

  // ── component window (SPEC 8) ──
  openWindow(id: string): void {
    this.set({ windowNode: id });
    void this.loadOutput(id);
  }

  closeWindow(): void {
    this.set({ windowNode: null });
  }

  // ── map window (SPEC 8) ──
  openMap(id: string): void {
    this.set({ mapNode: id });
  }

  closeMap(): void {
    this.set({ mapNode: null });
  }

  /** Select one node on the canvas (the map window's Go to Map Layer, change 03). */
  selectNode(id: string): void {
    this.set({ pendingSelect: [id] });
  }

  // ── colormap editor (change 03, section 2) ──
  openColormap(id: string): void {
    this.set({ colormapNode: id });
    void this.loadRamps();
  }

  closeColormap(): void {
    this.set({ colormapNode: null });
  }

  // ── Map Layer window (change 03, section 3) ──
  openLayer(id: string): void {
    this.set({ layerNode: id });
    void this.loadRamps();
  }

  closeLayer(): void {
    this.set({ layerNode: null });
  }

  /** Test: run this component only, using cached inputs. */
  async test(id: string): Promise<void> {
    try {
      await this.api.run("test", id);
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  /** Save as component…; asks before replacing a user component of the same name. */
  async saveComponent(id: string, confirmOverwrite: (message: string) => boolean): Promise<void> {
    try {
      let saved: { ref: string };
      try {
        saved = await this.api.saveComponent(id);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e;
        if (!confirmOverwrite(strings.overwriteComponent(e.message))) return;
        saved = await this.api.saveComponent(id, true);
      }
      await this.refreshComponents();
      this.showToast(strings.savedAsComponent(saved.ref));
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
  }

  /** Export .py into the project; asks before replacing an existing file. */
  async exportPy(path: string, confirmOverwrite: (message: string) => boolean): Promise<boolean> {
    const target = path.toLowerCase().endsWith(".py") ? path : `${path}.py`;
    try {
      let result: ExportResult;
      try {
        result = await this.api.exportPy(target);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 409)) throw e;
        if (!confirmOverwrite(strings.overwriteScript(e.message))) return false;
        result = await this.api.exportPy(target, true);
      }
      const written = result.path ?? target;
      this.showToast(
        result.warnings.length
          ? strings.exportedWithWarnings(written, result.warnings)
          : strings.exported(written),
      );
      void this.refreshFiles();
      return true;
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
      return false;
    }
  }

  async openInVsCode(id: string): Promise<void> {
    try {
      const { path } = await this.api.openInVsCode(id);
      this.showToast(strings.openedInVsCode(path));
    } catch (e) {
      this.showToast(e instanceof Error ? e.message : String(e));
    }
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
    const keys = ["value", "min", "max", "step", "integer", "options"] as const;
    if (keys.some((k) => k in patch)) {
      const wire = g.workflow.wires.find((w) => w.from[0] === id);
      return wire ? wire.to[1] : node.title;
    }
    if (patch.source !== undefined || patch.ports) return node.title;
    return null;
  }

  async patchNode(id: string, patch: NodePatch): Promise<void> {
    await this.tryPatchNode(id, patch);
  }

  /** One edit (one undo step); false when the server refused it (a toast says why). */
  async tryPatchNode(id: string, patch: NodePatch): Promise<boolean> {
    const label = this.changeLabel(id, patch);
    const ok = await this.mutate(() => this.api.patchNode(id, patch).then(() => true));
    if (label) this.set({ lastChange: label });
    return ok === true;
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

  // ── user settings (change 02) ──
  private themeEdits = 0;
  private themeSave: Promise<void> = Promise.resolve();

  /** On startup: keep the theme the page was served with (and follow the OS when it is
   * `system`), then apply the saved one (under `npm run dev` the page has none). */
  async loadSettings(): Promise<void> {
    this.applyTheme(pageThemeSetting());
    const edits = this.themeEdits;
    try {
      const { theme } = await this.api.settings();
      if (edits === this.themeEdits) this.applyTheme(theme);
    } catch {
      /* the page's theme stays */
    }
  }

  /** Choose the theme (top bar): applied at once, saved for this user. */
  async setTheme(theme: ThemeSetting): Promise<void> {
    this.themeEdits++;
    this.applyTheme(theme);
    // one PATCH at a time, in click order, so fast clicks save the theme that is shown
    const save = this.themeSave.then(async () => {
      try {
        await this.api.patchSettings({ theme });
      } catch (e) {
        this.showToast(e instanceof Error ? e.message : String(e));
      }
    });
    this.themeSave = save;
    await save;
  }

  private applyTheme(theme: ThemeSetting): void {
    applyThemeSetting(theme);
    this.set({ theme });
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

/** The centre-strip colour of a category, from the server's tabs (SPEC 8). */
export function useCategoryColour(category: string | null | undefined): string {
  const tabs = useStore((s) => s.tabs);
  return categoryColour(tabs, category);
}
