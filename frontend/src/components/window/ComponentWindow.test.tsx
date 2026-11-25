import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { GraphView, NodeView } from "../../apiTypes";
import { initialState, reduceEvent, store } from "../../store";
import { strings } from "../../strings";
import { ComponentWindow, wiredLabel } from "./ComponentWindow";
import { errorLine, freshName, parseValue, valueText } from "./values";

// Monaco does not run in jsdom: a textarea stands in for it.
vi.mock("./CodeEditor", () => ({
  CodeEditor: (p: { value: string; onChange: (v: string) => void }) => (
    <textarea data-testid="code" value={p.value} onChange={(e) => p.onChange(e.target.value)} />
  ),
}));

const SOURCE = `# geoknit: component
# name: Random Forest
# --- settings ---
n_trees = 100  # range: 10..1000
criterion = "gini"  # options: gini | entropy
max_depth = None
# --- code ---
model = 1
`;

function rf(extra: Partial<NodeView> = {}): NodeView {
  return {
    id: "n2",
    component: "builtin/model/random_forest",
    title: "Random Forest",
    state: "out_of_date",
    position: [0, 0],
    display: "default",
    category: "Model",
    inputs: [
      { name: "table", type: "Table", access: "item" },
      { name: "max_depth", type: "Number", access: "item" },
    ],
    outputs: [{ name: "model", type: "Model", access: "item" }],
    source: SOURCE,
    modified: false,
    parse_error: null,
    settings: [
      { name: "n_trees", value: 100, widget: "number", options: null, range: [10, 1000] },
      {
        name: "criterion",
        value: "gini",
        widget: "dropdown",
        options: ["gini", "entropy"],
        range: null,
      },
      { name: "max_depth", value: null, widget: "text", options: null, range: null },
    ],
    ...extra,
  };
}

