// Map Viewer logic without MapLibre (SPEC 8): styles, tile URLs, legends, bounds.

import type { LayerStyle, MapClass, MapLayer, RasterStats } from "../../apiTypes";
import { DEFAULT_VECTOR_COLOUR } from "../../palettes";

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

export const isRgb = (style: LayerStyle): boolean => style.bands.length === 3;

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

/** `/tiles/{key}/{z}/{x}/{y}.png?…`; without min/max the server stretches 2–98 %. */
export function tileUrl(key: string, style: LayerStyle): string {
  const q = new URLSearchParams({ bands: style.bands.join(","), colormap: style.colormap });
  if (style.min !== null) q.set("min", String(style.min));
  if (style.max !== null) q.set("max", String(style.max));
  return `/tiles/${key}/{z}/{x}/{y}.png?${q.toString()}`;
}

export const vectorUrl = (key: string): string => `/api/vector/${key}.geojson`;

export type Legend =
  | { kind: "ramp"; colours: string[]; min: number; max: number }
  | { kind: "classes"; classes: MapClass[] }
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
  if (!isRgb(style) && style.colormap === CATEGORICAL) {
    return stats?.classes ? { kind: "classes", classes: stats.classes } : null;
  }
  const r = range(style, stats);
  if (!r) return null;
  if (isRgb(style)) {
    return {
      kind: "rgb",
      bands: style.bands.map((b) => raster.bands[b - 1] ?? `band ${b}`),
      min: r[0],
      max: r[1],
    };
  }
  return { kind: "ramp", colours: colormaps[style.colormap] ?? [], min: r[0], max: r[1] };
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
        nearest: !isRgb(style) && style.colormap === CATEGORICAL,
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
