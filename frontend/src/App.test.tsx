import { fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ComponentEntry, GraphView, NodeView, PortView } from "./apiTypes";
import { fittingPort, groupsOf, placeOf } from "./catalog";
import { fileBadge } from "./components/FolderTree";
import { Ribbon } from "./components/Ribbon";
import { TextNode } from "./components/nodes/TextNode";
import { groupBox } from "./components/Groups";
import type { GkNode } from "./components/nodes/kinds";
import { exportPath, workflowFiles } from "./components/TopBar";
import { clipOf, initialState, portSummary, reduceEvent, Store, store } from "./store";
import { strings } from "./strings";
import { canConnect, connectionError, portTypes } from "./types";
import { ApiError, type Api } from "./api";
import { PARAM_ENTRIES } from "./testFixtures";

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
    dirty: false,
    can_undo: false,
    can_redo: false,
    recovery: false,
  };
}

function entry(ref: string, category: string, extra: Partial<ComponentEntry> = {}): ComponentEntry {
  return {
    ref,
    version: "0",
    origin: "builtin",
    name: ref,
    category,
    group: "Other",
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
    ["Boolean", "Text", true],
    ["Boolean", "Number", false],
    ["Number", "Boolean", false],
    ["Color", "Color", true],
    ["Colormap", "Color", false],
  ] as const)("%s → %s: %s", (out, input, ok) => {
    expect(canConnect(out, input)).toBe(ok);
  });

  test("union inputs and resolved like: outputs", () => {
    expect(connectionError(["Raster"], ["Table", "Vector"])).toBe(
      "Raster can't connect to Table | Vector",
    );
    expect(connectionError(["Vector"], ["Table", "Vector"])).toBeNull();
    expect(connectionError(["Table", "Vector"], ["Vector"])).toBeNull();
    const out: PortView = { name: "o", type: "Table", types: ["Table", "Vector"], access: "item" };
    expect(portTypes(out)).toEqual(["Table", "Vector"]);
    expect(portTypes({ ...out, resolved_type: "Vector" })).toEqual(["Vector"]);
  });
});

