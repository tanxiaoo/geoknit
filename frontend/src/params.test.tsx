// Change 01 step 6: the new Params nodes on the canvas and integer mode.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "@xyflow/react";
import type { ComponentType } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { Api } from "./api";
import type { GraphView, NamedRamps, NodeView } from "./apiTypes";
import { ColorNode, pickerValue, withAlpha } from "./components/nodes/ColorNode";
import { ColormapNode, gradientCss, stopsOf } from "./components/nodes/ColormapNode";
import { nodeKind } from "./components/nodes/kinds";
import { NumberNode } from "./components/nodes/NumberNode";
import { SliderWindow } from "./components/nodes/SliderNode";
import { ToggleNode } from "./components/nodes/ToggleNode";
import { rowsToOptions, ValueListNode } from "./components/nodes/ValueListNode";
import { wiredLabel } from "./components/window/ComponentWindow";
import { initialState, Store, store } from "./store";
import { strings } from "./strings";
import {
  PARAM_COLOR,
  PARAM_COLORMAP,
  PARAM_NUMBER,
  PARAM_TOGGLE,
  PARAM_VALUE_LIST,
} from "./types";

function view(component: string, extra: Partial<NodeView> = {}): NodeView {
  const type = extra.outputs?.[0]?.type ?? "Number";
  return {
    id: "n1",
    component,
    title: component,
    state: "never_run",
    position: [0, 0],
    display: "default",
    inputs: [],
    outputs: [{ name: "value", type, types: [type], access: "item" }],
    ...extra,
  };
}

type NodeComponent = ComponentType<Parameters<typeof NumberNode>[0]>;

function show(Node: NodeComponent, v: NodeView) {
  const props = { id: v.id, data: { view: v }, selected: false } as unknown as Parameters<
    typeof NumberNode
  >[0];
  return render(
    <ReactFlowProvider>
      <Node {...props} />
    </ReactFlowProvider>,
  );
}

const RAMPS: NamedRamps = {
  viridis: ["#440154", "#21918C", "#FDE724"],
  magma: ["#000003", "#B63679", "#FBFCBF"],
};

afterEach(() => {
  cleanup(); // unmount before the store is reset
  vi.restoreAllMocks();
  store.set({ ...initialState });
});

test("each Params kind has its own canvas node", () => {
  const kinds = [PARAM_NUMBER, PARAM_TOGGLE, PARAM_VALUE_LIST, PARAM_COLOR, PARAM_COLORMAP].map(
    (c) => nodeKind(view(c)),
  );
  expect(kinds).toEqual(["number", "toggle", "value_list", "color", "colormap"]);
  expect(nodeKind(view("builtin/raster/read"))).toBe("component");
});

describe("Number", () => {
  test("double-click edits inline; Enter sends the number", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    show(NumberNode as NodeComponent, view(PARAM_NUMBER, { value: 0 }));
    expect(screen.getByTestId("number-value-n1").textContent).toBe("0");
    fireEvent.doubleClick(screen.getByTestId("node-n1"));
    const input = screen.getByTestId("number-input-n1");
    fireEvent.change(input, { target: { value: "2.5" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(patch).toHaveBeenCalledWith("n1", { value: 2.5 });
  });

  test("text that is not a number is refused with a message, not sent", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    const toast = vi.spyOn(store, "showToast").mockImplementation(() => {});
    show(NumberNode as NodeComponent, view(PARAM_NUMBER, { value: 3 }));
    fireEvent.doubleClick(screen.getByTestId("node-n1"));
    const input = screen.getByTestId("number-input-n1");
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(patch).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(strings.notANumber("abc"));
  });

  test("the whole-numbers box switches integer mode", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    show(NumberNode as NodeComponent, view(PARAM_NUMBER, { value: 3, integer: false }));
    fireEvent.doubleClick(screen.getByTestId("node-n1"));
    fireEvent.click(screen.getByTestId("number-integer-n1"));
    expect(patch).toHaveBeenCalledWith("n1", { integer: true });
  });
});

