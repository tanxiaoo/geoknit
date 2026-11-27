// Icon registry (change 01, section 9): every built-in and Params icon resolves,
// unknown names fall back with one warning, and docs/icons.md is up to date.
// `UPDATE_ICONS=1 npx vitest run src/icons` rewrites docs/icons.md and docs/icons/.

import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { cwd, env } from "node:process";
import { render } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import layoutPy from "../../../geoknit/components/layout.py?raw";
import { strings } from "../strings";
import {
  CATEGORY_ICONS,
  DEFAULT_ICON,
  ICONS,
  iconFor,
  resetIconWarnings,
  resolveIcon,
  type IconSet,
} from "./registry";

const BUILTINS = import.meta.glob("../../../geoknit/components/builtin/*/*.py", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** `icon:` of every built-in component file. */
function builtinIcons(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, source] of Object.entries(BUILTINS)) {
    const m = /^# icon:\s*(.+?)\s*$/m.exec(source);
    out[path.replace(/^.*builtin\//, "")] = m ? m[1] : "";
  }
  return out;
}

/** The `PARAM_ICONS` block of geoknit/components/layout.py. */
function paramIcons(): Record<string, string> {
  const block = /^PARAM_ICONS[^{]*\{([\s\S]*?)^\}/m.exec(layoutPy);
  if (!block) throw new Error("PARAM_ICONS not found in layout.py");
  const out: Record<string, string> = {};
  for (const m of block[1].matchAll(/"(param\/[a-z_]+)":\s*"([^"]+)"/g)) out[m[1]] = m[2];
  return out;
}

describe("icon registry", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    resetIconWarnings();
  });

  it("resolves the icon of every built-in component", () => {
    const icons = builtinIcons();
    expect(Object.keys(icons).length).toBeGreaterThanOrEqual(19);
    const missing = Object.entries(icons).filter(([, name]) => !resolveIcon(name));
    expect(missing).toEqual([]);
  });

  it("resolves the icon of every Params entry", () => {
    const icons = paramIcons();
    expect(Object.keys(icons).sort()).toEqual([
      "param/color",
      "param/colormap",
      "param/map",
      "param/number",
      "param/panel",
      "param/slider",
      "param/text",
      "param/toggle",
      "param/value_list",
    ]);
    const missing = Object.entries(icons).filter(([, name]) => !resolveIcon(name));
    expect(missing).toEqual([]);
  });

  it("has an icon for every built-in tab and the default", () => {
    for (const name of [...Object.values(CATEGORY_ICONS), DEFAULT_ICON]) {
      expect(resolveIcon(name), name).toBeDefined();
    }
  });

  it("falls back to the category icon with one warning per unknown name", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const Raster = resolveIcon(CATEGORY_ICONS.Raster);
    expect(iconFor("gis:no-such-icon", "Raster")).toBe(Raster);
    expect(iconFor("gis:no-such-icon", "Raster")).toBe(Raster);
    expect(iconFor("reclassify", "Raster")).toBe(Raster); // bare names are gone
    expect(warn).toHaveBeenCalledTimes(2);
    expect(warn).toHaveBeenCalledWith(strings.unknownIcon("gis:no-such-icon"));
    expect(iconFor(null, "Pack tab")).toBe(resolveIcon(DEFAULT_ICON));
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it("draws vendored icons inline in currentColor", () => {
    const Icon = iconFor("gis:map-legend", "Raster");
    const { container } = render(<Icon size={18} aria-label="Reclassify" />);
    const span = container.querySelector('[data-icon="gis:map-legend"]') as HTMLElement;
    expect(span.style.width).toBe("18px");
    expect(span.getAttribute("aria-label")).toBe("Reclassify");
    const svg = span.querySelector("svg")!;
    expect(svg.getAttribute("fill")).toBe("currentColor");
    expect(span.innerHTML).not.toMatch(/#[0-9a-f]{3,6}\b/i);
  });

  it("serves a pack's .svg icon from its component", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const Icon = iconFor("icons/x.svg", "Fake", "fakepack/Fake/thing");
    expect(iconFor("icons/x.svg", "Fake", "fakepack/Fake/thing")).toBe(Icon);
    const { container } = render(<Icon size={16} />);
    const span = container.querySelector("[data-icon-url]") as HTMLElement;
    expect(span.dataset.iconUrl).toBe("/api/components/fakepack/Fake/thing/icon");
    expect(warn).not.toHaveBeenCalled();
  });

  it("keeps every vendored file in currentColor", () => {
    for (const [name, entry] of Object.entries(ICONS)) {
      if (!entry.svg) continue;
      const colours = entry.svg.match(/(fill|stroke)="(?!none|currentColor)[^"]*"/g);
      expect(colours, name).toBeNull();
    }
  });
});

