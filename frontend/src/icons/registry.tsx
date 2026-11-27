// Icon registry (change 01, section 9): header `icon:` names → icons.
//
// Names are `<set>:<name>` with set `gis` (Font-GIS), `lucide` or `tabler`;
// chosen in that order. Only the icons GeoKnit uses are bundled: Lucide icons
// come from lucide-react, Font-GIS and Tabler icons are SVG files copied into
// ./vendor/ (colours set to currentColor, licence files next to them).
// A header may also name a relative `.svg` file, served by
// `GET /api/components/{ref}/icon`. docs/icons.md is generated from `ICONS`
// by registry.test.ts (UPDATE_ICONS=1 rewrites it).

import { useEffect, useState, type ComponentType } from "react";
import {
  Calculator,
  Code,
  Grid2x2Check,
  Hash,
  List,
  Rainbow,
  Sigma,
  SlidersHorizontal,
  StickyNote,
  SunMoon,
  Table,
  Target,
  ToggleRight,
  Trees,
  Type,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";
import { componentIconUrl } from "../api";
import { strings } from "../strings";

import gisColor from "./vendor/gis/color.svg?raw";
import gisLayerDownload from "./vendor/gis/layer-download.svg?raw";
import gisLayers from "./vendor/gis/layers.svg?raw";
import gisLayersPoi from "./vendor/gis/layers-poi.svg?raw";
import gisMap from "./vendor/gis/map.svg?raw";
import gisMapLegend from "./vendor/gis/map-legend.svg?raw";
import gisMosaic from "./vendor/gis/mosaic.svg?raw";
import gisMultipoint from "./vendor/gis/multipoint.svg?raw";
import gisPoiInfo from "./vendor/gis/poi-info.svg?raw";
import gisPolygonPt from "./vendor/gis/polygon-pt.svg?raw";
import gisProjGeo from "./vendor/gis/proj-geo.svg?raw";
import gisSelectExtent from "./vendor/gis/select-extent.svg?raw";
import gisSnap from "./vendor/gis/snap.svg?raw";
import gisSplit from "./vendor/gis/split.svg?raw";
import tablerBrandPython from "./vendor/tabler/brand-python.svg?raw";

export interface IconProps {
  size?: number;
  "aria-label"?: string;
}

export type IconComponent = ComponentType<IconProps>;

export type IconSet = "gis" | "lucide" | "tabler";

/** One registry entry: the icon, and its SVG source for vendored sets (for docs/icons.md). */
export interface IconEntry {
  set: IconSet;
  Icon: IconComponent;
  svg?: string;
}

/** A vendored SVG (Font-GIS or Tabler) drawn inline, so `currentColor` follows the text colour. */
function rawIcon(svg: string, name: string): IconComponent {
  const markup = svg.replace(/<!--[\s\S]*?-->\s*/g, "");
  function RawIcon({ size = 24, "aria-label": label }: IconProps) {
    return (
      <span
        className="gk-svg-icon"
        role={label ? "img" : undefined}
        aria-label={label}
        aria-hidden={label ? undefined : true}
        data-icon={name}
        style={{ width: size, height: size }}
        dangerouslySetInnerHTML={{ __html: markup }}
      />
    );
  }
  RawIcon.displayName = name;
  return RawIcon;
}

const gis = (name: string, svg: string): [string, IconEntry] => [
  `gis:${name}`,
  { set: "gis", Icon: rawIcon(svg, `gis:${name}`), svg },
];
const tabler = (name: string, svg: string): [string, IconEntry] => [
  `tabler:${name}`,
  { set: "tabler", Icon: rawIcon(svg, `tabler:${name}`), svg },
];
function lucide(name: string, Lucide: LucideIcon): [string, IconEntry] {
  function LucideEntry(props: IconProps) {
    return <Lucide {...props} />;
  }
  LucideEntry.displayName = `lucide:${name}`;
  return [`lucide:${name}`, { set: "lucide", Icon: LucideEntry }];
}

/** Every available icon name, sorted. */
export const ICONS: Record<string, IconEntry> = Object.fromEntries(
  [
    gis("color", gisColor),
    gis("layer-download", gisLayerDownload),
    gis("layers", gisLayers),
    gis("layers-poi", gisLayersPoi),
    gis("map", gisMap),
    gis("map-legend", gisMapLegend),
    gis("mosaic", gisMosaic),
    gis("multipoint", gisMultipoint),
    gis("poi-info", gisPoiInfo),
    gis("polygon-pt", gisPolygonPt),
    gis("proj-geo", gisProjGeo),
    gis("select-extent", gisSelectExtent),
    gis("snap", gisSnap),
    gis("split", gisSplit),
    lucide("calculator", Calculator),
    lucide("code", Code),
    lucide("grid-2x2-check", Grid2x2Check),
    lucide("hash", Hash),
    lucide("list", List),
    lucide("rainbow", Rainbow),
    lucide("sigma", Sigma),
    lucide("sliders-horizontal", SlidersHorizontal),
    lucide("sticky-note", StickyNote),
    lucide("sun-moon", SunMoon),
    lucide("table", Table),
    lucide("target", Target),
    lucide("toggle-right", ToggleRight),
    lucide("trees", Trees),
    lucide("type", Type),
    lucide("wand-sparkles", WandSparkles),
    tabler("brand-python", tablerBrandPython),
  ].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
);

/** The icon of each built-in tab, used when a component has no (known) icon. */
export const CATEGORY_ICONS: Record<string, string> = {
  Params: "lucide:sliders-horizontal",
  Maths: "lucide:calculator",
  Sets: "lucide:list",
  Table: "lucide:table",
  Vector: "gis:polygon-pt",
  Raster: "gis:mosaic",
  Sampling: "gis:multipoint",
  Model: "lucide:trees",
  Validation: "lucide:target",
  Display: "gis:map",
  Script: "lucide:code",
};

/** Pack and user categories, and anything else without its own icon. */
export const DEFAULT_ICON = "lucide:code";

/** The registry's icon for a prefixed name, or `undefined`. */
export function resolveIcon(name: string): IconComponent | undefined {
  return Object.prototype.hasOwnProperty.call(ICONS, name) ? ICONS[name].Icon : undefined;
}

export function isSvgPath(name: string): boolean {
  return name.toLowerCase().endsWith(".svg");
}

const warned = new Set<string>();

function warnOnce(name: string): void {
  if (warned.has(name)) return;
  warned.add(name);
  console.warn(strings.unknownIcon(name));
}

/** For tests: forget which unknown names were already reported. */
export function resetIconWarnings(): void {
  warned.clear();
}

function categoryIcon(category: string | null | undefined): IconComponent {
  const name = (category && CATEGORY_ICONS[category]) || DEFAULT_ICON;
  return ICONS[name].Icon;
}

/** A pack's own `.svg`, drawn as a mask in `currentColor`; the category icon if it fails to load. */
function svgFileIcon(url: string, Fallback: IconComponent): IconComponent {
  function SvgFileIcon(props: IconProps) {
    const [failed, setFailed] = useState(false);
    useEffect(() => {
      const img = new Image();
      img.onerror = () => setFailed(true);
      img.src = url;
      return () => {
        img.onerror = null;
      };
    }, []);
    if (failed) return <Fallback {...props} />;
    const size = props.size ?? 24;
    const label = props["aria-label"];
    const mask = `url("${url}") center / contain no-repeat`;
    return (
      <span
        className="gk-svg-icon gk-file-icon"
        role={label ? "img" : undefined}
        aria-label={label}
        aria-hidden={label ? undefined : true}
        data-icon-url={url}
        style={{ width: size, height: size, mask, WebkitMask: mask }}
      />
    );
  }
  return SvgFileIcon;
}

const fileIcons = new Map<string, IconComponent>();

/**
 * The icon to draw for a header `icon:` value.
 *
 * - a prefixed name from the registry;
 * - a relative `.svg` path, served for component `ref`;
 * - otherwise the category's icon, with one console warning per unknown name.
 */
export function iconFor(
  name: string | null | undefined,
  category?: string | null,
  ref?: string | null,
): IconComponent {
  if (name) {
    const found = resolveIcon(name);
    if (found) return found;
    if (isSvgPath(name) && ref) {
      const url = componentIconUrl(ref);
      const key = `${category ?? ""}\n${url}`;
      let icon = fileIcons.get(key);
      if (!icon) {
        icon = svgFileIcon(url, categoryIcon(category));
        fileIcons.set(key, icon);
      }
      return icon;
    }
    if (!isSvgPath(name)) warnOnce(name);
  }
  return categoryIcon(category);
}
