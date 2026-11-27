// Map Layer window logic without React (change 03, section 3).

import type { ColormapJson, GraphView, MapLayerBuild, MapLayerStyle } from "../../apiTypes";
import { strings } from "../../strings";

/** The style inputs of a Map Layer, in window order (`field` has no port). */
export const STYLE_INPUTS = ["colormap", "color", "opacity", "bands", "name"] as const;
export type StyleInput = (typeof STYLE_INPUTS)[number];
export type StyleField = keyof MapLayerStyle;

/** A field's label in the window and in its issue line. */
export function fieldLabel(field: StyleField | "data"): string {
  switch (field) {
    case "data":
      return strings.layerData;
    case "colormap":
      return strings.colormap;
    case "color":
      return strings.colour;
    case "opacity":
      return strings.opacity;
    case "bands":
      return strings.layerBands;
    case "name":
      return strings.layerName;
    case "field":
      return strings.layerField;
  }
}

/** The ramp name of a colormap that is just a named ramp (what the dropdown can show), else
 * null (custom stops, reversed, fixed min/max, or classes). */
export function plainRamp(cm: ColormapJson | undefined | null): string | null {
  if (!cm || cm.kind !== "continuous" || !cm.name || cm.stops) return null;
  if (cm.reverse || (cm.min ?? null) !== null || (cm.max ?? null) !== null) return null;
  return cm.name;
}

/** Where a wired style input's value comes from: the title of the node wired into it, or
 * null when the input is not wired or its value is not used (it counts as unwired). */
export function wiredFrom(
  graph: GraphView | null,
  build: MapLayerBuild | null | undefined,
  nodeId: string,
  input: StyleInput,
): string | null {
  const how = build?.wired[input];
  if (!how || !graph) return null;
  const wire = graph.workflow.wires.find((w) => w.to[0] === nodeId && w.to[1] === input);
  const title = (wire && graph.nodes[wire.from[0]]?.title) ?? input;
  return how === "component" ? strings.layerFromResult(title) : strings.layerFrom(title);
}

/** Which fields the window shows for a layer of ``kind`` (unknown before the data's type is):
 * bands for rasters, colour and field for vectors; a wired one always. */
export function shownFields(
  kind: "raster" | "vector" | null,
  wired: Partial<Record<string, unknown>>,
): StyleField[] {
  const out: StyleField[] = [];
  for (const f of [...STYLE_INPUTS, "field"] as const) {
    const relevant =
      f === "bands"
        ? kind !== "vector"
        : f === "color"
          ? kind !== "raster"
          : f === "field"
            ? kind === "vector"
            : true;
    if (relevant || (f !== "field" && wired[f])) out.push(f);
  }
  return out;
}

/** Opacity rounded to two decimals, kept inside 0…1. */
export const clampOpacity = (v: number): number =>
  Math.round(Math.min(1, Math.max(0, v)) * 100) / 100;

/** A wired value as the window shows it read-only. */
export function shownValue(value: unknown): string {
  if (value === null || value === undefined) return strings.layerDefault;
  if (Array.isArray(value)) return value.join(",");
  if (typeof value === "number") return String(Number(value.toFixed(3)));
  return String(value);
}
