// Map Viewer logic without MapLibre (SPEC 8): styles, tile URLs, legends, bounds.

import type { Basemap, ColormapJson, LayerStyle, MapLayer, RasterStats } from "../../apiTypes";
import { DEFAULT_VECTOR_COLOUR } from "../../palettes";
import type { Theme } from "../../theme";

export const CATEGORICAL = "categorical";

export const STYLE_DEFAULTS: LayerStyle = {
  bands: [1],
  colormap: "viridis",
  min: null,
  max: null,
  opacity: 1,
  visible: true,
  color: DEFAULT_VECTOR_COLOUR,
};

/** The server's defaults for this layer, overridden by what the user saved. */
export function effectiveStyle(layer: MapLayer, saved?: Partial<LayerStyle>): LayerStyle {
  const defaults = layer.raster?.default_style ?? layer.vector?.default_style ?? {};
  return { ...STYLE_DEFAULTS, ...defaults, ...(saved ?? {}) };
}

/** The basemap drawn: `auto` follows the theme. */
export type ShownBasemap = "light" | "dark" | "none";

export function resolveBasemap(basemap: Basemap, theme: Theme): ShownBasemap {
  return basemap === "auto" ? theme : basemap;
}

/** MapLibre raster paint of the OpenStreetMap basemap. Both use the same tiles: light is
 * greyed, dark inverts the brightness and turns the hues back (no CSS filter, which would
 * also recolour the data layers). Every property is set in both, so a switch resets it. */
export const BASEMAP_PAINT: Record<"light" | "dark", Record<string, number>> = {
  light: {
    "raster-saturation": -0.85,
    "raster-brightness-min": 0.25,
    "raster-brightness-max": 1,
    "raster-contrast": -0.15,
    "raster-hue-rotate": 0,
  },
  dark: {
    "raster-saturation": -0.7,
    "raster-brightness-min": 1,
    "raster-brightness-max": 0,
    "raster-contrast": -0.15,
    "raster-hue-rotate": 180,
  },
};

export const isRgb = (style: LayerStyle): boolean => style.bands.length === 3;

/** A Colormap object (change 03) rather than a ramp name or `categorical`. */
export const isColormap = (colormap: LayerStyle["colormap"]): colormap is ColormapJson =>
  typeof colormap === "object" && colormap !== null;

/** One band drawn as classes: the categorical palette or a classes Colormap. */
export function showsClasses(style: LayerStyle): boolean {
  if (isRgb(style)) return false;
  const c = style.colormap;
  return isColormap(c) ? c.kind === "classes" : c === CATEGORICAL;
}

export const bandsKey = (key: string, bands: number[]): string => `${key}|${bands.join(",")}`;

/** Statistics for the bands the layer shows: from the layer itself, or fetched for other bands. */
export function statsFor(
  layer: MapLayer,
  style: LayerStyle,
  fetched: Record<string, RasterStats>,
): RasterStats | null {
  const raster = layer.raster;
  if (!raster || !layer.key) return null;
  const defaults = raster.default_style.bands ?? [1];
  if (defaults.join(",") === style.bands.join(",")) return raster.stats;
  return fetched[bandsKey(layer.key, style.bands)] ?? null;
}

/** Min / max the tiles use: the saved numbers, else the 2–98 % stretch. */
export function range(style: LayerStyle, stats: RasterStats | null): [number, number] | null {
  const lo = style.min ?? stats?.min;
  const hi = style.max ?? stats?.max;
  return lo === undefined || hi === undefined ? null : [lo, hi];
}

/** `/tiles/{key}/{z}/{x}/{y}.png?…`; without min/max the server stretches 2–98 %.
 * A Colormap object goes as `cmap` (compact JSON), which replaces `colormap`. */
export function tileUrl(key: string, style: LayerStyle): string {
  const c = style.colormap;
  const q = new URLSearchParams({ bands: style.bands.join(",") });
  if (isColormap(c)) q.set("cmap", JSON.stringify(c));
  else q.set("colormap", c);
  if (style.min !== null) q.set("min", String(style.min));
  if (style.max !== null) q.set("max", String(style.max));
  return `/tiles/${key}/{z}/{x}/{y}.png?${q.toString()}`;
}

export const vectorUrl = (key: string): string => `/api/vector/${key}.geojson`;

/** A legend row; without `label` the row reads "class <value>". */
export interface LegendClass {
  value: number;
  color: string;
  label?: string;
}

export type Legend =
  /** `positions` (0–1, one per colour) only for custom stops; else evenly spaced. */
  | { kind: "ramp"; colours: string[]; positions?: number[]; min: number; max: number }
  /** `other`: the colour of values not listed (a classes Colormap's `other`). */
  | { kind: "classes"; classes: LegendClass[]; other?: string }
  | { kind: "rgb"; bands: string[]; min: number; max: number }
  | { kind: "vector"; colour: string };

