import { createContext, useContext } from "react";
import { Handle, Position } from "@xyflow/react";
import type { PortType } from "../../apiTypes";
import { portSummary, store, useStore } from "../../store";
import { strings } from "../../strings";
import { PORT_COLOURS, tipSummary, typeLabel, wireError } from "../../types";

/** Show what a port or wire carries next to the pointer (SPEC 8). */
export function showTip(
  e: { clientX: number; clientY: number },
  head: string,
  summary: string | null,
) {
  store.set({
    tip: {
      text: `${head}
${summary === null ? strings.notRunYet : tipSummary(summary)}`,
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
  /** Port name, node title and whether it carries a list (SPEC 3 "List values"). */
  name?: string;
  title?: string;
  list?: boolean;
}

export const DragContext = createContext<DragFrom | null>(null);

export function handleId(side: "in" | "out", name: string): string {
  return `${side}:${name}`;
}

export function portName(handle: string | null | undefined): string {
  return (handle ?? "").replace(/^(in|out):/, "");
}

/** The refusal for a wire between ``drag`` and this port, or null if it fits. */
export function dragRefusal(
  drag: DragFrom,
  port: { side: "in" | "out"; name: string; types: PortType[]; list: boolean; title: string },
): string | null {
  if (port.side === "in") {
    return wireError(
      { title: drag.title ?? "", types: drag.types, list: drag.list ?? false },
      { name: port.name, types: port.types, access: port.list ? "list" : "item" },
    );
  }
  return wireError(
    { title: port.title, types: port.types, list: port.list },
    { name: drag.name ?? "", types: drag.types, access: drag.list ? "list" : "item" },
  );
}

interface Props {
  nodeId: string;
  side: "in" | "out";
  name: string;
  /** What the port can carry (several for a union input or an unresolved `like:` output). */
  types: PortType[];
  /** Carries a list: drawn with a double line (an `access: list` input, or a list output). */
  list?: boolean;
}

export function Port({ nodeId, side, name, types, list = false }: Props) {
  const drag = useContext(DragContext);
  const title = useStore((s) => s.graph?.nodes[nodeId]?.title ?? "");
  let refusal: string | null = null;
  let fit = "";
  if (drag && drag.nodeId !== nodeId && drag.side !== side) {
    refusal = dragRefusal(drag, { side, name, types, list, title });
    fit = refusal ? "gk-misfit" : "gk-fits";
  }
  // SPEC 3: first type's colour, a thin ring of the second.
  const style = { background: PORT_COLOURS[types[0]] } as React.CSSProperties &
    Record<"--gk-port", string>;
  if (types.length > 1) style.borderColor = PORT_COLOURS[types[1]];
  if (list) style["--gk-port"] = PORT_COLOURS[types[0]];
  const label = typeLabel(types);
  return (
    <Handle
      id={handleId(side, name)}
      type={side === "in" ? "target" : "source"}
      position={side === "in" ? Position.Left : Position.Right}
      className={`gk-handle ${fit}${types.length > 1 ? " gk-union" : ""}${list ? " gk-list" : ""}`}
      style={style}
      data-testid={`port-${nodeId}-${side}-${name}`}
      data-type={types.join("|")}
      data-access={list ? "list" : "item"}
      onMouseEnter={(e) => {
        if (refusal) {
          store.set({ tip: { text: refusal, x: e.clientX, y: e.clientY } });
          return;
        }
        showTip(
          e,
          `${name}: ${list ? strings.listOf(label) : label}`,
          portSummary(store.getState(), nodeId, side, name),
        );
      }}
      onMouseLeave={hideTip}
    />
  );
}