// ── docs/icons.md ──

// vitest runs in frontend/ (plain paths: under jsdom, `URL` is jsdom's, which node:fs refuses).
const DOCS = `${cwd()}/../docs/`;
const PREVIEWS = `${DOCS}icons/`;
const PREVIEW_COLOUR = "#64748b"; // readable on GitHub's light and dark themes

const SET_TITLES: Record<IconSet, string> = {
  gis: "Font-GIS (CC BY 4.0)",
  lucide: "Lucide (ISC)",
  tabler: "Tabler Icons (MIT)",
};

function previewFile(name: string): string {
  return `${name.replace(":", "-")}.svg`;
}

/** A standalone SVG preview of one icon, for GitHub to show in docs/icons.md. */
function previewSvg(name: string): string {
  const entry = ICONS[name];
  let svg: string;
  if (entry.svg) {
    svg = entry.svg.replace("<svg ", '<svg width="24" height="24" ');
  } else {
    svg = renderToStaticMarkup(<entry.Icon size={24} />) + "\n";
  }
  return svg.replace(/currentColor/g, PREVIEW_COLOUR);
}

function iconsDoc(): { markdown: string; files: Record<string, string> } {
  const files: Record<string, string> = {};
  const lines = [
    "# Icons",
    "",
    "<!-- Generated by frontend/src/icons/registry.test.tsx. Do not edit: run",
    "     `UPDATE_ICONS=1 npx vitest run src/icons` in frontend/ to rewrite it. -->",
    "",
    "Names a component header can use in `icon:` (see",
    "[writing-components.md](writing-components.md)). A name that is not in this",
    "list falls back to the category's icon. For any other icon, ship an `.svg`",
    "file with the component and name its path relative to the component file:",
    "`icon: icons/my-icon.svg` (it must stay inside the pack folder). Icons are",
    "drawn in one colour (`currentColor`), so they follow the theme.",
    "",
    "Sets, in the order GeoKnit chooses from them: [Font-GIS](https://github.com/Viglino/font-gis)",
    "(icons CC BY 4.0, Jean-Marc Viglino), [Lucide](https://lucide.dev) (ISC),",
    "[Tabler Icons](https://tabler.io/icons) (MIT). See `THIRD_PARTY_NOTICES.md`.",
    "",
    "| Icon | Name | Set |",
    "|------|------|-----|",
  ];
  for (const [name, entry] of Object.entries(ICONS)) {
    const file = previewFile(name);
    files[file] = previewSvg(name);
    lines.push(
      `| <img src="icons/${file}" width="24" height="24" alt=""> | \`${name}\` | ${SET_TITLES[entry.set]} |`,
    );
  }
  return { markdown: lines.join("\n") + "\n", files };
}

describe("docs/icons.md", () => {
  it("lists every icon in the registry (UPDATE_ICONS=1 rewrites it)", () => {
    const { markdown, files } = iconsDoc();
    const mdPath = `${DOCS}icons.md`;
    if (env.UPDATE_ICONS === "1") {
      mkdirSync(PREVIEWS, { recursive: true });
      for (const old of readdirSync(PREVIEWS)) {
        if (!(old in files)) rmSync(PREVIEWS + old);
      }
      for (const [file, svg] of Object.entries(files)) {
        writeFileSync(PREVIEWS + file, svg, "utf-8");
      }
      writeFileSync(mdPath, markdown, "utf-8");
    }
    const hint = "docs/icons.md is stale: run `UPDATE_ICONS=1 npx vitest run src/icons` in frontend/";
    expect(existsSync(mdPath), hint).toBe(true);
    expect(readFileSync(mdPath, "utf-8").replace(/\r\n/g, "\n"), hint).toBe(markdown);
    expect(readdirSync(PREVIEWS).sort(), hint).toEqual(Object.keys(files).sort());
    for (const [file, svg] of Object.entries(files)) {
      expect(readFileSync(PREVIEWS + file, "utf-8").replace(/\r\n/g, "\n"), hint).toBe(svg);
    }
  });
});
