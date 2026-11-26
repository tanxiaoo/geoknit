// Data-type and category colours (SPEC 3, SPEC 8) and the connection rules (SPEC 3).

import type { NodeState, PortType } from "./apiTypes";

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

/** Types offered by the port editor: Layer comes only from Map Layer (change 03). */
export const EDITABLE_PORT_TYPES = DATA_TYPES.filter((t) => t !== "Layer");

export const PORT_COLOURS: Record<PortType, string> = {
  Number: "#64748B",
  Text: "#A16207",
  Raster: "#0B7A7C",
  Vector: "#C2410C",
  Table: "#7C3AED",
  Model: "#BE185D",
  Boolean: "#0369A1",
  Color: "#4D7C0F",
  Colormap: "#4338CA",
  Layer: "#A21CAF",
  Any: "#64748B",
};

export const CATEGORY_COLOURS: Record<string, string> = {
  Params: "#475569",
  Raster: "#0B7A7C",
  Vector: "#C2410C",
  Sampling: "#7C3AED",
  Model: "#BE185D",
  Validation: "#15803D",
  Script: "#475569",
};

export const CATEGORY_ORDER = ["Params", "Raster", "Vector", "Sampling", "Model", "Validation", "Script"];

export function categoryColour(category: string | null | undefined): string {
  return (category && CATEGORY_COLOURS[category]) || "#475569";
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

/** Nodes that still need a run show the orange dot. */
export function needsRun(state: NodeState | null | undefined): boolean {
  return state !== "done" && state !== "running";
}

export const PARAM_TEXT = "param/text";
export const PARAM_SLIDER = "param/slider";
export const PARAM_PANEL = "param/panel";
export const PARAM_MAP = "param/map";
