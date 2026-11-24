import { createContext, useContext } from "react";
import { Handle, Position } from "@xyflow/react";
import type { PortType } from "../../apiTypes";
import { portSummary, store } from "../../store";
import { strings } from "../../strings";
import { canConnect, PORT_COLOURS } from "../../types";

/** Show what a port or wire carries next to the pointer (SPEC 8). */
export function showTip(
  e: { clientX: number; clientY: number },
  head: string,
  summary: string | null,
) {
  store.set({
    tip: {
      text: `${head}
${summary ?? strings.notRunYet}`,
      x: e.clientX,
      y: e.clientY,
    },
  });
}

export function hideTip() {
  if (store.getState().tip) store.set({ tip: null });
}

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
      onMouseEnter={(e) =>
        showTip(e, `${name}: ${type}`, portSummary(store.getState(), nodeId, side, name))
      }
      onMouseLeave={hideTip}
    />
  );
}
