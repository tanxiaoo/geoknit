import { useEffect, useState } from "react";
import type { NodeProps } from "@xyflow/react";
import { store } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

function formatNumber(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Number(n.toPrecision(6)));
}

/** Number Slider: drag to change, double-click the value for min / max / step. */
export function SliderNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const min = view.min ?? 0;
  const max = view.max ?? 100;
  const step = view.step ?? 1;
  const value = typeof view.value === "number" ? view.value : min;
  const [local, setLocal] = useState(value);
  const [open, setOpen] = useState(false);
  const state = view.state ?? "never_run";

  useEffect(() => setLocal(value), [value]);

  const commit = () => {
    if (local !== value) void store.patchNode(id, { value: local });
  };

  return (
    <div
      className={`gk-node gk-slider gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <input
        type="range"
        className="nodrag gk-range"
        min={min}
        max={max}
        step={step}
        value={local}
        onChange={(e) => setLocal(Number(e.currentTarget.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        aria-label={strings.sliderValue}
      />
      <span
        className="gk-slider-value"
        onDoubleClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        data-testid={`slider-value-${id}`}
      >
        {formatNumber(local)}
      </span>
      <Port nodeId={id} side="out" name="value" type="Number" />
      {open && (
        <SliderWindow
          min={min}
          max={max}
          step={step}
          value={local}
          onCancel={() => setOpen(false)}
          onOk={(v) => {
            setOpen(false);
            void store.patchNode(id, v);
          }}
        />
      )}
    </div>
  );
}

interface WindowProps {
  min: number;
  max: number;
  step: number;
  value: number;
  onOk: (v: { min: number; max: number; step: number; value: number }) => void;
  onCancel: () => void;
}

/** The small min / max / step / value window of a Number Slider (SPEC 8). */
export function SliderWindow(props: WindowProps) {
  const [fields, setFields] = useState({
    min: String(props.min),
    max: String(props.max),
    step: String(props.step),
    value: String(props.value),
  });
  const names = ["min", "max", "step", "value"] as const;
  const label = {
    min: strings.sliderMin,
    max: strings.sliderMax,
    step: strings.sliderStep,
    value: strings.sliderValue,
  };
  const submit = () =>
    props.onOk({
      min: Number(fields.min),
      max: Number(fields.max),
      step: Number(fields.step),
      value: Number(fields.value),
    });
  return (
    <form
      className="nodrag nowheel gk-popover gk-slider-window"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "Escape") props.onCancel();
        e.stopPropagation();
      }}
    >
      {names.map((n) => (
        <label key={n}>
          <span>{label[n]}</span>
          <input
            type="number"
            step="any"
            value={fields[n]}
            autoFocus={n === "value"}
            onChange={(e) => setFields({ ...fields, [n]: e.currentTarget.value })}
            data-testid={`slider-${n}`}
          />
        </label>
      ))}
      <div className="gk-popover-buttons">
        <button type="button" onClick={props.onCancel}>
          {strings.cancel}
        </button>
        <button type="submit" className="gk-primary" data-testid="slider-ok">
          {strings.ok}
        </button>
      </div>
    </form>
  );
}
