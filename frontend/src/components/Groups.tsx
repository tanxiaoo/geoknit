import { useState } from "react";
import { ViewportPortal } from "@xyflow/react";
import type { GroupJson } from "../apiTypes";
import { store } from "../store";
import { strings } from "../strings";
import type { GkNode } from "./nodes/kinds";

const PAD = 14;
const LABEL = 24;

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The box around a group's nodes, once React Flow has measured them. */
export function groupBox(group: GroupJson, nodes: GkNode[]): Box | null {
  const members = nodes.filter((n) => group.nodes.includes(n.id));
  if (!members.length || members.some((n) => !n.measured?.width)) return null;
  const x0 = Math.min(...members.map((n) => n.position.x));
  const y0 = Math.min(...members.map((n) => n.position.y));
  const x1 = Math.max(...members.map((n) => n.position.x + (n.measured?.width ?? 0)));
  const y1 = Math.max(...members.map((n) => n.position.y + (n.measured?.height ?? 0)));
  return {
    x: x0 - PAD,
    y: y0 - PAD - LABEL,
    w: x1 - x0 + 2 * PAD,
    h: y1 - y0 + 2 * PAD + LABEL,
  };
}

interface Props {
  groups: GroupJson[];
  nodes: GkNode[];
  /** Click on a label: select the group's nodes, so they can be dragged together. */
  onSelect: (ids: string[]) => void;
  onMenu: (index: number, x: number, y: number) => void;
}

/** Groups as labelled boxes behind the nodes (SPEC 8). */
export function Groups({ groups, nodes, onSelect, onMenu }: Props) {
  const [editing, setEditing] = useState<number | null>(null);
  return (
    <ViewportPortal>
      {groups.map((g, i) => {
        const box = groupBox(g, nodes);
        if (!box) return null;
        return (
          <div
            key={i}
            className="gk-group"
            style={{
              transform: `translate(${box.x}px, ${box.y}px)`,
              width: box.w,
              height: box.h,
            }}
            data-testid={`group-${i}`}
          >
            {editing === i ? (
              <input
                className="gk-group-title nodrag nopan"
                defaultValue={g.title}
                autoFocus
                onFocus={(e) => e.currentTarget.select()}
                onBlur={(e) => {
                  setEditing(null);
                  const title = e.currentTarget.value.trim();
                  if (title && title !== g.title) void store.renameGroup(i, title);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") e.currentTarget.blur();
                  if (e.key === "Escape") setEditing(null);
                }}
                data-testid={`group-title-input-${i}`}
              />
            ) : (
              <div
                className="gk-group-title nodrag nopan"
                title={strings.renameGroup}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => onSelect(g.nodes)}
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  setEditing(i);
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onMenu(i, e.clientX, e.clientY);
                }}
                data-testid={`group-title-${i}`}
              >
                {g.title}
              </div>
            )}
          </div>
        );
      })}
    </ViewportPortal>
  );
}
