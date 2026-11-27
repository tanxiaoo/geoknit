// Change 02 (SPEC 3): both theme blocks of theme.css define the same tokens, and the
// colours that carry text or wires meet WCAG contrast ratios in both themes.
//
// theme.css is read from disk (vitest turns imported CSS into an empty string); the
// category strip colours are the server's (`TABS` and `PACK_COLOUR` in
// geoknit/components/layout.py, sent by GET /api/components), read from that file.

import { readFileSync } from "node:fs";
import { cwd } from "node:process";
import { describe, expect, it } from "vitest";

const CSS = readFileSync(`${cwd()}/src/theme.css`, "utf-8").replace(/\/\*[\s\S]*?\*\//g, "");
const LAYOUT = readFileSync(`${cwd()}/../geoknit/components/layout.py`, "utf-8");

/** The `--gk-*` declarations of the block whose selector list contains ``selector``. */
function block(selector: string): Record<string, string> {
  for (const m of CSS.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = m[1].split(",").map((s) => s.trim());
    if (!selectors.includes(selector)) continue;
    const tokens: Record<string, string> = {};
    for (const d of m[2].matchAll(/--gk-([\w-]+)\s*:\s*([^;]+);/g)) tokens[d[1]] = d[2].trim();
    return tokens;
  }
  throw new Error(`no block for ${selector}`);
}

const THEMES = {
  light: block(':root[data-theme="light"]'),
  dark: block(':root[data-theme="dark"]'),
};

/** The category strip colours the server sends (tabs, packs) plus `cat-other`. */
function stripColours(): Record<string, string> {
  const tabs = /TABS[^=]*=\s*\{([^}]*)\}/.exec(LAYOUT);
  if (!tabs) throw new Error("TABS not found in layout.py");
  const found: Record<string, string> = {};
  for (const m of tabs[1].matchAll(/"(\w+)":\s*"(#[0-9A-Fa-f]{6})"/g)) found[m[1]] = m[2];
  const pack = /PACK_COLOUR\s*=\s*"(#[0-9A-Fa-f]{6})"/.exec(LAYOUT);
  if (pack) found.pack = pack[1];
  return found;
}

/** sRGB channels 0–255 of a `#rgb` or `#rrggbb` colour. */
function rgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  if (!/^[0-9a-f]{6}$/i.test(full)) throw new Error(`not an opaque hex colour: ${hex}`);
  return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16)) as [number, number, number];
}

/** WCAG 2 relative luminance. */
function luminance(hex: string): number {
  const [r, g, b] = rgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2 contrast ratio of two colours (1–21). */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** Pairs below ``min`` as readable strings (empty when all pass). */
function failures(pairs: [string, string, string, string][], min: number): string[] {
  return pairs
    .filter(([, fg, , bg]) => contrast(fg, bg) < min)
    .map(([f, fg, b, bg]) => `${f} ${fg} on ${b} ${bg}: ${contrast(fg, bg).toFixed(2)}`);
}

describe("theme.css", () => {
  it("defines the same tokens in light and dark", () => {
    expect(Object.keys(THEMES.dark).sort()).toEqual(Object.keys(THEMES.light).sort());
    expect(Object.keys(THEMES.light).length).toBeGreaterThan(50);
  });

  it("keeps the top bar, strips and strip text the same in both themes", () => {
    for (const k of Object.keys(THEMES.light)) {
      if (/^(topbar-|cat-)|^on-strip$|^logo$|^worker-idle$/.test(k)) {
        expect(THEMES.dark[k], k).toBe(THEMES.light[k]);
      }
    }
  });

  it("checks the contrast helper against known ratios", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#fff", "#fff")).toBeCloseTo(1, 5);
    expect(contrast("#767676", "#ffffff")).toBeCloseTo(4.54, 2);
  });
});

describe.each(Object.entries(THEMES))("contrast in the %s theme", (_name, t) => {
  const types = Object.keys(t).filter((k) => k.startsWith("type-"));

  it("covers every data type", () => {
    expect(types.length).toBeGreaterThanOrEqual(11);
  });

  it("type colours vs canvas-bg and node-bg ≥ 3:1", () => {
    const pairs = types.flatMap((k) =>
      ["canvas-bg", "node-bg"].map((b) => [k, t[k], b, t[b]] as [string, string, string, string]),
    );
    expect(failures(pairs, 3)).toEqual([]);
  });

  const surfaces = ["panel-bg", "node-bg", "panel-note-bg"];

  it("ink vs panel-bg, node-bg, panel-note-bg ≥ 4.5:1", () => {
    const pairs = surfaces.map((b) => ["ink", t.ink, b, t[b]] as [string, string, string, string]);
    expect(failures(pairs, 4.5)).toEqual([]);
  });

  it("muted vs panel-bg, node-bg, panel-note-bg ≥ 3:1", () => {
    const pairs = surfaces.map((b) => ["muted", t.muted, b, t[b]] as [string, string, string, string]);
    expect(failures(pairs, 3)).toEqual([]);
  });

  // The Panel draws its text in panel-note-ink and its headers in panel-note-muted, so
  // those are what the reader sees on the note.
  it("the Panel's own text on panel-note-bg (ink ≥ 4.5:1, muted ≥ 3:1)", () => {
    const bg = t["panel-note-bg"];
    expect(failures([["panel-note-ink", t["panel-note-ink"], "panel-note-bg", bg]], 4.5)).toEqual([]);
    expect(failures([["panel-note-muted", t["panel-note-muted"], "panel-note-bg", bg]], 3)).toEqual([]);
  });

  it("on-strip vs every category strip ≥ 4.5:1", () => {
    const strips = { ...stripColours(), "cat-other": t["cat-other"] };
    expect(Object.keys(strips).length).toBeGreaterThan(5);
    const pairs = Object.entries(strips).map(
      ([k, c]) => ["on-strip", t["on-strip"], k, c] as [string, string, string, string],
    );
    expect(failures(pairs, 4.5)).toEqual([]);
  });
});
