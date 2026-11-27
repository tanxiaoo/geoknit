// Change 01 step 3: list values in the frontend (SPEC 3 "List values"): the drag rule,
// double-line ports and wires, and list summaries in the tooltip.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Position, ReactFlowProvider } from "@xyflow/react";
import { afterEach, describe, expect, test } from "vitest";
import type { ComponentEntry, GraphView, NodeView, PortView } from "./apiTypes";
import { fittingPort } from "./catalog";
import { paramEntry } from "./testFixtures";
import { ComponentNode } from "./components/nodes/ComponentNode";
import { PanelNode } from "./components/nodes/PanelNode";
import { DragContext, dragRefusal, Port, type DragFrom } from "./components/nodes/Port";
import { TypedEdge } from "./components/TypedEdge";
import { initialState, store } from "./store";
import { carriesList, sameTypeWires, tipSummary, wireError } from "./types";

const REFUSAL = 'Numbers gives a list; "x" takes one value — use List Item';

function view(id: string, extra: Partial<NodeView> = {}): NodeView {
  return {
    id,
    component: "inline",
    title: id,
    state: "done",
    position: [0, 0],
    display: "text",
    inputs: [],
    outputs: [],
    ...extra,
  };
}

function graphOf(nodes: NodeView[]): GraphView {
  return {
    workflow: { nodes: [], wires: [], groups: [], view: {} },
    nodes: Object.fromEntries(nodes.map((n) => [n.id, n])),
    out_of_date: 0,
    path: null,
    trusted: true,
    running: false,
    dirty: false,
    can_undo: false,
    can_redo: false,
    recovery: false,
  };
}

const numbers = view("n1", {
  title: "Numbers",
  outputs: [{ name: "values", type: "Number", access: "list", resolved_access: "list" }],
});
const sum = view("n2", {
  title: "Sum",
  inputs: [
    { name: "x", type: "Number", access: "item" },
    { name: "xs", type: "Number", access: "list" },
  ],
  outputs: [{ name: "total", type: "Number", access: "item", resolved_access: "item" }],
});

const NUMBERS_DRAG: DragFrom = {
  nodeId: "n1",
  side: "out",
  types: ["Number"],
  name: "values",
  title: "Numbers",
  list: true,
};

// A Panel passing a list of Numbers through.
const panel = view("p1", {
  component: "param/panel",
  title: "Panel",
  inputs: [{ name: "data", type: "Any", access: "item" }],
  outputs: [
    {
      name: "data",
      type: "Any",
      access: "item",
      like: "data",
      resolved_type: "Number",
      resolved_access: "list",
    },
  ],
});

/** A node component rendered with the props React Flow would give it. */
function drawNode(Node: typeof ComponentNode | typeof PanelNode, v: NodeView) {
  const props = { id: v.id, data: { view: v }, selected: false };
  return <Node {...(props as unknown as Parameters<typeof ComponentNode>[0])} />;
}

afterEach(() => {
  cleanup(); // unmount before the store resets, so nothing re-renders outside act()
  store.set({ ...initialState });
});