export function legendFor(
  layer: MapLayer,
  style: LayerStyle,
  stats: RasterStats | null,
  colormaps: Record<string, string[]>,
): Legend | null {
  if (layer.vector) return { kind: "vector", colour: style.color };
  const raster = layer.raster;
  if (!raster) return null;
  const cm = !isRgb(style) && isColormap(style.colormap) ? style.colormap : null;
  if (cm?.kind === "classes") {
    const classes = cm.classes.map(([value, color, label]) => ({
      value,
      color,
      label: label === "" ? formatValue(value) : label,
    }));
    return cm.other === null ? { kind: "classes", classes } : { kind: "classes", classes, other: cm.other };
  }
  if (!isRgb(style) && style.colormap === CATEGORICAL) {
    return stats?.classes ? { kind: "classes", classes: stats.classes } : null;
  }
  const r = range(style, stats);
  if (cm) {
    // the Colormap's own min/max win, as in the tiles
    const lo = cm.min ?? r?.[0];
    const hi = cm.max ?? r?.[1];
    if (lo === undefined || hi === undefined) return null;
    return { kind: "ramp", ...rampColours(cm, colormaps), min: lo, max: hi };
  }
  if (!r) return null;
  if (isRgb(style)) {
    return {
      kind: "rgb",
      bands: style.bands.map((b) => raster.bands[b - 1] ?? `band ${b}`),
      min: r[0],
      max: r[1],
    };
  }
  const name = isColormap(style.colormap) ? "" : style.colormap;
  return { kind: "ramp", colours: colormaps[name] ?? [], min: r[0], max: r[1] };
}

/** Colours of a continuous Colormap, low to high: its stops, or its named ramp's. */
function rampColours(
  cm: Extract<ColormapJson, { kind: "continuous" }>,
  colormaps: Record<string, string[]>,
): { colours: string[]; positions?: number[] } {
  if (!cm.stops) {
    const named = colormaps[cm.name ?? ""] ?? [];
    return { colours: cm.reverse ? [...named].reverse() : named };
  }
  const stops = cm.reverse ? cm.stops.map(([p, c]) => [1 - p, c] as const).reverse() : cm.stops;
  return { colours: stops.map(([, c]) => c), positions: stops.map(([p]) => p) };
}

/** CSS `linear-gradient` stops of a ramp legend. */
export function gradientStops(legend: Extract<Legend, { kind: "ramp" }>): string {
  const { colours, positions } = legend;
  return colours.map((c, i) => (positions ? `${c} ${positions[i] * 100}%` : c)).join(", ");
}

/** Bounds of every layer that can be drawn, as [west, south, east, north]. */
export function unionBounds(layers: MapLayer[]): [number, number, number, number] | null {
  let out: [number, number, number, number] | null = null;
  for (const l of layers) {
    if (l.status !== "ready") continue;
    const b = l.raster?.bounds ?? l.vector?.bounds ?? null;
    if (!b) continue;
    out = out
      ? [Math.min(out[0], b[0]), Math.min(out[1], b[1]), Math.max(out[2], b[2]), Math.max(out[3], b[3])]
      : [...b];
  }
  return out;
}

/** What MapCanvas draws, top layer first: vectors above rasters, then wire order. */
export type RenderLayer =
  | {
      id: string;
      kind: "raster";
      url: string;
      bounds: [number, number, number, number];
      opacity: number;
      visible: boolean;
      nearest: boolean;
    }
  | {
      id: string;
      kind: "vector";
      url: string;
      colour: string;
      opacity: number;
      visible: boolean;
    };

export function renderLayers(
  layers: MapLayer[],
  styles: Record<string, Partial<LayerStyle>>,
): RenderLayer[] {
  const out: RenderLayer[] = [];
  for (const l of layers) {
    if (l.status !== "ready" || !l.key) continue;
    const style = effectiveStyle(l, styles[l.id]);
    if (l.raster) {
      out.push({
        id: l.id,
        kind: "raster",
        url: tileUrl(l.key, style),
        bounds: l.raster.bounds,
        opacity: style.opacity,
        visible: style.visible,
        nearest: showsClasses(style),
      });
    } else if (l.vector) {
      out.push({
        id: l.id,
        kind: "vector",
        url: vectorUrl(l.key),
        colour: style.color,
        opacity: style.opacity,
        visible: style.visible,
      });
    }
  }
  // points and outlines would vanish under an opaque raster
  return [...out.filter((l) => l.kind === "vector"), ...out.filter((l) => l.kind === "raster")];
}

/** Short number for legends and the inspect panel. */
export function formatValue(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "–";
  if (Number.isInteger(v)) return String(v);
  return String(Number(v.toPrecision(5)));
}
