// Shapes of the GeoKnit server API (SPEC 9).

export type PortType =
  | "Number"
  | "Text"
  | "Raster"
  | "Vector"
  | "Table"
  | "Model"
  | "Boolean"
  | "Color"
  | "Colormap"
  | "Layer"
  | "Any";
export type NodeState = "never_run" | "out_of_date" | "running" | "done" | "error" | "skipped";
export type Display = "default" | "text" | "icon";

export interface PortView {
  name: string;
  /** The first listed type. */
  type: PortType;
  /** Every type an input accepts (SPEC 3); one element for an ordinary port. */
  types?: PortType[];
  access: "item" | "list";
  file?: string | null;
  /** Output only: the input whose wired type it follows (`{like: data}`). */
  like?: string | null;
  /** Output only (`/api/graph`): the type the graph resolved, null while unresolved. */
  resolved_type?: PortType | null;
  /** Output only (`/api/graph`): "list" when the output carries a list, also a Panel
   * passing one through (SPEC 3 "List values"). */
  resolved_access?: "item" | "list";
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
  /** Number and Number Slider: whole numbers only (change 01, section 2). */
  integer?: boolean;
  /** Value List: its options; the chosen one is `value` (change 01, section 8). */
  options?: ValueOption[];
  size?: [number, number] | null;
  source?: string;
  version?: string | null;
  based_on?: string | null;
  modified?: boolean;
  parse_error?: string | null;
  category?: string | null;
  icon?: string | null;
  settings?: SettingView[];
  /** The header's `ports:` key; `null` when the ports cannot be edited (SPEC 4). */
  editable_ports?: EditablePorts | null;
  /** Map Viewer: saved basemap and per-layer styles (SPEC 8). */
  map?: MapSettings;
}

/** One option of a Value List: a number or text value under a label. */
export interface ValueOption {
  label: string;
  value: number | string;
}

/** A Colormap as the API and the workflow file give it (`Colormap.to_json()`, change 01).
 * A named ramp's `stops` are left out: they follow from `name` (`GET /api/colormaps`). */
export type ColormapJson =
  | {
      kind: "continuous";
      name: string | null;
      stops?: [number, string][];
      min: number | null;
      max: number | null;
      reverse: boolean;
    }
  | { kind: "classes"; classes: [number, string, string][]; other: string | null };

/** `GET /api/colormaps`: the named ramps, 11 `#RRGGBB` stops each, low to high. */
export type NamedRamps = Record<string, string[]>;

/** Which sides of a component the Settings tab edits, and the types it offers. */
export interface EditablePorts {
  inputs: boolean;
  outputs: boolean;
  /** The first is a new port's type. */
  types: PortType[];
  /** The types offered for inputs: `types`, plus `Any` when the header lists no types. */
  input_types?: PortType[];
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
  /** The ribbon tab. */
  category: string;
  /** The group inside the tab ("Other" for a pack component without `group:`). */
  group: string;
  icon: string | null;
  description: string;
  inputs: PortView[];
  outputs: PortView[];
  requires: string[];
  settings: SettingView[];
  editable_ports?: EditablePorts | null;
}

/** A ribbon tab: its centre-strip colour and its groups in order (change 01, section 7). */
export interface TabView {
  name: string;
  colour: string;
  groups: string[];
}

/** `GET /api/components`: components and Params nodes in ribbon order, and the tabs. */
export interface Library {
  components: ComponentEntry[];
  tabs: TabView[];
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
  types?: PortType[];
  like?: string | null;
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
  integer?: boolean;
  options?: ValueOption[];
  size?: [number, number] | null;
  map?: { basemap?: Basemap; styles?: Record<string, Partial<LayerStyle> | null> };
}

// ── Map Viewer (SPEC 8, 9) ──

export type Basemap = "light" | "none";

/** A layer's look; `color` is for vectors, the rest for rasters. */
export interface LayerStyle {
  bands: number[];
  colormap: string;
  min: number | null;
  max: number | null;
  opacity: number;
  visible: boolean;
  color: string;
}

export interface MapSettings {
  basemap?: Basemap;
  styles?: Record<string, Partial<LayerStyle>>;
}

export interface MapClass {
  value: number;
  color: string;
}

export interface RasterStats {
  min: number;
  max: number;
  classes: MapClass[] | null;
}

export interface RasterInfo {
  bands: string[];
  dtype: string;
  width: number;
  height: number;
  nodata: number | null;
  crs: string;
  bounds: [number, number, number, number];
  stats: RasterStats;
  default_style: Partial<LayerStyle>;
}

export interface VectorInfo {
  features: number;
  shown: number;
  geometry: string[];
  columns: string[];
  crs: string;
  bounds: [number, number, number, number] | null;
  default_style: Partial<LayerStyle>;
}

export type LayerStatus = "ready" | "not_run" | "no_cache" | "unsupported" | "error";

export interface MapLayer {
  /** `<source node id>.<port>` */
  id: string;
  title: string;
  source: [string, string];
  key: string | null;
  status: LayerStatus;
  message: string | null;
  type: PortType | null;
  raster?: RasterInfo;
  vector?: VectorInfo;
  style?: Partial<LayerStyle>;
}

export interface MapView {
  basemap: Basemap;
  layers: MapLayer[];
  basemaps: Basemap[];
  /** A few colours of each colormap, low to high. */
  colormaps: Record<string, string[]>;
  max_features: number;
}

export interface InspectLayer {
  id: string;
  title: string;
  outside: boolean;
  values: { band: string; value: number | null }[];
}

export interface InspectResult {
  lon: number;
  lat: number;
  layers: InspectLayer[];
}

/** `POST /api/export/py` (SPEC 10). `path` is set when the script was written. */
export interface ExportResult {
  script: string;
  path: string | null;
  warnings: string[];
}
