// What can be added to the canvas: Params nodes plus the component library.

import type { ComponentEntry, PortType } from "./apiTypes";
import { strings } from "./strings";
import {
  CATEGORY_ORDER,
  canConnect,
  PARAM_MAP,
  PARAM_PANEL,
  PARAM_SLIDER,
  PARAM_TEXT,
} from "./types";

const PORT_NAMES: Record<string, string> = {
  [PARAM_PANEL]: "data",
  [PARAM_MAP]: "layers",
};

function param(ref: string, name: string, inputs: PortType[], outputs: PortType[]): ComponentEntry {
  const port = (t: PortType, n: string) => ({
    name: n,
    type: t,
    access: ref === PARAM_MAP ? ("list" as const) : ("item" as const),
  });
  return {
    ref,
    version: "",
    origin: "param",
    name,
    category: "Params",
    icon: null,
    description: "",
    inputs: inputs.map((t) => port(t, PORT_NAMES[ref] ?? "value")),
    outputs: outputs.map((t) => port(t, PORT_NAMES[ref] ?? "value")),
    requires: [],
    settings: [],
  };
}

export function paramEntries(): ComponentEntry[] {
  return [
    param(PARAM_SLIDER, strings.numberSlider, [], ["Number"]),
    param(PARAM_TEXT, strings.text, [], ["Text"]),
    param(PARAM_PANEL, strings.panel, ["Any"], ["Any"]),
    param(PARAM_MAP, strings.mapViewer, ["Any"], []),
  ];
}

export function allEntries(library: ComponentEntry[]): ComponentEntry[] {
  return [...paramEntries(), ...library];
}

/** Ribbon tabs: Params, the built-in categories in SPEC order, then pack categories. */
export function categories(library: ComponentEntry[]): string[] {
  const found = new Set(library.map((c) => c.category));
  const known = CATEGORY_ORDER.filter((c) => c === "Params" || found.has(c));
  const extra = [...found].filter((c) => !CATEGORY_ORDER.includes(c)).sort();
  return [...known, ...extra];
}

export function matches(entry: ComponentEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [entry.name, entry.category, entry.description, entry.ref].some((s) =>
    s.toLowerCase().includes(q),
  );
}

/** A port a new node should be wired to when dropped from a dragged wire. */
export interface WireFrom {
  nodeId: string;
  port: string;
  side: "in" | "out";
  type: PortType;
}

/** The port on ``entry`` that fits ``from``, or null. */
export function fittingPort(entry: ComponentEntry, from: WireFrom): string | null {
  if (from.side === "out") {
    return entry.inputs.find((p) => canConnect(from.type, p.type))?.name ?? null;
  }
  return entry.outputs.find((p) => canConnect(p.type, from.type))?.name ?? null;
}
