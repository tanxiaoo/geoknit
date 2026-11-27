import type { NodeProps } from "@xyflow/react";
import { iconFor } from "../../icons/registry";
import { store, useCategoryColour, useStore } from "../../store";
import { strings } from "../../strings";
import { carriesList, needsRun, portTypes } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** Map Layer: data and style inputs, a Display strip, the `layer` output; double-click opens
 * its style window (change 03, section 3). A view node: it never runs. */
export function LayerNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const canvasDisplay = useStore((s) => s.graph?.workflow.view.display ?? "text");
  const colour = useCategoryColour("Display");
  const display = view.display === "default" ? canvasDisplay : view.display;
  const Icon = iconFor("gis:layers", "Display");
  const state = view.state ?? "never_run";
  const name = view.layer?.value?.name;
  return (
    <div
      className={`gk-node gk-comp gk-layer-node gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={name ? `${name}\n${strings.layerHint}` : strings.layerHint}
      onDoubleClick={(e) => {
        e.stopPropagation();
        store.openLayer(id);
      }}
    >
      {needsRun(state) && <span className="gk-dot" />}
      <div className="gk-col gk-inputs">
        {view.inputs.map((p) => (
          <div className="gk-port-row" key={p.name}>
            <Port nodeId={id} side="in" name={p.name} types={portTypes(p)} list={carriesList(p)} />
            <span>{p.name}</span>
          </div>
        ))}
      </div>
      <div className={`gk-strip gk-strip-${display}`} style={{ background: colour }}>
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
            <Port nodeId={id} side="out" name={p.name} types={portTypes(p)} list={carriesList(p)} />
          </div>
        ))}
      </div>
    </div>
  );
}
