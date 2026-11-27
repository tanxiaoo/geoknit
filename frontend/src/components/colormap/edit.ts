// Colormap editor logic without React (change 03, section 2): stops, classes, paste, fill.

import type { ColormapJson } from "../../apiTypes";
import { FALLBACK_COLOR_VALUE, NEW_CLASS_COLOURS } from "../../palettes";
import { strings } from "../../strings";

export type Stop = [number, string];
export type ClassRow = [number, string, string];
export type Continuous = Extract<ColormapJson, { kind: "continuous" }>;
export type Classes = Extract<ColormapJson, { kind: "classes" }>;

const HEX = /^#?([0-9a-f]{6}|[0-9a-f]{8})$/i;

/** ``#rrggbb`` / ``#rrggbbaa`` (the ``#`` may be left out) upper case, else null. */
export function normHex(text: string): string | null {
  const m = HEX.exec(text.trim());
  return m ? `#${m[1].toUpperCase()}` : null;
}

function channels(hex: string): number[] {
  const h = hex.slice(1);
  const out = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  out.push(h.length === 8 ? parseInt(h.slice(6, 8), 16) : 255);
  return out;
}

function toHex(ch: number[]): string {
  const [r, g, b, a] = ch.map((c) => Math.round(Math.min(255, Math.max(0, c))));
  const parts = a === 255 ? [r, g, b] : [r, g, b, a];
  return `#${parts.map((c) => c.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

/** A stop position rounded to 3 decimals and kept inside 0…1. */
export const clampPos = (p: number): number => Math.round(Math.min(1, Math.max(0, p)) * 1000) / 1000;

/** The colour of a ramp at ``p`` (0…1), linear between the stops (sorted by position). */
export function colourAt(stops: Stop[], p: number): string {
  if (!stops.length) return NEW_CLASS_COLOURS[0];
  if (p <= stops[0][0]) return normHex(stops[0][1]) ?? stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [p1, c1] = stops[i];
    if (p <= p1) {
      const [p0, c0] = stops[i - 1];
      const t = p1 === p0 ? 1 : (p - p0) / (p1 - p0);
      const a = channels(normHex(c0) ?? FALLBACK_COLOR_VALUE);
      const b = channels(normHex(c1) ?? FALLBACK_COLOR_VALUE);
      return toHex(a.map((v, k) => v + (b[k] - v) * t));
    }
  }
  const last = stops[stops.length - 1][1];
  return normHex(last) ?? last;
}

/** Evenly spaced stops of a named ramp's colours. */
export const evenStops = (colours: string[]): Stop[] =>
  colours.map((c, i) => [clampPos(i / Math.max(1, colours.length - 1)), c]);

/** ``n`` colours sampled evenly along a ramp (one colour: its start). */
export function sampleRamp(colours: string[], n: number): string[] {
  const stops = evenStops(colours);
  return Array.from({ length: n }, (_, i) => colourAt(stops, n === 1 ? 0 : i / (n - 1)));
}

// ── continuous stops ──

/** Add a stop at ``p`` with the ramp's colour there; returns the stops and its index. */
export function addStop(stops: Stop[], p: number): { stops: Stop[]; index: number } {
  const pos = clampPos(p);
  const stop: Stop = [pos, colourAt(stops, pos)];
  const index = stops.findIndex(([q]) => q > pos);
  const at = index === -1 ? stops.length : index;
  return { stops: [...stops.slice(0, at), stop, ...stops.slice(at)], index: at };
}

/** Move stop ``index`` to ``p``, keeping the stops in order; returns where it went. */
export function moveStop(stops: Stop[], index: number, p: number): { stops: Stop[]; index: number } {
  const moved: Stop = [clampPos(p), stops[index][1]];
  const rest = stops.filter((_, i) => i !== index);
  const at = rest.findIndex(([q]) => q > moved[0]);
  const to = at === -1 ? rest.length : at;
  return { stops: [...rest.slice(0, to), moved, ...rest.slice(to)], index: to };
}

/** Remove a stop; a ramp keeps at least two. */
export function removeStop(stops: Stop[], index: number): Stop[] {
  return stops.length <= 2 ? stops : stops.filter((_, i) => i !== index);
}

export function setStopColour(stops: Stop[], index: number, hex: string): Stop[] {
  return stops.map((s, i) => (i === index ? [s[0], hex] : s));
}

// ── classes ──

/** A new class after the others: the next whole value and a colour from the palette. */
export function addClass(classes: ClassRow[]): ClassRow[] {
  const values = classes.map(([v]) => v);
  const value = values.length ? Math.floor(Math.max(...values)) + 1 : 1;
  const colour = NEW_CLASS_COLOURS[classes.length % NEW_CLASS_COLOURS.length];
  return [...classes, [value, colour, ""]];
}

/** Remove a class; a classes colormap keeps at least one. */
export function removeClass(classes: ClassRow[], index: number): ClassRow[] {
  return classes.length <= 1 ? classes : classes.filter((_, i) => i !== index);
}

/** Move class ``index`` up (-1) or down (+1). */
export function moveClass(classes: ClassRow[], index: number, delta: -1 | 1): ClassRow[] {
  const to = index + delta;
  if (to < 0 || to >= classes.length) return classes;
  const out = [...classes];
  [out[index], out[to]] = [out[to], out[index]];
  return out;
}

export function setClass(
  classes: ClassRow[],
  index: number,
  row: Partial<{ value: number; colour: string; label: string }>,
): ClassRow[] {
  return classes.map((c, i) =>
    i === index ? [row.value ?? c[0], row.colour ?? c[1], row.label ?? c[2]] : c,
  );
}

/** "Fill colours from ramp": the listed values, in order, get colours along the ramp. */
export function fillFromRamp(classes: ClassRow[], colours: string[]): ClassRow[] {
  const picked = sampleRamp(colours, classes.length);
  return classes.map(([v, , label], i) => [v, picked[i], label]);
}

/** Lines of ``value, #hex, label`` (tab or comma separated; the label may be left out and
 * may hold commas). Blank lines are skipped and a first line that is not a class (a header)
 * is ignored. Null when nothing else reads as a class table. */
export function parseClassTable(text: string): ClassRow[] | null {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() !== "");
  const rows: ClassRow[] = [];
  for (const [i, line] of lines.entries()) {
    const sep = line.includes("\t") ? "\t" : ",";
    const [first, second = "", ...rest] = line.split(sep);
    const value = first.trim() === "" ? NaN : Number(first);
    const colour = normHex(second);
    if (!Number.isFinite(value) || !colour) {
      if (i === 0) continue; // a header row
      return null;
    }
    rows.push([value, colour, rest.join(sep).trim()]);
  }
  return rows.length ? rows : null;
}

// ── kinds and checks ──

/** A classes colormap to start from: one class in the ramp's first colour. */
export function startClasses(stops: Stop[] | null): Classes {
  const colour = stops ? colourAt(stops, 0) : NEW_CLASS_COLOURS[0];
  return { kind: "classes", classes: [[1, colour, ""]], other: null };
}

export const START_CONTINUOUS: Continuous = {
  kind: "continuous",
  name: "viridis",
  min: null,
  max: null,
  reverse: false,
};

/** Why the server would refuse this colormap (checked first so the editor stays in step). */
export function problem(cm: ColormapJson): string | null {
  if (cm.kind === "classes") {
    if (!cm.classes.length) return strings.cmNeedsClass;
    const values = cm.classes.map(([v]) => v);
    if (new Set(values).size !== values.length) return strings.cmValueTwice;
    return null;
  }
  if (cm.min !== null && cm.max !== null && cm.min >= cm.max) return strings.cmMinBelowMax;
  return null;
}
