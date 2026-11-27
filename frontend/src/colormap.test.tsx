// Change 03 step 2: the Colormap editor's helpers and window.

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ColormapJson, GraphView, NamedRamps, NodeView } from "./apiTypes";
import { ColormapWindow } from "./components/colormap/ColormapWindow";
import {
  addClass,
  addStop,
  colourAt,
  fillFromRamp,
  moveClass,
  moveStop,
  normHex,
  parseClassTable,
  problem,
  removeClass,
  removeStop,
  sampleRamp,
  setStopColour,
  type ClassRow,
  type Stop,
} from "./components/colormap/edit";
import { initialState, store } from "./store";
import { strings } from "./strings";
import { PARAM_COLORMAP } from "./types";

const RAMPS: NamedRamps = {
  viridis: ["#440154", "#21918C", "#FDE724"],
  magma: ["#000000", "#808080", "#FFFFFF"],
};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  store.set({ ...initialState });
});

describe("paste a class table", () => {
  test("comma or tab separated lines become classes", () => {
    expect(parseClassTable("1, #FF0000, Built\n2, #00FF00, Green")).toEqual([
      [1, "#FF0000", "Built"],
      [2, "#00FF00", "Green"],
    ]);
    expect(parseClassTable("1\t#ff000080\tBuilt, dense\r\n\r\n2.5\t00ff00\t")).toEqual([
      [1, "#FF000080", "Built, dense"],
      [2.5, "#00FF00", ""],
    ]);
  });

  test("labels may hold commas; a header line is skipped; the label may be left out", () => {
    expect(parseClassTable("value,colour,label\n3,#0000FF,a, b\n4,#000000")).toEqual([
      [3, "#0000FF", "a, b"],
      [4, "#000000", ""],
    ]);
  });

  test("text that is not a class table gives null", () => {
    expect(parseClassTable("Built")).toBeNull();
    expect(parseClassTable("")).toBeNull();
    expect(parseClassTable("1, #FF0000, a\nfoo, #00FF00, b")).toBeNull();
    expect(parseClassTable("1, red, a")).toBeNull();
  });
});

describe("fill from ramp", () => {
  const classes: ClassRow[] = [
    [1, "#123456", "a"],
    [2, "#123456", "b"],
    [3, "#123456", "c"],
  ];

  test("the listed values in order get colours along the ramp; labels stay", () => {
    expect(fillFromRamp(classes, RAMPS.magma)).toEqual([
      [1, "#000000", "a"],
      [2, "#808080", "b"],
      [3, "#FFFFFF", "c"],
    ]);
    expect(fillFromRamp(classes.slice(0, 1), RAMPS.magma)).toEqual([[1, "#000000", "a"]]);
  });

  test("colours between the ramp's own are interpolated", () => {
    expect(sampleRamp(["#000000", "#FFFFFF"], 3)).toEqual(["#000000", "#808080", "#FFFFFF"]);
    expect(colourAt([[0, "#00000000"], [1, "#FF0000FF"]], 0.5)).toBe("#80000080");
  });
});

describe("stops", () => {
  const stops: Stop[] = [
    [0, "#000000"],
    [1, "#FFFFFF"],
  ];

  test("a click adds a stop with the ramp's colour there", () => {
    expect(addStop(stops, 0.25)).toEqual({
      stops: [
        [0, "#000000"],
        [0.25, "#404040"],
        [1, "#FFFFFF"],
      ],
      index: 1,
    });
    expect(addStop(stops, 1.4).stops[2][0]).toBe(1);
  });

  test("a dragged stop keeps the stops in order and says where it went", () => {
    const three: Stop[] = [
      [0, "#000000"],
      [0.5, "#FF0000"],
      [1, "#FFFFFF"],
    ];
    expect(moveStop(three, 0, 0.75)).toEqual({
      stops: [
        [0.5, "#FF0000"],
        [0.75, "#000000"],
        [1, "#FFFFFF"],
      ],
      index: 1,
    });
    expect(moveStop(three, 1, 0.12345).stops[1][0]).toBe(0.123);
  });

  test("remove keeps at least two; a colour change touches one stop", () => {
    expect(removeStop(stops, 0)).toBe(stops);
    expect(removeStop([...stops, [1, "#FF0000"]], 2)).toEqual(stops);
    expect(setStopColour(stops, 1, "#FF0000")).toEqual([
      [0, "#000000"],
      [1, "#FF0000"],
    ]);
  });
});

