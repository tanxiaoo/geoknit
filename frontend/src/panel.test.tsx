// Change 01 step 8: the Panel viewer (section 11): one view per kind of value, and the
// table grid paging from GET /api/table/{key}.

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { api, ApiError } from "./api";
import type { GraphView, NodeOutput, NodeView, PanelView, TableView } from "./apiTypes";
import { PanelNode } from "./components/nodes/PanelNode";
import { cellText, columnWidths } from "./components/nodes/PanelView";
import { initialState, store } from "./store";

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

const source = view("n1", { outputs: [{ name: "out", type: "Any", access: "item" }] });
const panel = view("p1", {
  component: "param/panel",
  title: "Panel",
  inputs: [{ name: "data", type: "Any", access: "item" }],
  outputs: [{ name: "data", type: "Any", access: "item", like: "data" }],
});

function graphOf(nodes: NodeView[]): GraphView {
  return {
    workflow: {
      nodes: [],
      wires: [{ from: ["n1", "out"], to: ["p1", "data"] }],
      groups: [],
      view: {},
    },
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

/** Draw the Panel showing ``shown``, with the given paging (what /output said). */
function drawPanel(shown: PanelView, diskCache = true) {
  store.set({
    graph: graphOf([source, panel]),
    summaries: { p1: { data: "describe() text" } },
    views: { p1: { data: shown } },
    paging: { p1: { key: "n1.out", diskCache } },
    ramps: { viridis: ["#440154", "#21918c", "#fde725"] },
  });
  const props = { id: "p1", data: { view: panel }, selected: false };
  return render(
    <ReactFlowProvider>
      <PanelNode {...(props as unknown as Parameters<typeof PanelNode>[0])} />
    </ReactFlowProvider>,
  );
}

function table(rows: number, shown = rows, extra: Partial<TableView> = {}): TableView {
  return {
    kind: "table",
    type: "Table",
    columns: ["name", "value"],
    rows: Array.from({ length: shown }, (_, i) => [`row ${i}`, i * 1.5]),
    index: Array.from({ length: shown }, (_, i) => i),
    total_rows: rows,
    offset: 0,
    geometry: [],
    ...extra,
  };
}

const text = () => screen.getByTestId("panel-text-p1").textContent;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  store.set({ ...initialState });
});

describe("Panel: each kind of value (SPEC table)", () => {
  test("Number, Text and Boolean show the value", () => {
    drawPanel({ kind: "value", type: "Number", value: 2.5 });
    expect(text()).toBe("2.5");
    cleanup();
    drawPanel({ kind: "value", type: "Number", value: "nan" });
    expect(text()).toBe("nan");
    cleanup();
    drawPanel({ kind: "value", type: "Text", value: "two\nlines" });
    expect(text()).toBe("two\nlines");
    cleanup();
    drawPanel({ kind: "value", type: "Boolean", value: false });
    expect(text()).toBe("False");
  });

  test("a Color shows a swatch and the hex value", () => {
    drawPanel({ kind: "color", type: "Color", value: "#FF000080" });
    expect(screen.getByTestId("panel-swatch-p1").style.background).toBe("rgba(255, 0, 0, 0.5)");
    expect(text()).toBe("#FF000080");
  });

  test("a continuous Colormap shows its gradient and name", () => {
    drawPanel({
      kind: "colormap",
      type: "Colormap",
      value: { kind: "continuous", name: "viridis", min: null, max: null, reverse: false },
    });
    expect(screen.getByTestId("panel-ramp-p1").style.background).toContain("linear-gradient");
    expect(text()).toBe("viridis");
  });

  test("a classes Colormap shows one chip per class with its label", () => {
    drawPanel({
      kind: "colormap",
      type: "Colormap",
      value: {
        kind: "classes",
        classes: [
          [1, "#FF0000", "urban"],
          [2, "#00FF00", "green"],
        ],
        other: null,
      },
    });
    expect(screen.getByTestId("panel-class-p1-0").textContent).toBe("urban");
    expect(screen.getByTestId("panel-class-p1-1").textContent).toBe("green");
    expect(screen.queryByTestId("panel-class-p1-2")).toBeNull();
  });

  test("a list shows one row per element with its index", () => {
    drawPanel({
      kind: "list",
      type: null,
      count: 53,
      items: [
        { kind: "value", type: "Number", value: 3 },
        { kind: "color", type: "Color", value: "#00FF00" },
        { kind: "summary", type: "Raster", text: "Raster 10×10, 1 band" },
        ...Array.from({ length: 47 }, () => ({
          kind: "value" as const,
          type: "Text" as const,
          value: "x",
        })),
      ],
    });
    expect(screen.getByTestId("panel-header-p1").textContent).toBe("list of 53");
    expect(screen.getByTestId("panel-item-p1-0").textContent).toBe("03");
    expect(screen.getByTestId("panel-item-p1-1").textContent).toBe("1#00FF00");
    expect(screen.getByTestId("panel-item-p1-2").textContent).toBe("2Raster 10×10, 1 band");
    expect(text()).toContain("… 3 more");
  });

  test("a Table shows the header line and a grid with an index column", () => {
    drawPanel(table(2));
    expect(screen.getByTestId("panel-header-p1").textContent).toBe("2 rows × 2 columns");
    const headers = [...screen.getByTestId("panel-grid-p1").querySelectorAll("thead th")];
    expect(headers.map((h) => h.textContent)).toEqual(["", "name", "value"]);
    const cells = [...screen.getByTestId("panel-row-p1-1").children].map((c) => c.textContent);
    expect(cells).toEqual(["1", "row 1", "1.5"]);
    expect(screen.queryByTestId("panel-note-p1")).toBeNull();
  });

  test("a Vector's geometry column shows the geometry type name", () => {
    drawPanel({
      kind: "table",
      type: "Vector",
      columns: ["id", "geometry"],
      rows: [
        [7, "Point"],
        [8, null],
      ],
      index: [0, 1],
      total_rows: 2,
      offset: 0,
      geometry: ["geometry"],
    });
    expect(screen.getByTestId("panel-header-p1").textContent).toBe("2 rows × 2 columns");
    const geom = screen.getByTestId("panel-row-p1-0").children[2];
    expect(geom.textContent).toBe("Point");
    expect(geom.className).toBe("gk-panel-geom");
    expect(screen.getByTestId("panel-row-p1-1").children[2].textContent).toBe("");
  });

  test("a Raster (or Model) shows the describe() summary", () => {
    drawPanel({ kind: "summary", type: "Raster", text: "Raster 10×10\nEPSG:32632" });
    expect(text()).toBe("Raster 10×10\nEPSG:32632");
  });

  test("before a run, the Panel says so", () => {
    store.set({ graph: graphOf([source, { ...panel, state: "out_of_date" }]) });
    const props = { id: "p1", data: { view: { ...panel, state: "out_of_date" } }, selected: false };
    render(
      <ReactFlowProvider>
        <PanelNode {...(props as unknown as Parameters<typeof PanelNode>[0])} />
      </ReactFlowProvider>,
    );
    expect(text()).toBe("run to update");
  });
});