describe("drag rule: a list output into an item input", () => {
  const list = { title: "Numbers", types: ["Number" as const], list: true };

  test("is refused with the server's message; list and Any item inputs take it", () => {
    expect(wireError(list, { name: "x", types: ["Number"], access: "item" })).toBe(REFUSAL);
    expect(wireError(list, { name: "xs", types: ["Number"], access: "list" })).toBeNull();
    // Panel's data: an Any item input takes the list whole
    expect(wireError(list, { name: "data", types: ["Any"], access: "item" })).toBeNull();
    // a single value goes anywhere its type fits
    const one = { ...list, list: false };
    expect(wireError(one, { name: "x", types: ["Number"], access: "item" })).toBeNull();
    // a type mismatch is reported first
    expect(wireError(list, { name: "r", types: ["Raster"], access: "item" })).toBe(
      "Number can't connect to Raster",
    );
  });

  test("resolved_access decides on /api/graph outputs, access on /api/components", () => {
    const panelOut: PortView = { name: "data", type: "Number", access: "item", like: "data" };
    expect(carriesList(panelOut)).toBe(false);
    expect(carriesList({ ...panelOut, resolved_access: "list" })).toBe(true);
    expect(carriesList({ ...panelOut, access: "list" })).toBe(true);
    expect(carriesList({ ...panelOut, access: "list", resolved_access: "item" })).toBe(false);
  });

  test("works from either end of the drag", () => {
    const types = ["Number" as const];
    const fromOut: DragFrom = { ...NUMBERS_DRAG };
    const x = { side: "in" as const, name: "x", types, list: false, title: "Sum" };
    expect(dragRefusal(fromOut, x)).toBe(REFUSAL);
    expect(dragRefusal(fromOut, { ...x, name: "xs", list: true })).toBeNull();
    const fromIn: DragFrom = { nodeId: "n2", side: "in", types, name: "x", title: "Sum" };
    const values = { side: "out" as const, name: "values", types, list: true, title: "Numbers" };
    expect(dragRefusal(fromIn, values)).toBe(REFUSAL);
    expect(dragRefusal({ ...fromIn, name: "xs", list: true }, values)).toBeNull();
  });

  test("a wire dropped in empty space skips item inputs for a list", () => {
    const entry: ComponentEntry = {
      ref: "user/sum",
      version: "0",
      origin: "user",
      name: "Sum",
      category: "Script",
      group: "Other",
      icon: null,
      description: "",
      inputs: sum.inputs,
      outputs: [{ name: "total", type: "Number", access: "item" }],
      requires: [],
      settings: [],
    };
    const types = ["Number" as const];
    const from = { nodeId: "n1", port: "values", side: "out" as const, types, list: true };
    expect(fittingPort(entry, from)).toBe("xs");
    expect(fittingPort(entry, { ...from, list: false })).toBe("x");
    const panel = paramEntry("param/panel");
    expect(fittingPort(panel, from)).toBe("data");
    const lister = { ...entry, outputs: [numbers.outputs[0]] };
    const into = { nodeId: "n2", port: "x", side: "in" as const, types };
    expect(fittingPort(lister, into)).toBeNull();
    expect(fittingPort(lister, { ...into, port: "xs", list: true })).toBe("values");
  });

  test("an item input under a list drag is marked misfit and shows the refusal", () => {
    store.set({ graph: graphOf([numbers, sum]) });
    render(
      <ReactFlowProvider>
        <DragContext.Provider value={NUMBERS_DRAG}>
          <Port nodeId="n2" side="in" name="x" types={["Number"]} />
          <Port nodeId="n2" side="in" name="xs" types={["Number"]} list />
        </DragContext.Provider>
      </ReactFlowProvider>,
    );
    const x = screen.getByTestId("port-n2-in-x");
    expect(x.className).toMatch(/gk-misfit/);
    expect(screen.getByTestId("port-n2-in-xs").className).toMatch(/gk-fits/);
    fireEvent.mouseEnter(x, { clientX: 1, clientY: 1 });
    expect(store.getState().tip?.text).toBe(REFUSAL);
  });
});

describe("drag rule: one type into a list input an output is like", () => {
  const SAME = 'all wires into "items" must have the same type';
  // Sort List: `items: {type: [Number, Text], access: list}`, `sorted: {like: items}`
  const sorter = view("n3", {
    title: "Sort List",
    inputs: [{ name: "items", type: "Number", types: ["Number", "Text"], access: "list" }],
    outputs: [{ name: "sorted", type: "Number", access: "list", like: "items" }],
  });
  const words = view("n4", { outputs: [{ name: "w", type: "Text", access: "list" }] });
  const wired = (from: string[]): GraphView => ({
    ...graphOf([numbers, sum, sorter, words]),
    workflow: {
      nodes: [],
      wires: from.map((f) => ({ from: [f, f === "n1" ? "values" : "w"], to: ["n3", "items"] })),
      groups: [],
      view: {},
    },
  });

  test("a second type is refused, as the server does", () => {
    const g = wired(["n1"]); // a Number list is in
    const into = sameTypeWires(g, "n3", "items");
    expect(into).toEqual([["Number"]]);
    const dst = { name: "items", types: sorter.inputs[0].types!, access: "list" as const };
    const text = { title: "Words", types: ["Text" as const], list: true };
    expect(wireError(text, { ...dst, wired: into })).toBe(SAME);
    expect(wireError({ ...text, types: ["Number"] }, { ...dst, wired: into })).toBeNull();
    // Boolean → Text arrives as Text: refused next to Numbers too
    expect(wireError({ title: "Flag", types: ["Boolean"], list: false }, { ...dst, wired: into }))
      .toBe(SAME);
    // an unresolved Panel (Any) is not checked; a type mismatch is still reported first
    expect(wireError({ title: "Panel", types: ["Any"], list: false }, { ...dst, wired: into }))
      .toBeNull();
    expect(wireError({ title: "R", types: ["Raster"], list: false }, { ...dst, wired: into }))
      .toBe("Raster can't connect to Number | Text");
    // without a like: output on it, or with no wires yet, the rule does not apply
    expect(sameTypeWires(wired([]), "n3", "items")).toEqual([]);
    expect(sameTypeWires(g, "n2", "xs")).toBeUndefined();
  });

  test("the input port is marked misfit while dragging, from either end", () => {
    store.set({ graph: wired(["n1"]) });
    const drag: DragFrom = { nodeId: "n4", side: "out", types: ["Text"], name: "w", list: true };
    render(
      <ReactFlowProvider>
        <DragContext.Provider value={drag}>
          <Port nodeId="n3" side="in" name="items" types={["Number", "Text"]} list />
        </DragContext.Provider>
      </ReactFlowProvider>,
    );
    const items = screen.getByTestId("port-n3-in-items");
    expect(items.className).toMatch(/gk-misfit/);
    fireEvent.mouseEnter(items, { clientX: 1, clientY: 1 });
    expect(store.getState().tip?.text).toBe(SAME);
    // dragged from the input: the wired types travel with the drag
    const fromIn: DragFrom = {
      nodeId: "n3",
      side: "in",
      types: ["Number", "Text"],
      name: "items",
      list: true,
      wired: sameTypeWires(wired(["n1"]), "n3", "items"),
    };
    const w = { side: "out" as const, name: "w", types: ["Text" as const], list: true, title: "" };
    expect(dragRefusal(fromIn, w)).toBe(SAME);
  });
});

