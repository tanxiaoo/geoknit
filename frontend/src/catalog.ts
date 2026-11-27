// What can be added to the canvas: the Params nodes and the component library, both
// from `GET /api/components` in ribbon order (change 01, section 7).

import type { ComponentEntry, PortType, PortView, TabView } from "./apiTypes";
import { strings } from "./strings";
import { carriesList, portTypes, wireError } from "./types";

/** The entries of one tab, by group in the tab's order (entries keep the server's order). */
export function groupsOf(
  library: ComponentEntry[],
  tab: TabView,
): { group: string; entries: ComponentEntry[] }[] {
  return tab.groups
    .map((group) => ({
      group,
      entries: library.filter((e) => e.category === tab.name && e.group === group),
    }))
    .filter((g) => g.entries.length > 0);
}

/** "Tab › Group", shown next to a name in search results. */
export function placeOf(entry: ComponentEntry): string {
  const tab = entry.category === "Params" ? strings.paramsTab : entry.category;
  return strings.tabGroup(tab, entry.group);
}

export function matches(entry: ComponentEntry, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [entry.name, entry.category, entry.group, entry.description, entry.ref].some((s) =>
    s.toLowerCase().includes(q),
  );
}

/** A port a new node should be wired to when dropped from a dragged wire. */
export interface WireFrom {
  nodeId: string;
  port: string;
  side: "in" | "out";
  types: PortType[];
  /** The port carries a list: a list output, or an `access: list` input. */
  list?: boolean;
}

/** The port on ``entry`` that fits ``from``, or null. */
export function fittingPort(entry: ComponentEntry, from: WireFrom): string | null {
  const list = from.list ?? false;
  if (from.side === "out") {
    const src = { title: "", types: from.types, list };
    const fits = (p: PortView) =>
      !wireError(src, { name: p.name, types: portTypes(p), access: p.access });
    return entry.inputs.find(fits)?.name ?? null;
  }
  const dst = { name: from.port, types: from.types, access: list ? "list" : "item" } as const;
  const fits = (p: PortView) =>
    !wireError({ title: "", types: portTypes(p), list: carriesList(p) }, dst);
  return entry.outputs.find(fits)?.name ?? null;
}
