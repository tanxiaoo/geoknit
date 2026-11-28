// Data-type colours and category colour lookup (SPEC 3, SPEC 8) and the connection rules (SPEC 3).

import type { GraphView, NodeState, PortType, PortView, TabView } from "./apiTypes";
import { strings } from "./strings";

export const DATA_TYPES: Exclude<PortType, "Any">[] = [
  "Number",
  "Text",
  "Raster",
  "Vector",
  "Table",
  "Model",
  "Boolean",
  "Color",
  "Colormap",
  "Layer",
];

/** CSS colours of the data types: tokens of theme.css, usable in inline styles. */
export const PORT_COLOURS: Record<PortType, string> = {
  Number: "var(--gk-type-number)",
  Text: "var(--gk-type-text)",
  Raster: "var(--gk-type-raster)",
  Vector: "var(--gk-type-vector)",
  Table: "var(--gk-type-table)",
  Model: "var(--gk-type-model)",
  Boolean: "var(--gk-type-boolean)",
  Color: "var(--gk-type-color)",
  Colormap: "var(--gk-type-colormap)",
  Layer: "var(--gk-type-layer)",
  Any: "var(--gk-type-any)",
};

/** Centre strip of a category that is not a tab (an inline component's own category). */
export const OTHER_CATEGORY_COLOUR = "var(--gk-cat-other)";

/** A category's colour from the `tabs` of `GET /api/components` (change 01, section 7). */
export function categoryColour(tabs: TabView[], category: string | null | undefined): string {
  return tabs.find((t) => t.name === category)?.colour ?? OTHER_CATEGORY_COLOUR;
}

/** SPEC 3: same type, an `Any` input, Number/Boolean → Text, or an `Any` output. */
export function canConnect(out: PortType, input: PortType): boolean {
  return (
    out === input ||
    input === "Any" ||
    out === "Any" ||
    (input === "Text" && (out === "Number" || out === "Boolean"))
  );
}

/** The types a port can carry: the server's `resolved_types` for a graph output (the
 * same set its wiring checks use), else the resolved type, else the declared ones. */
export function portTypes(p: PortView): PortType[] {
  if (p.resolved_types && p.resolved_types.length) return p.resolved_types;
  if (p.resolved_type) return [p.resolved_type];
  return p.types && p.types.length ? p.types : [p.type];
}

/** `Table | Vector` for a port that accepts several types. */
export function typeLabel(types: PortType[]): string {
  return types.join(" | ");
}

/** SPEC 3: some possible output type fits some listed input type. */
export function canConnectAny(outs: PortType[], ins: PortType[]): boolean {
  return outs.some((o) => ins.some((i) => canConnect(o, i)));
}

/** The refusal tooltip ("Raster can't connect to Table | Vector"), or null if it fits. */
export function connectionError(outs: PortType[], ins: PortType[]): string | null {
  return canConnectAny(outs, ins) ? null : strings.cantConnect(typeLabel(outs), typeLabel(ins));
}

/** SPEC 3 "List values": an output carrying a list (`resolved_access` from `/api/graph`,
 * so a Panel passing a list through counts; else `access`), or an `access: list` input. */
export function carriesList(p: PortView): boolean {
  return (p.resolved_access ?? p.access) === "list";
}

/** The output end of a wire being checked. */
export interface WireSource {
  /** Node title, for the list refusal ("Numbers gives a list; …"). */
  title: string;
  types: PortType[];
  list: boolean;
}

/** The input end of a wire being checked. */
export interface WireTarget {
  name: string;
  types: PortType[];
  access: "item" | "list";
  /** A list input that an output of its node is `like`: the arriving types of the wires
   * already into it (`sameTypeWires`), for the same-type rule. */
  wired?: PortType[][];
}

/** The types a value of `outs` has once it reaches an input of `ins` (Number/Boolean →
 * Text applies; an `Any` output may be any of `ins`), as the server's `_arriving_types`. */
export function arrivingTypes(outs: PortType[], ins: PortType[]): PortType[] {
  const found: PortType[] = [];
  for (const t of outs) {
    let arriving: PortType[] = [];
    if (t === "Any") arriving = ins;
    else if (ins.some((i) => canConnect(t, i)))
      arriving = [ins.includes(t) || ins.includes("Any") ? t : "Text"];
    for (const a of arriving) if (!found.includes(a)) found.push(a);
  }
  return found;
}

/** For the same-type rule (SPEC 3 "List values"): the arriving types of each wire already
 * into `nodeId.input`, when it is a list input that an output of the node is `like`;
 * otherwise undefined (the rule does not apply). */
export function sameTypeWires(
  graph: GraphView,
  nodeId: string,
  input: string,
): PortType[][] | undefined {
  const view = graph.nodes[nodeId];
  const inp = view?.inputs.find((p) => p.name === input);
  if (!view || !inp || inp.access !== "list") return undefined;
  if (!view.outputs.some((o) => o.like === input)) return undefined;
  const ins = inp.types && inp.types.length ? inp.types : [inp.type];
  return graph.workflow.wires
    .filter((w) => w.to[0] === nodeId && w.to[1] === input)
    .map((w) => {
      const src = graph.nodes[w.from[0]]?.outputs.find((o) => o.name === w.from[1]);
      return src ? arrivingTypes(portTypes(src), ins) : [];
    });
}

/** Why a wire is refused, as the server words it (type mismatch first), or null if it fits.
 * A list output only goes into a list input, or into an `Any` item input (Panel) whole;
 * the wires into a list input that an output is `like` must have one type. */
export function wireError(src: WireSource, dst: WireTarget): string | null {
  const problem = connectionError(src.types, dst.types);
  if (problem) return problem;
  const anyItem = dst.types.length === 1 && dst.types[0] === "Any";
  if (src.list && dst.access === "item" && !anyItem) {
    return strings.listIntoItem(src.title, dst.name);
  }
  if (dst.access === "list" && dst.wired) {
    const mine = arrivingTypes(src.types, dst.types);
    const one = (ts: PortType[]) => ts.length === 1 && ts[0] !== "Any";
    if (one(mine) && dst.wired.some((theirs) => one(theirs) && theirs[0] !== mine[0])) {
      return strings.sameTypeInto(dst.name);
    }
  }
  return null;
}

/** A list summary cut for a tooltip: its first line and the first few items. */
export function tipSummary(summary: string, keep = 5): string {
  const lines = summary.split("\n");
  const head = /^list of (\d+)/.exec(lines[0] ?? "");
  if (!head) return summary;
  const items = lines.slice(1).filter((l) => l.startsWith("["));
  if (items.length <= keep) return summary;
  return [lines[0], ...items.slice(0, keep), strings.moreItems(Number(head[1]) - keep)].join("\n");
}

/** Nodes that still need a run show the orange dot. */
export function needsRun(state: NodeState | null | undefined): boolean {
  return state !== "done" && state !== "running";
}

export const PARAM_TEXT = "param/text";
export const PARAM_NUMBER = "param/number";
export const PARAM_SLIDER = "param/slider";
export const PARAM_TOGGLE = "param/toggle";
export const PARAM_VALUE_LIST = "param/value_list";
export const PARAM_COLOR = "param/color";
export const PARAM_COLORMAP = "param/colormap";
export const PARAM_PANEL = "param/panel";
export const PARAM_LAYER = "param/layer";
export const PARAM_MAP = "param/map";
