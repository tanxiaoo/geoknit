import { BaseEdge, getBezierPath, type Edge, type EdgeProps } from "@xyflow/react";
import { portSummary, store } from "../store";
import { hideTip, portName, showTip } from "./nodes/Port";

export type TypedEdgeData = { colour: string; faded: boolean; list?: boolean };
export type GkEdge = Edge<TypedEdgeData>;

/** A wire coloured by the type it carries; faded into out-of-date nodes (SPEC 8).
 * A wire carrying a list is a double line (SPEC 3 "List values"). */
export function TypedEdge(props: EdgeProps<GkEdge>) {
  const [path] = getBezierPath(props);
  const colour = props.data?.colour ?? "#64748B";
  const list = props.data?.list ?? false;
  const port = portName(props.sourceHandleId);
  const opacity = props.data?.faded ? 0.4 : 1;
  const width = props.selected ? 3.5 : 2;
  return (
    <g
      onMouseEnter={(e) =>
        showTip(
          e,
          `${port} → ${portName(props.targetHandleId)}`,
          portSummary(store.getState(), props.source, "out", port),
        )
      }
      onMouseLeave={hideTip}
      data-testid={`wire-${props.id}`}
      data-access={list ? "list" : "item"}
    >
      <BaseEdge
        id={props.id}
        path={path}
        interactionWidth={14}
        style={{
          stroke: colour,
          // a list: a wide stroke with the canvas colour drawn down its middle
          strokeWidth: list ? width + 3 : width,
          opacity,
          filter: props.selected ? "drop-shadow(0 0 2px #16a34a)" : undefined,
        }}
      />
      {list && (
        <path
          d={path}
          className="gk-wire-gap"
          fill="none"
          style={{ strokeWidth: props.selected ? 2 : 1.6, opacity, pointerEvents: "none" }}
          data-testid={`wire-gap-${props.id}`}
        />
      )}
    </g>
  );
}
