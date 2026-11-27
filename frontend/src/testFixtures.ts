// Test data: the Params nodes as `GET /api/components` lists them (change 01, section 7).

import type { ComponentEntry, PortView } from "./apiTypes";

function port(name: string, type: PortView["type"], extra: Partial<PortView> = {}): PortView {
  return { name, type, types: [type], access: "item", ...extra };
}

function param(
  ref: string,
  name: string,
  group: string,
  inputs: PortView[],
  outputs: PortView[],
): ComponentEntry {
  return {
    ref,
    version: "",
    origin: "param",
    name,
    category: "Params",
    group,
    icon: ref === "param/map" ? "gis:map" : null,
    description: "",
    inputs,
    outputs,
    requires: [],
    settings: [],
    editable_ports: null,
  };
}

export const PARAM_ENTRIES: ComponentEntry[] = [
  param("param/text", "Text", "Input", [], [port("value", "Text", { like: null })]),
  param("param/number", "Number", "Input", [], [port("value", "Number", { like: null })]),
  param("param/slider", "Number Slider", "Input", [], [port("value", "Number", { like: null })]),
  param("param/toggle", "Boolean Toggle", "Input", [], [port("value", "Boolean", { like: null })]),
  param("param/value_list", "Value List", "Input", [], [port("value", "Number", { like: null })]),
  param("param/color", "Color Swatch", "Style", [], [port("value", "Color", { like: null })]),
  param("param/colormap", "Colormap", "Style", [], [port("value", "Colormap", { like: null })]),
  param("param/panel", "Panel", "Inspect", [port("data", "Any")], [port("data", "Any", { like: "data" })]),
  param("param/map", "Map Viewer", "Map", [port("layers", "Any", { access: "list" })], []),
];

export function paramEntry(ref: string): ComponentEntry {
  const found = PARAM_ENTRIES.find((e) => e.ref === ref);
  if (!found) throw new Error(`no Params entry ${ref}`);
  return found;
}