describe("double-line ports and wires", () => {
  test("list ports are drawn as lists; item ports are not", () => {
    store.set({ graph: graphOf([numbers, sum]) });
    render(
      <ReactFlowProvider>
        {drawNode(ComponentNode, numbers)}
        {drawNode(ComponentNode, sum)}
      </ReactFlowProvider>,
    );
    const out = screen.getByTestId("port-n1-out-values");
    expect(out.dataset.access).toBe("list");
    expect(out.className).toMatch(/gk-list/);
    expect(screen.getByTestId("port-n2-in-xs").dataset.access).toBe("list");
    expect(screen.getByTestId("port-n2-in-x").dataset.access).toBe("item");
    expect(screen.getByTestId("port-n2-out-total").className).not.toMatch(/gk-list/);
  });

  test("a Panel passing a list through draws both ports as lists", () => {
    store.set({ graph: graphOf([panel]) });
    render(
      <ReactFlowProvider>
        {drawNode(PanelNode, panel)}
      </ReactFlowProvider>,
    );
    expect(screen.getByTestId("port-p1-in-data").dataset.access).toBe("list");
    expect(screen.getByTestId("port-p1-out-data").dataset.access).toBe("list");
  });

  test("a list wire is a wide stroke with a gap down the middle", () => {
    const edge = (list: boolean) =>
      render(
        <ReactFlowProvider>
          <svg>
            <TypedEdge
              {...({
                id: `w${list}`,
                source: "n1",
                target: "n2",
                sourceX: 0,
                sourceY: 0,
                targetX: 100,
                targetY: 50,
                sourcePosition: Position.Right,
                targetPosition: Position.Left,
                sourceHandleId: "out:values",
                targetHandleId: "in:xs",
                selected: false,
                data: { colour: "#64748B", faded: false, list },
              } as unknown as Parameters<typeof TypedEdge>[0])}
            />
          </svg>
        </ReactFlowProvider>,
      );
    edge(true);
    expect(screen.getByTestId("wire-wtrue").dataset.access).toBe("list");
    expect(screen.getByTestId("wire-gap-wtrue")).toBeTruthy();
    edge(false);
    expect(screen.getByTestId("wire-wfalse").dataset.access).toBe("item");
    expect(screen.queryByTestId("wire-gap-wfalse")).toBeNull();
  });
});

describe("list summaries", () => {
  const items = Array.from({ length: 12 }, (_, i) => `[${i}] Number ${i}`);
  const summary = ["list of 12 Number", ...items].join("\n");

  test("the tooltip keeps the first line and the first items", () => {
    expect(tipSummary(summary)).toBe(
      ["list of 12 Number", ...items.slice(0, 5), "… 7 more"].join("\n"),
    );
    const short = "list of 2 Number\n[0] Number 1\n[1] Number 2";
    expect(tipSummary(short)).toBe(short);
    const table = "Table 3 rows\na\nb\nc\nd\ne\nf";
    expect(tipSummary(table)).toBe(table);
  });

  test("hovering a list port names it a list and shows its summary", () => {
    store.set({ graph: graphOf([numbers]), summaries: { n1: { values: summary } } });
    render(
      <ReactFlowProvider>
        <Port nodeId="n1" side="out" name="values" types={["Number"]} list />
      </ReactFlowProvider>,
    );
    fireEvent.mouseEnter(screen.getByTestId("port-n1-out-values"), { clientX: 1, clientY: 1 });
    const tip = store.getState().tip?.text ?? "";
    expect(tip.split("\n").slice(0, 3)).toEqual([
      "values: list of Number",
      "list of 12 Number",
      "[0] Number 0",
    ]);
    expect(tip).toContain("… 7 more");
  });

  test("a Panel shows the whole list summary (length and one line per element)", () => {
    const g = graphOf([numbers, panel]);
    g.workflow.wires = [{ from: ["n1", "values"], to: ["p1", "data"] }];
    store.set({ graph: g, summaries: { p1: { data: summary } } });
    render(
      <ReactFlowProvider>
        {drawNode(PanelNode, panel)}
      </ReactFlowProvider>,
    );
    expect(screen.getByTestId("panel-text-p1").textContent).toBe(summary);
  });
});
