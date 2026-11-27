import type { NodeProps } from "@xyflow/react";
import { Map as MapIcon } from "lucide-react";
import { useCategoryColour, useStore } from "../../store";
import { strings } from "../../strings";
import { needsRun } from "../../types";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** Map Viewer: one `layers` input taking any number of wires; double-click opens the map. */
export function MapNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const count = useStore((s) => s.graph?.workflow.wires.filter((w) => w.to[0] === id).length ?? 0);
  const state = view.state ?? "never_run";
  const colour = useCategoryColour("Params");
  return (
    <div
      className={`gk-node gk-comp gk-map-node gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
      title={strings.mapOpenHint}
    >
      {needsRun(state) && count > 0 && <span className="gk-dot" />}
      <div className="gk-col gk-inputs">
        <div className="gk-port-row">
          <Port nodeId={id} side="in" name="layers" types={["Any"]} list />
          <span>layers</span>
        </div>
      </div>
      <div className="gk-strip gk-strip-text" style={{ background: colour }}>
        <span className="gk-vertical">{strings.mapViewer}</span>
      </div>
      <div className="gk-col gk-map-count" data-testid={`map-count-${id}`}>
        <MapIcon size={16} aria-hidden />
        <span>{strings.mapLayerCount(count)}</span>
      </div>
    </div>
  );
}
