import type { NodeProps } from "@xyflow/react";
import { iconFor } from "../../icons";
import { useStore } from "../../store";
import { strings } from "../../strings";
import { categoryColour, needsRun, portTypes } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** Grasshopper-style node: inputs left, coloured strip with name or icon, outputs right. */
export function ComponentNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const canvasDisplay = useStore((s) => s.graph?.workflow.view.display ?? "text");
  const error = useStore((s) => s.errors[id]);
  const display = view.display === "default" ? canvasDisplay : view.display;
  const Icon = iconFor(view.icon, view.category);
  const state = view.state ?? "never_run";
  return (
    <div
      className={`gk-node gk-comp gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={state === "error" || state === "skipped" ? error : undefined}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <div className="gk-col gk-inputs">
        {view.inputs.map((p) => (
          <div className="gk-port-row" key={p.name}>
            <Port nodeId={id} side="in" name={p.name} types={portTypes(p)} />
            <span>{p.name}</span>
          </div>
        ))}
      </div>
      <div
        className={`gk-strip gk-strip-${display}`}
        style={{ background: categoryColour(view.category) }}
      >
        {display === "icon" ? (
          <Icon size={18} aria-label={view.title} />
        ) : (
          <span className="gk-vertical">{view.title}</span>
        )}
      </div>
      <div className="gk-col gk-outputs">
        {view.outputs.map((p) => (
          <div className="gk-port-row" key={p.name}>
            <span>{p.name}</span>
            <Port nodeId={id} side="out" name={p.name} types={portTypes(p)} />
          </div>
        ))}
      </div>
      {view.modified && (
        <span className="gk-modified" title={strings.modifiedHint} data-testid={`modified-${id}`}>
          {strings.modified}
        </span>
      )}
    </div>
  );
}
