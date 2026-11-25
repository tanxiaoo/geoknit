// Shapes of the GeoKnit server API (SPEC 9).

export type PortType = "Number" | "Text" | "Raster" | "Vector" | "Table" | "Model" | "Any";
export type NodeState = "never_run" | "out_of_date" | "running" | "done" | "error" | "skipped";
export type Display = "default" | "text" | "icon";

export interface PortView {
  name: string;
  type: PortType;
  access: "item" | "list";
  file?: string | null;
}

export interface SettingView {
  name: string;
  value: unknown;
  widget: "text" | "dropdown" | "number" | "multiline";
  options: unknown[] | null;
  range: [number, number] | null;
}

export interface NodeView {
  id: string;
  component: string;
  title: string;
  state: NodeState | null;
  position: [number, number];
  display: Display;
  inputs: PortView[];
  outputs: PortView[];
  value?: unknown;
  min?: number;
  max?: number;
  step?: number;
  size?: [number, number] | null;
  source?: string;
  version?: string | null;
  based_on?: string | null;
  modified?: boolean;
  parse_error?: string | null;
  category?: string | null;
  icon?: string | null;
  settings?: SettingView[];
}

export interface WireJson {
  from: [string, string];
  to: [string, string];
}

export interface ViewJson {
  display?: "text" | "icon";
  zoom?: number;
  offset?: [number, number];
}

export interface GroupJson {
  title: string;
  nodes: string[];
}

export interface WorkflowJson {
  nodes: NodeJson[];
  wires: WireJson[];
  groups: GroupJson[];
  view: ViewJson;
}

/** One node as the .geoknit file stores it (SPEC 5). */
export type NodeJson = { id: string; position: [number, number] } & Record<string, unknown>;

export interface GraphView {
  workflow: WorkflowJson;
  nodes: Record<string, NodeView>;
  out_of_date: number;
  path: string | null;
  trusted: boolean;
  running: boolean;
  /** Differs from its file (any content, for a new workflow). */
  dirty: boolean;
  can_undo: boolean;
  can_redo: boolean;
  /** An autosave from an earlier session can be restored. */
  recovery: boolean;
}

export interface ComponentEntry {
  ref: string;
  version: string;
  origin: string;
  name: string;
  category: string;
  icon: string | null;
  description: string;
  inputs: PortView[];
  outputs: PortView[];
  requires: string[];
  settings: SettingView[];
}

export interface FileNode {
  name: string;
  path: string;
  kind: "dir" | "file";
  children?: FileNode[];
}

export interface Status {
  python: string;
  worker: "idle" | "running";
  pid: number | null;
}

export interface NodeOutput {
  state: NodeState | null;
  log: string[];
  error: string | null;
  outputs: Record<string, string>;
}

export interface RunReport {
  ran: string[];
  cached: string[];
  failed: string[];
  skipped: string[];
  ok: boolean;
}

export type ServerEvent =
  | { type: "states"; states: Record<string, NodeState>; out_of_date: number }
  | { type: "started"; node: string }
  | { type: "log"; node: string; line: string }
  | {
      type: "done";
      node: string;
      outputs: Record<string, string>;
      cached: boolean;
    }
  | { type: "error" | "skipped"; node: string; traceback: string }
  | { type: "run_finished"; report: RunReport | null; error?: string }
  | { type: "workflow_opened"; path: string }
  | { type: "node_changed"; node: string }
  | ({ type: "worker" } & Status);

/** A port as PATCH /api/nodes/{id} `ports` takes it; `was` renames (wires follow). */
export interface PortEdit {
  name: string;
  type: PortType;
  access?: "item" | "list";
  file?: string | null;
  was?: string;
}

export interface NodePatch {
  settings?: Record<string, unknown>;
  source?: string;
  ports?: { inputs: PortEdit[]; outputs: PortEdit[] };
  position?: [number, number];
  display?: Display;
  value?: unknown;
  min?: number;
  max?: number;
  step?: number;
  size?: [number, number] | null;
}