describe("catalog", () => {
  test("ribbon groups follow the tab's order; search shows Tab › Group", () => {
    const lib = [
      entry("builtin/raster/read", "Raster", { group: "Files" }),
      entry("builtin/raster/clip", "Raster", { group: "Extent" }),
      entry("builtin/raster/write", "Raster", { group: "Files" }),
      entry("fake/raster/x", "Raster"),
      entry("builtin/model/rf", "Model", { group: "Train" }),
    ];
    const tab = { name: "Raster", colour: "#0B7A7C", groups: ["Files", "Bands", "Extent", "Other"] };
    expect(
      groupsOf(lib, tab).map((g) => [g.group, g.entries.map((e) => e.ref)]),
    ).toEqual([
      ["Files", ["builtin/raster/read", "builtin/raster/write"]],
      ["Extent", ["builtin/raster/clip"]],
      ["Other", ["fake/raster/x"]],
    ]);
    expect(placeOf(lib[1])).toBe("Raster › Extent");
    expect(placeOf(PARAM_ENTRIES[0])).toBe("Params › Input");
  });

  test("the ribbon draws the server's tabs and labelled groups", () => {
    const raster = [
      entry("builtin/raster/read", "Raster", { name: "Read Raster", group: "Files" }),
      entry("builtin/raster/clip", "Raster", { name: "Clip", group: "Extent" }),
    ];
    store.set({
      ...initialState,
      components: [...PARAM_ENTRIES, ...raster],
      tabs: [
        { name: "Params", colour: "#475569", groups: ["Input", "Inspect", "Map"] },
        { name: "Raster", colour: "#0B7A7C", groups: ["Files", "Extent"] },
      ],
    });
    const { unmount } = render(
      <ReactFlowProvider>
        <Ribbon />
      </ReactFlowProvider>,
    );
    const labels = () =>
      [...document.querySelectorAll(".gk-ribbon-group-label")].map((el) => el.textContent);
    expect(screen.getAllByRole("button", { name: /^(Params|Raster)$/ }).map((b) => b.textContent))
      .toEqual(["Params", "Raster"]);
    expect(labels()).toEqual(["Input", "Inspect", "Map"]);
    fireEvent.click(screen.getByTestId("tab-Raster"));
    expect(labels()).toEqual(["Files", "Extent"]);
    expect(screen.getByTestId("ribbon-group-Extent").textContent).toContain("Clip");
    const icon = screen.getByTestId("ribbon-builtin/raster/clip").querySelector(".gk-button-icon");
    expect((icon as HTMLElement).style.color).toBe("rgb(11, 122, 124)");
    fireEvent.change(screen.getByTestId("ribbon-search"), { target: { value: "clip" } });
    expect(document.querySelector(".gk-search-results")?.textContent).toContain("Raster › Extent");
    unmount();
    store.set({ ...initialState });
  });

  test("a wire dropped in empty space fits the first compatible port", () => {
    const rf = entry("builtin/model/rf", "Model", {
      inputs: [
        { name: "table", type: "Table", access: "item" },
        { name: "n_trees", type: "Number", access: "item" },
      ],
      outputs: [{ name: "model", type: "Model", access: "item" }],
    });
    const from = {
      nodeId: "n1",
      port: "value",
      side: "out" as const,
      types: ["Number" as const],
    };
    expect(fittingPort(rf, from)).toBe("n_trees");
    expect(fittingPort(rf, { ...from, types: ["Raster"] })).toBeNull();
    const [text, slider, panel] = PARAM_ENTRIES;
    expect(fittingPort(slider, { ...from, side: "in", types: ["Text"] })).toBe("value");
    expect(fittingPort(text, { ...from, side: "in", types: ["Number"] })).toBeNull();
    expect(fittingPort(panel, { ...from, types: ["Raster"] })).toBe("data");
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
  const g = graph(
    [node("n1"), node("n2", { component: "builtin/model/rf", title: "RF" })],
    [{ from: ["n1", "value"], to: ["n2", "target"] }],
  );
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

describe("Export .py (SPEC 10)", () => {
  test("the default path sits next to the workflow", () => {
    expect(exportPath(null)).toBe("workflow.py");
    expect(exportPath("examples/imd.geoknit")).toBe("examples/imd.py");
  });

  test("an existing file is replaced only after confirming", async () => {
    const exportPy = vi.fn(async (path?: string, overwrite = false) => {
      if (!overwrite) throw new ApiError(`${path} already exists`, 409);
      return { script: "", path: path ?? null, warnings: [] };
    });
    const s = new Store(fakeApi({ exportPy, files: vi.fn(async () => ({}) as never) }));
    expect(await s.exportPy("imd", () => false)).toBe(false);
    expect(exportPy).toHaveBeenCalledTimes(1);
    expect(exportPy).toHaveBeenLastCalledWith("imd.py");

    const asked: string[] = [];
    expect(await s.exportPy("imd.py", (m) => (asked.push(m), true))).toBe(true);
    expect(asked).toEqual([strings.overwriteScript("imd.py already exists")]);
    expect(exportPy).toHaveBeenLastCalledWith("imd.py", true);
    expect(s.getState().toast?.message).toBe(strings.exported("imd.py"));
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

describe("editing helpers", () => {
  const wires = [{ from: ["n1", "value"], to: ["n2", "data"] }] as GraphView["workflow"]["wires"];

  test("a port's summary: its own output, or the output wired into it, after a run", () => {
    const g = graph(
      [node("n1", { state: "done" }), node("n2", { component: "param/panel" })],
      wires,
    );
    const state = { ...initialState, graph: g, summaries: { n1: { value: "Text 'hi'" } } };
    expect(portSummary(state, "n1", "out", "value")).toBe("Text 'hi'");
    expect(portSummary(state, "n2", "in", "data")).toBe("Text 'hi'");
    expect(portSummary(state, "n2", "in", "other")).toBeNull();
    const stale = { ...state, graph: graph([node("n1", { state: "out_of_date" })], wires) };
    expect(portSummary(stale, "n1", "out", "value")).toBeNull();
  });

  test("copy keeps only the wires among the copied nodes", () => {
    const g = graph(
      [node("n1"), node("n2"), node("n3")],
      [...wires, { from: ["n2", "data"], to: ["n3", "text"] }],
    );
    g.workflow.nodes = ["n1", "n2", "n3"].map((id) => ({ id, position: [0, 0] }));
    const clip = clipOf(g, ["n1", "n2"]);
    expect(clip.nodes.map((n) => n.id)).toEqual(["n1", "n2"]);
    expect(clip.wires).toEqual(wires);
  });

  test("Open lists every .geoknit file in the project", () => {
    const tree = {
      name: "p",
      path: "",
      kind: "dir" as const,
      children: [
        { name: "a.geoknit", path: "a.geoknit", kind: "file" as const },
        {
          name: "data",
          path: "data",
          kind: "dir" as const,
          children: [
            { name: "x.tif", path: "data/x.tif", kind: "file" as const },
            { name: "b.GEOKNIT", path: "data/b.GEOKNIT", kind: "file" as const },
          ],
        },
      ],
    };
    expect(workflowFiles(tree)).toEqual(["a.geoknit", "data/b.GEOKNIT"]);
    expect(workflowFiles(null)).toEqual([]);
  });

  test("a group box wraps its measured nodes with room for the label", () => {
    const n = (id: string, x: number, y: number) =>
      ({ id, position: { x, y }, measured: { width: 100, height: 50 }, data: {} }) as GkNode;
    const box = groupBox({ title: "G", nodes: ["a", "b"] }, [
      n("a", 0, 0),
      n("b", 200, 100),
      n("c", 900, 900),
    ]);
    expect(box).toEqual({ x: -14, y: -38, w: 328, h: 202 });
    expect(groupBox({ title: "G", nodes: ["zz"] }, [n("a", 0, 0)])).toBeNull();
  });
});