test("Number Slider: the window sends integer mode with the limits", () => {
  const ok = vi.fn();
  render(
    <SliderWindow min={0} max={10} step={0.5} value={2} integer={false} onOk={ok} onCancel={vi.fn()} />,
  );
  fireEvent.click(screen.getByTestId("slider-integer"));
  fireEvent.click(screen.getByTestId("slider-ok"));
  expect(ok).toHaveBeenCalledWith({ min: 0, max: 10, step: 0.5, value: 2, integer: true });
});

describe("Boolean Toggle", () => {
  test("a click flips the value", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    show(ToggleNode as NodeComponent, view(PARAM_TOGGLE, { value: false }));
    const toggle = screen.getByTestId("toggle-n1");
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(toggle.textContent).toBe(strings.toggleFalse);
    fireEvent.click(toggle);
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenCalledWith("n1", { value: true });
  });

  test("its port is a Boolean", () => {
    show(ToggleNode as NodeComponent, view(PARAM_TOGGLE, { value: true }));
    expect(screen.getByTestId("port-n1-out-value").getAttribute("data-type")).toBe("Boolean");
    expect(screen.getByTestId("toggle-n1").getAttribute("aria-checked")).toBe("true");
  });
});

describe("Value List", () => {
  const options = [
    { label: "One", value: 1 },
    { label: "Two", value: 2 },
  ];

  test("the dropdown chooses an option's value", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    show(ValueListNode as NodeComponent, view(PARAM_VALUE_LIST, { options, value: 1 }));
    const select = screen.getByTestId("value-list-n1") as HTMLSelectElement;
    expect([...select.options].map((o) => o.textContent)).toEqual(["One", "Two"]);
    expect(select.value).toBe("0");
    fireEvent.change(select, { target: { value: "1" } });
    expect(patch).toHaveBeenCalledWith("n1", { value: 2 });
  });

  test("its port follows the server's output type", () => {
    const text = view(PARAM_VALUE_LIST, {
      options: [{ label: "A", value: "a" }],
      value: "a",
      outputs: [{ name: "value", type: "Text", types: ["Text"], access: "item" }],
    });
    show(ValueListNode as NodeComponent, text);
    expect(screen.getByTestId("port-n1-out-value").getAttribute("data-type")).toBe("Text");
  });

  test("double-click opens the options window; OK sends the options", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    show(ValueListNode as NodeComponent, view(PARAM_VALUE_LIST, { options, value: 1 }));
    fireEvent.doubleClick(screen.getByTestId("node-n1"));
    fireEvent.change(screen.getByTestId("option-value-1"), { target: { value: "b" } });
    fireEvent.click(screen.getByTestId("option-add"));
    fireEvent.change(screen.getByTestId("option-value-2"), { target: { value: "3" } });
    fireEvent.click(screen.getByTestId("options-ok"));
    expect(patch).toHaveBeenCalledWith("n1", {
      options: [
        { label: "One", value: 1 },
        { label: "Two", value: "b" },
        { label: "3", value: 3 },
      ],
    });
  });

  test("an unedited text value stays text; a typed number becomes a number", () => {
    expect(
      rowsToOptions([
        { label: "a", text: "1", original: "1" },
        { label: "b", text: "2", original: "x" },
        { label: " ", text: "c", original: null },
      ]),
    ).toEqual([
      { label: "a", value: "1" },
      { label: "b", value: 2 },
      { label: "c", value: "c" },
    ]);
  });
});

describe("Color Swatch", () => {
  test("shows a swatch; double-click opens the picker and OK sends the hex", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    show(ColorNode as NodeComponent, view(PARAM_COLOR, { value: "#0B7A7C" }));
    expect(screen.getByTestId("swatch-n1").style.background).toBe("rgb(11, 122, 124)");
    fireEvent.doubleClick(screen.getByTestId("node-n1"));
    expect((screen.getByTestId("color-picker") as HTMLInputElement).value).toBe("#0b7a7c");
    fireEvent.change(screen.getByTestId("color-picker"), { target: { value: "#ff0000" } });
    expect((screen.getByTestId("color-hex") as HTMLInputElement).value).toBe("#FF0000");
    fireEvent.click(screen.getByTestId("color-ok"));
    expect(patch).toHaveBeenCalledWith("n1", { value: "#FF0000" });
  });

  test("the picker keeps the alpha of the hex", () => {
    expect(pickerValue("#0B7A7C80")).toBe("#0b7a7c");
    expect(pickerValue("11,122,124")).toBe("#000000");
    expect(withAlpha("#ff0000", "#0B7A7C80")).toBe("#FF000080");
  });
});

