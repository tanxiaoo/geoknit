import type { Node } from "@xyflow/react";
import type { NodeView } from "../../apiTypes";
import {
  PARAM_COLOR,
  PARAM_COLORMAP,
  PARAM_MAP,
  PARAM_NUMBER,
  PARAM_PANEL,
  PARAM_SLIDER,
  PARAM_TEXT,
  PARAM_TOGGLE,
  PARAM_VALUE_LIST,
} from "../../types";

export type GkNodeData = { view: NodeView };
export type GkNode = Node<GkNodeData>;

/** The canvas node type of each Params kind (SPEC 5, change 01 section 8). */
const KINDS = {
  [PARAM_TEXT]: "text",
  [PARAM_NUMBER]: "number",
  [PARAM_SLIDER]: "slider",
  [PARAM_TOGGLE]: "toggle",
  [PARAM_VALUE_LIST]: "value_list",
  [PARAM_COLOR]: "color",
  [PARAM_COLORMAP]: "colormap",
  [PARAM_PANEL]: "panel",
  [PARAM_MAP]: "map",
} as const;

export type NodeKind = (typeof KINDS)[keyof typeof KINDS] | "component";

export function nodeKind(view: NodeView): NodeKind {
  return (KINDS as Record<string, NodeKind>)[view.component] ?? "component";
}

export const PANEL_SIZE: [number, number] = [220, 120];