describe("classes", () => {
  test("add, remove, reorder", () => {
    const one: ClassRow[] = [[3, "#FF0000", "a"]];
    const two = addClass(one);
    expect(two[1][0]).toBe(4);
    expect(two[1][2]).toBe("");
    expect(addClass([])[0][0]).toBe(1);
    expect(removeClass(one, 0)).toBe(one);
    expect(removeClass(two, 0)).toEqual([two[1]]);
    expect(moveClass(two, 1, -1)).toEqual([two[1], two[0]]);
    expect(moveClass(two, 1, 1)).toBe(two);
  });

  test("what the server would refuse is caught first", () => {
    const twice: ColormapJson = {
      kind: "classes",
      classes: [
        [1, "#FF0000", ""],
        [1, "#00FF00", ""],
      ],
      other: null,
    };
    expect(problem(twice)).toBe(strings.cmValueTwice);
    const range: ColormapJson = { kind: "continuous", name: "viridis", min: 2, max: 1, reverse: false };
    expect(problem(range)).toBe(strings.cmMinBelowMax);
    expect(normHex("ff00aa")).toBe("#FF00AA");
    expect(normHex("#ff00a")).toBeNull();
  });
});

// ── the window ──

function open(value: ColormapJson) {
  const node: NodeView = {
    id: "n1",
    component: PARAM_COLORMAP,
    title: "Colormap",
    state: "never_run",
    position: [0, 0],
    display: "default",
    inputs: [],
    outputs: [{ name: "value", type: "Colormap", types: ["Colormap"], access: "item" }],
    value,
  };
  const graph = { workflow: { nodes: [], wires: [], groups: [] }, nodes: { n1: node } };
  store.set({ graph: graph as unknown as GraphView, ramps: RAMPS, colormapNode: "n1" });
  return render(<ColormapWindow />);
}

const VIRIDIS: ColormapJson = { kind: "continuous", name: "viridis", min: null, max: null, reverse: false };

describe("Colormap window", () => {
  test("each edit is one patch of the whole value", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    open(VIRIDIS);
    fireEvent.change(screen.getByTestId("cm-ramp"), { target: { value: "magma" } });
    expect(patch).toHaveBeenLastCalledWith("n1", {
      value: { kind: "continuous", name: "magma", min: null, max: null, reverse: false },
    });
    fireEvent.click(screen.getByTestId("cm-min-auto"));
    const min = screen.getByTestId("cm-min");
    fireEvent.change(min, { target: { value: "0.5" } });
    fireEvent.keyDown(min, { key: "Enter" });
    expect(patch).toHaveBeenLastCalledWith("n1", {
      value: { kind: "continuous", name: "magma", min: 0.5, max: null, reverse: false },
    });
    expect(patch).toHaveBeenCalledTimes(3);
  });

  test("Custom starts from the ramp's stops; the picker sends once it rests", () => {
    vi.useFakeTimers();
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    open(VIRIDIS);
    fireEvent.change(screen.getByTestId("cm-ramp"), { target: { value: "__custom__" } });
    const custom = {
      kind: "continuous",
      name: null,
      stops: [
        [0, "#440154"],
        [0.5, "#21918C"],
        [1, "#FDE724"],
      ],
      min: null,
      max: null,
      reverse: false,
    };
    expect(patch).toHaveBeenLastCalledWith("n1", { value: custom });
    expect(screen.getAllByTestId(/^cm-stop-\d$/)).toHaveLength(3);
    const picker = screen.getByTestId("cm-stop-picker");
    fireEvent.change(picker, { target: { value: "#ff0000" } });
    fireEvent.change(picker, { target: { value: "#00ff00" } });
    expect(patch).toHaveBeenCalledTimes(1);
    act(() => void vi.advanceTimersByTime(1000));
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenLastCalledWith("n1", {
      value: { ...custom, stops: [[0, "#00FF00"], ...custom.stops.slice(1)] },
    });
  });

  test("Classes: a pasted table replaces the classes", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    open(VIRIDIS);
    fireEvent.click(screen.getByTestId("cm-kind-classes"));
    expect(patch).toHaveBeenLastCalledWith("n1", {
      value: { kind: "classes", classes: [[1, "#440154", ""]], other: null },
    });
    fireEvent.paste(screen.getByTestId("cm-classes"), {
      clipboardData: { getData: () => "1, #FF0000, Built\n2, #00FF00, Green" },
    });
    expect(patch).toHaveBeenLastCalledWith("n1", {
      value: {
        kind: "classes",
        classes: [
          [1, "#FF0000", "Built"],
          [2, "#00FF00", "Green"],
        ],
        other: null,
      },
    });
    expect(screen.getAllByTestId(/^cm-class-\d$/)).toHaveLength(2);
  });

  test("a duplicate class value is refused before it is sent", () => {
    const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
    const toast = vi.spyOn(store, "showToast");
    open({
      kind: "classes",
      classes: [
        [1, "#FF0000", ""],
        [2, "#00FF00", ""],
      ],
      other: null,
    });
    const value = screen.getByTestId("cm-class-value-1");
    fireEvent.change(value, { target: { value: "1" } });
    fireEvent.blur(value);
    expect(patch).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledWith(strings.cmValueTwice);
  });
});
