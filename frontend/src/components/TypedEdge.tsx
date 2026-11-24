import { BaseEdge, getBezierPath, type Edge, type EdgeProps } from "@xyflow/react";

export type TypedEdgeData = { colour: string; faded: boolean };
export type GkEdge = Edge<TypedEdgeData>;

/** A wire coloured by the type it carries; faded into out-of-date nodes (SPEC 8). */
export function TypedEdge(props: EdgeProps<GkEdge>) {
  const [path] = getBezierPath(props);
  const colour = props.data?.colour ?? "#64748B";
  return (
    <BaseEdge
      id={props.id}
      path={path}
      interactionWidth={14}
      style={{
        stroke: colour,
        strokeWidth: props.selected ? 3.5 : 2,
        opacity: props.data?.faded ? 0.4 : 1,
        filter: props.selected ? "drop-shadow(0 0 2px #16a34a)" : undefined,
      }}
    />
  );
}