describe("Panel: table grid", () => {
  test("cells and widths: missing blank, booleans True/False, widths from header and page", () => {
    expect([null, true, 0, "inf"].map(cellText)).toEqual(["", "True", "0", "inf"]);
    const t = table(1000, 2);
    // index: "999" → 3 (+2); name: "row 0" → 5 (+2); value: "value" → 5 (+2)
    expect(columnWidths(t)).toEqual([5, 7, 7]);
    const wide = table(1, 1, { columns: ["c"], rows: [["x".repeat(100)]], index: [0] });
    expect(columnWidths(wide)).toEqual([5, 34]); // clamped to 32 characters
  });

  /** Pretend the grid is scrolled to its end (jsdom does no layout). */
  function scrollToEnd() {
    const grid = screen.getByTestId("panel-grid-p1");
    Object.defineProperty(grid, "scrollHeight", { configurable: true, value: 4000 });
    Object.defineProperty(grid, "clientHeight", { configurable: true, value: 100 });
    Object.defineProperty(grid, "scrollTop", { configurable: true, value: 3900 });
    fireEvent.scroll(grid);
    return grid;
  }

  test("scrolling near the end loads the next page", async () => {
    const page = table(1000, 200, { offset: 200 });
    page.index = page.index.map((i) => Number(i) + 200);
    const spy = vi.spyOn(api, "table").mockResolvedValue(page);
    drawPanel(table(1000, 200));
    expect(screen.getByTestId("panel-header-p1").textContent).toBe("1000 rows × 2 columns");
    expect(screen.getByTestId("panel-grid-p1").dataset.rows).toBe("200");
    scrollToEnd();
    await waitFor(() => expect(screen.getByTestId("panel-grid-p1").dataset.rows).toBe("400"));
    expect(spy).toHaveBeenCalledWith("n1.out", 200, 200);
    expect(screen.getByTestId("panel-row-p1-250").children[0].textContent).toBe("250");
  });

  test("an empty page before total_rows stops paging (no endless re-requests)", async () => {
    const spy = vi.spyOn(api, "table").mockResolvedValue(table(1000, 0, { offset: 200 }));
    drawPanel(table(1000, 200));
    scrollToEnd();
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    // more scrolling and re-renders do not ask again for the same offset
    await act(async () => {});
    scrollToEnd();
    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("panel-grid-p1").dataset.rows).toBe("200");
  });

  test("a 404 while paging shows as an error in the grid", async () => {
    vi.spyOn(api, "table").mockRejectedValue(new ApiError("not in the cache; run first", 404));
    drawPanel(table(1000, 200));
    scrollToEnd();
    expect(await screen.findByTestId("panel-error-p1")).toHaveProperty(
      "textContent",
      "could not load more rows: not in the cache; run first",
    );
    expect(screen.queryByTestId("panel-note-p1")).toBeNull();
  });

  test("with the disk cache off: the first page and a note, no paging", async () => {
    const spy = vi.spyOn(api, "table");
    drawPanel(table(1000, 200), false);
    expect(screen.getByTestId("panel-note-p1").textContent).toBe(
      "the disk cache is off: only the first 200 rows",
    );
    scrollToEnd();
    await act(async () => {});
    expect(spy).not.toHaveBeenCalled();
  });

  test("the paging key is fetched from the node's output when not known", async () => {
    const out: NodeOutput = {
      state: "done",
      log: [],
      error: null,
      outputs: { data: "Table" },
      views: {},
      keys: { data: "n1.out" },
      disk_cache: true,
    };
    const output = vi.spyOn(api, "output").mockResolvedValue(out);
    drawPanel(table(1000, 200));
    act(() => store.set({ paging: {} }));
    await waitFor(() =>
      expect(store.getState().paging.p1).toEqual({ key: "n1.out", diskCache: true }),
    );
    expect(output).toHaveBeenCalledWith("p1");
  });
});
