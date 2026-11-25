import type { Node } from "@xyflow/react";
import type { NodeView } from "../../apiTypes";
import { PARAM_MAP, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT } from "../../types";

export type GkNodeData = { view: NodeView };
export type GkNode = Node<GkNodeData>;

export function nodeKind(view: NodeView): "text" | "slider" | "panel" | "map" | "component" {
  if (view.component === PARAM_TEXT) return "text";
  if (view.component === PARAM_SLIDER) return "slider";
  if (view.component === PARAM_PANEL) return "panel";
  if (view.component === PARAM_MAP) return "map";
  return "component";
}

export const PANEL_SIZE: [number, number] = [220, 120];
