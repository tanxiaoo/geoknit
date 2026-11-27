import { createContext, useContext } from "react";
import { Handle, Position } from "@xyflow/react";
import type { PortType } from "../../apiTypes";
import { portSummary, store } from "../../store";
import { strings } from "../../strings";
import { connectionError, PORT_COLOURS, typeLabel } from "../../types";

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
  types: PortType[];
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
  /** What the port can carry (several for a union input or an unresolved `like:` output). */
  types: PortType[];
}

export function Port({ nodeId, side, name, types }: Props) {
  const drag = useContext(DragContext);
  let refusal: string | null = null;
  let fit = "";
  if (drag && drag.nodeId !== nodeId && drag.side !== side) {
    refusal =
      side === "in" ? connectionError(drag.types, types) : connectionError(types, drag.types);
    fit = refusal ? "gk-misfit" : "gk-fits";
  }
  // SPEC 3: first type's colour, a thin ring of the second.
  const style: React.CSSProperties = { background: PORT_COLOURS[types[0]] };
  if (types.length > 1) style.borderColor = PORT_COLOURS[types[1]];
  return (
    <Handle
      id={handleId(side, name)}
      type={side === "in" ? "target" : "source"}
      position={side === "in" ? Position.Left : Position.Right}
      className={`gk-handle ${fit}${types.length > 1 ? " gk-union" : ""}`}
      style={style}
      data-testid={`port-${nodeId}-${side}-${name}`}
      data-type={types.join("|")}
      onMouseEnter={(e) => {
        if (refusal) {
          store.set({ tip: { text: refusal, x: e.clientX, y: e.clientY } });
          return;
        }
        showTip(e, `${name}: ${typeLabel(types)}`, portSummary(store.getState(), nodeId, side, name));
      }}
      onMouseLeave={hideTip}
    />
  );
}
