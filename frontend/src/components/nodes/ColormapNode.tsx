import { useEffect } from "react";
import type { NodeProps } from "@xyflow/react";
import type { ColormapJson, NamedRamps } from "../../apiTypes";
import { store, useStore } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

export const DEFAULT_COLORMAP: ColormapJson = {
  kind: "continuous",
  name: "viridis",
  min: null,
  max: null,
  reverse: false,
};

export function isColormap(v: unknown): v is ColormapJson {
  return typeof v === "object" && v !== null && "kind" in v;
}

/** A continuous colormap's stops, low to high: its own, or its named ramp's evenly spaced
 * (`GET /api/colormaps`). Null while the ramps are not loaded, or for classes. */
export function stopsOf(cm: ColormapJson, ramps: NamedRamps | null): [number, string][] | null {
  if (cm.kind !== "continuous") return null;
  let stops = cm.stops ?? null;
  if (!stops && cm.name && ramps?.[cm.name]) {
    const colours = ramps[cm.name];
    stops = colours.map((c, i) => [i / (colours.length - 1), c]);
  }
  if (!stops) return null;
  return cm.reverse ? stops.map(([p, c]) => [1 - p, c] as [number, string]).reverse() : stops;
}

/** A CSS gradient through ``stops`` (left = low). */
export function gradientCss(stops: [number, string][]): string {
  const parts = stops.map(([p, c]) => `${c} ${Number((p * 100).toFixed(2))}%`);
  return `linear-gradient(to right, ${parts.join(", ")})`;
}

/** What the strip shows: a gradient, or class chips (change 03 makes those). */
export interface StripProps {
  cm: ColormapJson;
  ramps: NamedRamps | null;
  testId?: string;
  className?: string;
}

export function Strip({ cm, ramps, testId, className }: StripProps) {
  const extra = className ? ` ${className}` : "";
  if (cm.kind === "classes") {
    return (
      <span className={`gk-ramp gk-ramp-classes${extra}`} data-testid={testId}>
        {cm.classes.map(([value, colour, label]) => (
          <span
            key={String(value)}
            className="gk-class-chip"
            style={{ background: colour }}
            title={label}
          />
        ))}
      </span>
    );
  }
  const stops = stopsOf(cm, ramps);
  return (
    <span
      className={`gk-ramp${extra}`}
      style={stops ? { background: gradientCss(stops) } : undefined}
      data-testid={testId}
    />
  );
}

/** The ramp's name, "custom" for edited stops, or the number of classes. */
export function colormapLabel(cm: ColormapJson): string {
  if (cm.kind === "classes") return strings.colormapClasses(cm.classes.length);
  const name = cm.stops || !cm.name ? strings.colormapCustom : cm.name;
  return cm.reverse ? `${name} (${strings.colormapReverse.toLowerCase()})` : name;
}

/** Colormap: a gradient strip; double-click opens the Colormap editor window (change 03,
 * section 2). */
export function ColormapNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const cm = isColormap(view.value) ? view.value : DEFAULT_COLORMAP;
  const ramps = useStore((s) => s.ramps);
  const state = view.state ?? "never_run";
  useEffect(() => void store.loadRamps(), []);
  return (
    <div
      className={`gk-node gk-text gk-colormap gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={strings.cmEditorHint}
      onDoubleClick={(e) => {
        e.stopPropagation();
        store.openColormap(id);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <Strip cm={cm} ramps={ramps} testId={`ramp-${id}`} />
      <span className="gk-text-value">{colormapLabel(cm)}</span>
      <Port nodeId={id} side="out" name="value" types={["Colormap"]} />
    </div>
  );
}