describe("Colormap", () => {
  const viridis = { kind: "continuous", name: "viridis", min: null, max: null, reverse: false };

  test("stops come from the named ramps, or the colormap's own; reverse flips them", () => {
    expect(stopsOf(viridis as never, null)).toBeNull();
    expect(stopsOf(viridis as never, RAMPS)).toEqual([
      [0, "#440154"],
      [0.5, "#21918C"],
      [1, "#FDE724"],
    ]);
    const custom = {
      kind: "continuous",
      name: null,
      stops: [
        [0, "#000000"],
        [0.25, "#FFFFFF"],
      ],
      min: null,
      max: null,
      reverse: true,
    };
    expect(stopsOf(custom as never, RAMPS)).toEqual([
      [0.75, "#FFFFFF"],
      [1, "#000000"],
    ]);
    expect(gradientCss([[0, "#000000"], [1, "#FFFFFF"]])).toBe(
      "linear-gradient(to right, #000000 0%, #FFFFFF 100%)",
    );
  });

  test("draws the gradient; double-click opens the Colormap editor (change 03)", () => {
    store.set({ ramps: RAMPS });
    const value = { ...viridis, min: 0, max: 5 };
    show(ColormapNode as NodeComponent, view(PARAM_COLORMAP, { value }));
    expect(screen.getByTestId("ramp-n1").style.background).toContain("linear-gradient");
    expect(screen.getByTestId("node-n1").textContent).toContain("viridis");
    fireEvent.doubleClick(screen.getByTestId("node-n1"));
    expect(store.getState().colormapNode).toBe("n1");
  });

  test("a classes colormap is drawn as chips", () => {
    store.set({ ramps: RAMPS });
    const classes = {
      kind: "classes",
      classes: [
        [1, "#FF0000", "a"],
        [2, "#00FF00", "b"],
      ],
      other: null,
    };
    show(ColormapNode as NodeComponent, view(PARAM_COLORMAP, { value: classes }));
    expect(screen.getByTestId("ramp-n1").querySelectorAll(".gk-class-chip")).toHaveLength(2);
    expect(screen.getByTestId("node-n1").textContent).toContain(strings.colormapClasses(2));
  });

  test("the store loads the ramps once", async () => {
    const colormaps = vi.fn(async () => RAMPS);
    const s = new Store({ colormaps } as unknown as Api);
    await Promise.all([s.loadRamps(), s.loadRamps()]);
    await s.loadRamps();
    expect(colormaps).toHaveBeenCalledTimes(1);
    expect(s.getState().ramps).toEqual(RAMPS);
  });
});

test("the Settings tab names a wired Params value", () => {
  const nodes = {
    t: view(PARAM_TOGGLE, { id: "t", title: "Boolean Toggle", value: true }),
    v: view(PARAM_VALUE_LIST, {
      id: "v",
      title: "Value List",
      options: [{ label: "One", value: 1 }],
      value: 1,
    }),
  };
  const g = {
    workflow: {
      nodes: [],
      wires: [
        { from: ["t", "value"], to: ["c", "flag"] },
        { from: ["v", "value"], to: ["c", "n"] },
      ],
      groups: [],
      view: {},
    },
    nodes,
  } as unknown as GraphView;
  expect(wiredLabel(g, "c", "flag")).toBe(strings.wiredParam("Boolean Toggle", "True"));
  expect(wiredLabel(g, "c", "n")).toBe(strings.wiredParam("Value List", "One"));
});

test("integer and options edits name what changed", () => {
  const g = {
    workflow: {
      nodes: [],
      wires: [{ from: ["n1", "value"], to: ["c", "size"] }],
      groups: [],
      view: {},
    },
    nodes: { n1: view(PARAM_NUMBER) },
  } as unknown as GraphView;
  store.set({ graph: g });
  expect(store.changeLabel("n1", { integer: true })).toBe("size");
  expect(store.changeLabel("n1", { options: [] })).toBe("size");
});
