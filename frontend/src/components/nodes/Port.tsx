import { createContext, useContext } from "react";
import { Handle, Position } from "@xyflow/react";
import type { PortType } from "../../apiTypes";
import { canConnect, PORT_COLOURS } from "../../types";

/** The port a wire is being dragged from, so other ports can show if they fit. */
export interface DragFrom {
  nodeId: string;
  side: "in" | "out";
  type: PortType;
}

export const DragContext = createContext<DragFrom | null>(null);

export function handleId(side: "in" | "out", name: string): string {
  return `${side}:${name}`;
}

export function portName(handle: string | null | undefined): string {
  return (handle ?? "").replace(/^(in|out):/, "");
}

interface Props {
  nodeId: string;
  side: "in" | "out";
  name: string;
  type: PortType;
}

export function Port({ nodeId, side, name, type }: Props) {
  const drag = useContext(DragContext);
  let fit = "";
  if (drag && drag.nodeId !== nodeId && drag.side !== side) {
    const ok = side === "in" ? canConnect(drag.type, type) : canConnect(type, drag.type);
    fit = ok ? "gk-fits" : "gk-misfit";
  }
  return (
    <Handle
      id={handleId(side, name)}
      type={side === "in" ? "target" : "source"}
      position={side === "in" ? Position.Left : Position.Right}
      className={`gk-handle ${fit}`}
      style={{ background: PORT_COLOURS[type] }}
      data-testid={`port-${nodeId}-${side}-${name}`}
      data-type={type}
      title={`${name}: ${type}`}
    />
  );
}
