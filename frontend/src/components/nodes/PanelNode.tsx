import { NodeResizer, type NodeProps } from "@xyflow/react";
import { store, useStore } from "../../store";
import { strings } from "../../strings";
import { Port } from "./Port";
import type { GkNode } from "./kinds";

/** Panel: a yellow, resizable box showing the summary of whatever is wired in. */
export function PanelNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const wired = useStore((s) => s.graph?.workflow.wires.some((w) => w.to[0] === id) ?? false);
  const text = useStore((s) => s.summaries[id]?.data);
  const error = useStore((s) => s.errors[id]);
  const state = view.state ?? "never_run";
  const body = !wired
    ? strings.panelEmpty
    : state === "done" && text !== undefined
      ? text
      : (error ?? strings.panelRunToUpdate);
  return (
    <div
      className={`gk-node gk-panel gk-state-${state}${selected ? " gk-selected" : ""}`}
      data-testid={`node-${id}`}
      data-state={state}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={120}
        minHeight={48}
        onResizeEnd={(_, p) =>
          void store.patchNode(id, { size: [Math.round(p.width), Math.round(p.height)] })
        }
      />
      <Port nodeId={id} side="in" name="data" type="Any" />
      <pre className="nowheel gk-panel-text" data-testid={`panel-text-${id}`}>
        {body}
      </pre>
      <Port nodeId={id} side="out" name="data" type="Any" />
    </div>
  );
}
