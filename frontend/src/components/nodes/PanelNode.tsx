import { NodeResizer, type NodeProps } from "@xyflow/react";
import { store, useStore } from "../../store";
import { strings } from "../../strings";
import { carriesList, portTypes } from "../../types";
import { Port } from "./Port";
import { PanelView } from "./PanelView";
import type { GkNode } from "./kinds";

/** Panel: a yellow, resizable box showing whatever is wired in (change 01, section 11): the
 * value, a swatch, a gradient, list rows or a paging grid; the describe() text otherwise. */
export function PanelNode({ id, data, selected }: NodeProps<GkNode>) {
  const view = data.view;
  const wired = useStore((s) => s.graph?.workflow.wires.some((w) => w.to[0] === id) ?? false);
  const text = useStore((s) => s.summaries[id]?.data);
  const shown = useStore((s) => s.views[id]?.data);
  const error = useStore((s) => s.errors[id]);
  const state = view.state ?? "never_run";
  const out = view.outputs[0];
  // A list passes through whole (SPEC 3 "List values"): both ends are drawn as a list.
  const list = out ? carriesList(out) : false;
  const done = wired && state === "done";
  const body = !wired
    ? strings.panelEmpty
    : done && text !== undefined
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
      <Port nodeId={id} side="in" name="data" types={["Any"]} list={list} />
      {done && shown ? (
        <div className="gk-panel-text gk-panel-view" data-testid={`panel-text-${id}`}>
          <PanelView nodeId={id} view={shown} />
        </div>
      ) : (
        <pre className="nowheel gk-panel-text" data-testid={`panel-text-${id}`}>
          {body}
        </pre>
      )}
      <Port
        nodeId={id}
        side="out"
        name="data"
        types={out ? portTypes(out) : ["Any"]}
        list={list}
      />
    </div>
  );
}
