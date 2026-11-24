import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ComponentEntry, GraphView, NodeView } from "./apiTypes";
import { categories, fittingPort, paramEntries } from "./catalog";
import { fileBadge } from "./components/FolderTree";
import { TextNode } from "./components/nodes/TextNode";
import { initialState, reduceEvent, Store, store } from "./store";
import { strings } from "./strings";
import { canConnect } from "./types";
import type { Api } from "./api";

function node(id: string, extra: Partial<NodeView> = {}): NodeView {
  return {
    id,
    component: "param/text",
    title: "Text",
    state: "never_run",
    position: [0, 0],
    display: "default",
    inputs: [],
    outputs: [{ name: "value", type: "Text", access: "item" }],
    ...extra,
  };
}

function graph(nodes: NodeView[], wires: GraphView["workflow"]["wires"] = []): GraphView {
  return {
    workflow: { nodes: [], wires, groups: [], view: {} },
    nodes: Object.fromEntries(nodes.map((n) => [n.id, n])),
    out_of_date: nodes.length,
    path: null,
    trusted: true,
    running: false,
  };
}

function entry(ref: string, category: string, extra: Partial<ComponentEntry> = {}): ComponentEntry {
  return {
    ref,
    version: "0",
    origin: "builtin",
    name: ref,
    category,
    icon: null,
    description: "",
    inputs: [],
    outputs: [],
    requires: [],
    settings: [],
    ...extra,
  };
}

describe("connection rules (SPEC 3)", () => {
  test.each([
    ["Raster", "Raster", true],
    ["Raster", "Number", false],
    ["Number", "Text", true],
    ["Text", "Number", false],
    ["Table", "Any", true],
    ["Any", "Model", true],
    ["Vector", "Raster", false],
  ] as const)("%s → %s: %s", (out, input, ok) => {
    expect(canConnect(out, input)).toBe(ok);
  });
});

describe("catalog", () => {
  test("ribbon tabs: Params, built-ins in SPEC order, then packs", () => {
    const lib = [
      entry("fake/zeta/a", "Zeta"),
      entry("builtin/model/rf", "Model"),
      entry("builtin/raster/read", "Raster"),
    ];
    expect(categories(lib)).toEqual(["Params", "Raster", "Model", "Zeta"]);
  });

  test("a wire dropped in empty space fits the first compatible port", () => {
    const rf = entry("builtin/model/rf", "Model", {
      inputs: [
        { name: "table", type: "Table", access: "item" },
        { name: "n_trees", type: "Number", access: "item" },
      ],
      outputs: [{ name: "model", type: "Model", access: "item" }],
    });
    const from = { nodeId: "n1", port: "value", side: "out" as const, type: "Number" as const };
    expect(fittingPort(rf, from)).toBe("n_trees");
    expect(fittingPort(rf, { ...from, type: "Raster" })).toBeNull();
    const [slider, text, panel] = paramEntries();
    expect(fittingPort(slider, { ...from, side: "in", type: "Text" })).toBe("value");
    expect(fittingPort(text, { ...from, side: "in", type: "Number" })).toBeNull();
    expect(fittingPort(panel, { ...from, type: "Raster" })).toBe("data");
  });
});

test("folder tree badges", () => {
  expect(fileBadge("imd.tif")).toEqual({ letter: "R", kind: "raster" });
  expect(fileBadge("AOI.GPKG")).toEqual({ letter: "V", kind: "vector" });
  expect(fileBadge("imd.geoknit")).toEqual({ letter: "G", kind: "workflow" });
  expect(fileBadge("notes.txt")).toBeNull();
});

describe("events from /ws", () => {
  const start = { ...initialState, graph: graph([node("n1"), node("n2")]) };

  test("states, started, done, error", () => {
    let s = reduceEvent(start, {
      type: "states",
      states: { n1: "out_of_date", n2: "out_of_date" },
      out_of_date: 2,
    });
    expect(s.graph?.nodes.n1.state).toBe("out_of_date");
    s = reduceEvent(s, { type: "started", node: "n1" });
    expect(s.graph?.nodes.n1.state).toBe("running");
    s = reduceEvent(s, { type: "done", node: "n1", outputs: { value: "hi" }, cached: false });
    expect(s.graph?.nodes.n1.state).toBe("done");
    expect(s.summaries.n1).toEqual({ value: "hi" });
    s = reduceEvent(s, { type: "error", node: "n2", traceback: "boom" });
    expect(s.graph?.nodes.n2.state).toBe("error");
    expect(s.errors.n2).toBe("boom");
    s = reduceEvent(s, {
      type: "run_finished",
      report: { ran: ["n1"], cached: [], failed: ["n2"], skipped: [], ok: false },
    });
    expect(s.runCount).toBe(1);
    expect(s.lastReport?.failed).toEqual(["n2"]);
  });
});

function fakeApi(over: Partial<Api> = {}): Api {
  const g = graph([node("n1"), node("n2", { component: "builtin/model/rf", title: "RF" })], [
    { from: ["n1", "value"], to: ["n2", "target"] },
  ]);
  return {
    graph: vi.fn(async () => g),
    patchNode: vi.fn(async () => g.nodes.n1),
    addWire: vi.fn(async () => ({})),
    output: vi.fn(async () => ({ state: null, log: [], error: null, outputs: {} })),
    ...over,
  } as unknown as Api;
}

describe("store", () => {
  test("a value change is named after the input it feeds", async () => {
    const s = new Store(fakeApi());
    await s.refreshGraph();
    await s.patchNode("n1", { value: "IMD" });
    expect(s.getState().lastChange).toBe("target");
  });

  test("a refused wire shows the server's message where it was dropped", async () => {
    const s = new Store(
      fakeApi({
        addWire: vi.fn(async () => {
          throw new Error("Raster can't connect to Number");
        }),
      }),
    );
    await s.refreshGraph();
    expect(await s.addWire(["n1", "value"], ["n2", "x"], { x: 5, y: 6 })).toBe(false);
    expect(s.getState().toast).toMatchObject({
      message: "Raster can't connect to Number",
      x: 5,
      y: 6,
    });
  });
});

describe("Text node", () => {
  afterEach(() => vi.restoreAllMocks());

  test("double-click edits inline and Enter sends the value", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    render(
      <ReactFlowProvider>
        <TextNode
          {...({
            id: "n1",
            data: { view: node("n1", { value: "" }) },
            selected: false,
          } as unknown as Parameters<typeof TextNode>[0])}
        />
      </ReactFlowProvider>,
    );
    fireEvent.doubleClick(screen.getByText(strings.textPlaceholder));
    const input = screen.getByTestId("text-input-n1");
    fireEvent.change(input, { target: { value: "data/imd.tif" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(patch).toHaveBeenCalledWith("n1", { value: "data/imd.tif" });
  });
});
