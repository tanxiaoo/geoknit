import type { NodeProps } from "@xyflow/react";
import { store } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** Boolean Toggle: a pill with a switch; a click flips it, one undo step (change 01, 8). */
export function ToggleNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const value = view.value === true;
  const state = view.state ?? "never_run";
  return (
    <div
      className={`gk-node gk-toggle gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <button
        type="button"
        role="switch"
        aria-checked={value}
        className="nodrag gk-switch-button"
        title={strings.toggleHint}
        onClick={(e) => {
          e.stopPropagation();
          void store.patchNode(id, { value: !value });
        }}
        onDoubleClick={(e) => e.stopPropagation()}
        data-testid={`toggle-${id}`}
      >
        <span className={`gk-switch${value ? " gk-switch-on" : ""}`}>
          <span className="gk-switch-knob" />
        </span>
        <span className="gk-toggle-value">{value ? strings.toggleTrue : strings.toggleFalse}</span>
      </button>
      <Port nodeId={id} side="out" name="value" types={["Boolean"]} />
    </div>
  );
}