function graphOf(nodes: NodeView[], wires: GraphView["workflow"]["wires"] = []): GraphView {
  return {
    workflow: { nodes: [], wires, groups: [], view: {} },
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

const slider: NodeView = {
  id: "n1",
  component: "param/slider",
  title: "Number Slider",
  state: "done",
  position: [0, 0],
  display: "default",
  inputs: [],
  outputs: [{ name: "value", type: "Number", access: "item" }],
  value: 300,
};

function open(view: NodeView, wires: GraphView["workflow"]["wires"] = []) {
  const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
  vi.spyOn(store, "loadOutput").mockResolvedValue();
  store.set({ graph: graphOf([slider, view], wires), windowNode: null, logs: {}, errors: {} });
  act(() => store.openWindow(view.id));
  render(<ComponentWindow />);
  return patch;
}

afterEach(() => {
  vi.restoreAllMocks();
  act(() => store.set({ ...initialState }));
});

describe("settings values", () => {
  test("show as Python literals and read back typed", () => {
    expect(valueText(null)).toBe("None");
    expect(valueText(true)).toBe("True");
    expect(valueText([1, "a", null])).toBe('[1, "a", None]');
    expect(parseValue("12", null)).toBe(12);
    expect(parseValue("None", 5)).toBeNull();
    expect(parseValue("False", null)).toBe(false);
    expect(parseValue("[1, 'b', None]", null)).toEqual([1, "b", null]);
    expect(parseValue("12", "text")).toBe("12"); // a text setting stays text
    expect(parseValue("hello", null)).toBe("hello");
  });

  test("parse error line and fresh port names", () => {
    expect(errorLine("line 7: settings block: x")).toBe(7);
    expect(errorLine("missing the line")).toBeNull();
    expect(freshName("x", ["x1", "x2"])).toBe("x3");
  });
});

describe("Output events", () => {
  test("started clears the log, log lines append", () => {
    let s = reduceEvent(
      { ...initialState, logs: { n2: ["old"] } },
      { type: "started", node: "n2" },
    );
    expect(s.logs.n2).toEqual([]);
    s = reduceEvent(s, { type: "log", node: "n2", line: "trained" });
    expect(s.logs.n2).toEqual(["trained"]);
  });
});

describe("component window", () => {
  test("wired inputs name their source; unwired ones offer their default", () => {
    const wires = [
      { from: ["n1", "value"] as [string, string], to: ["n2", "table"] as [string, string] },
    ];
    expect(wiredLabel(graphOf([slider, rf()], wires), "n2", "table")).toBe(
      strings.wiredSlider("300"),
    );
    open(rf(), wires);
    expect(screen.getByTestId("input-table").textContent).toContain("Number Slider = 300");
    expect((screen.getByTestId("setting-max_depth") as HTMLInputElement).value).toBe("None");
  });

  test("a settings change is sent as a settings patch", () => {
    const patch = open(rf());
    const field = screen.getByTestId("setting-n_trees");
    fireEvent.change(field, { target: { value: "500" } });
    fireEvent.blur(field);
    expect(patch).toHaveBeenCalledWith("n2", { settings: { n_trees: 500 } });
    fireEvent.change(screen.getByTestId("setting-criterion"), { target: { value: "1" } });
    expect(patch).toHaveBeenCalledWith("n2", { settings: { criterion: "entropy" } });
  });

  test("code edits are applied when leaving the Code tab", async () => {
    const patch = open(rf());
    fireEvent.click(screen.getByTestId("window-tab-code"));
    const code = await screen.findByTestId("code");
    fireEvent.change(code, { target: { value: SOURCE.replace("model = 1", "model = 2") } });
    await act(async () => fireEvent.click(screen.getByTestId("window-tab-settings")));
    expect(patch).toHaveBeenCalledWith("n2", {
      source: SOURCE.replace("model = 1", "model = 2"),
    });
  });

  test("a broken settings block disables the Settings tab and shows the error", () => {
    open(rf({ parse_error: "line 4: settings block: invalid syntax" }));
    expect(screen.getByTestId("settings-parse-error").textContent).toContain("line 4");
    expect(
      (screen.getByTestId("setting-n_trees") as HTMLInputElement).closest("fieldset")!.disabled,
    ).toBe(true);
  });

  test("Script components edit their ports; renames carry the old name", () => {
    const patch = open(
      rf({
        id: "n3",
        title: "Python",
        category: "Script",
        settings: [],
        inputs: [{ name: "raster", type: "Raster", access: "item" }],
        outputs: [{ name: "out", type: "Text", access: "item" }],
      }),
    );
    const name = screen.getByTestId("port-name-raster");
    fireEvent.change(name, { target: { value: "image" } });
    fireEvent.blur(name);
    expect(patch).toHaveBeenLastCalledWith("n3", {
      ports: {
        inputs: [{ name: "image", type: "Raster", access: "item", file: null, was: "raster" }],
        outputs: [{ name: "out", type: "Text", access: "item", file: null }],
      },
    });
    fireEvent.click(screen.getByTestId("add-output"));
    expect(patch.mock.lastCall?.[1].ports?.outputs.map((p) => p.name)).toEqual(["out", "y1"]);
    fireEvent.change(screen.getByTestId("port-type-out"), { target: { value: "Raster" } });
    expect(patch.mock.lastCall?.[1].ports?.outputs[0]).toMatchObject({
      name: "out",
      type: "Raster",
    });
    fireEvent.click(screen.getByTestId("port-remove-raster"));
    expect(patch.mock.lastCall?.[1].ports?.inputs).toEqual([]);
  });

  test("Output shows the log and the traceback", () => {
    open(rf({ state: "error" }));
    act(() =>
      store.set({ logs: { n2: ["hello"] }, errors: { n2: 'File "Random Forest", line 9' } }),
    );
    expect(screen.getByTestId("output").textContent).toContain("hello");
    expect(screen.getByTestId("output-error").textContent).toContain("line 9");
  });
});
