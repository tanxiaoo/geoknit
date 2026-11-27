import { useEffect, useState } from "react";
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

function isColormap(v: unknown): v is ColormapJson {
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
interface StripProps {
  cm: ColormapJson;
  ramps: NamedRamps | null;
  testId?: string;
}

function Strip({ cm, ramps, testId }: StripProps) {
  if (cm.kind === "classes") {
    return (
      <span className="gk-ramp gk-ramp-classes" data-testid={testId}>
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
      className="gk-ramp"
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

/** Colormap: a gradient strip; double-click offers the named ramps (change 01, section 8;
 * the full colormap editor is change 03). */
export function ColormapNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const cm = isColormap(view.value) ? view.value : DEFAULT_COLORMAP;
  const ramps = useStore((s) => s.ramps);
  const [open, setOpen] = useState(false);
  const state = view.state ?? "never_run";
  useEffect(() => void store.loadRamps(), []);
  return (
    <div
      className={`gk-node gk-text gk-colormap gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={strings.colormapHint}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setOpen(true);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <Strip cm={cm} ramps={ramps} testId={`ramp-${id}`} />
      <span className="gk-text-value">{colormapLabel(cm)}</span>
      <Port nodeId={id} side="out" name="value" types={["Colormap"]} />
      {open && (
        <RampWindow
          value={cm}
          ramps={ramps ?? {}}
          onCancel={() => setOpen(false)}
          onPick={(next) => {
            setOpen(false);
            void store.patchNode(id, { value: next });
          }}
        />
      )}
    </div>
  );
}

interface WindowProps {
  value: ColormapJson;
  ramps: NamedRamps;
  onPick: (value: ColormapJson) => void;
  onCancel: () => void;
}

/** The named ramps to choose from, with a "reversed" box. A continuous colormap keeps its
 * min and max. */
export function RampWindow({ value, ramps, onPick, onCancel }: WindowProps) {
  const [reverse, setReverse] = useState(value.kind === "continuous" && value.reverse);
  const current = value.kind === "continuous" && !value.stops ? value.name : null;
  const wasReversed = value.kind === "continuous" && value.reverse;
  const pick = (name: string) =>
    onPick({
      kind: "continuous",
      name,
      min: value.kind === "continuous" ? value.min : null,
      max: value.kind === "continuous" ? value.max : null,
      reverse,
    });
  return (
    <div
      className="nodrag nowheel gk-popover gk-slider-window gk-ramp-window"
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Escape") onCancel();
        e.stopPropagation();
      }}
      data-testid="ramp-window"
    >
      <strong>{strings.colormapRamps}</strong>
      <ul>
        {Object.keys(ramps).map((name) => (
          <li
            key={name}
            className={name === current && reverse === wasReversed ? "gk-active" : ""}
            onClick={() => pick(name)}
            data-testid={`ramp-${name}`}
          >
            <Strip cm={{ kind: "continuous", name, min: null, max: null, reverse }} ramps={ramps} />
            <span>{name}</span>
          </li>
        ))}
      </ul>
      <label className="gk-ramp-reverse">
        <input
          type="checkbox"
          checked={reverse}
          onChange={(e) => setReverse(e.currentTarget.checked)}
          data-testid="ramp-reverse"
        />
        <span>{strings.colormapReverse}</span>
      </label>
      <div className="gk-popover-buttons">
        <button type="button" onClick={onCancel}>
          {strings.cancel}
        </button>
      </div>
    </div>
  );
}
