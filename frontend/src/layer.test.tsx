// Change 03 step 3: the Map Layer node and its style window.

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type {
  ColormapJson,
  GraphView,
  MapLayerBuild,
  MapLayerInfo,
  MapLayerStyle,
  NamedRamps,
  NodeView,
  PortView,
  WireJson,
} from "./apiTypes";
import { LayerWindow } from "./components/layer/LayerWindow";
import { plainRamp, shownFields, wiredFrom } from "./components/layer/style";
import { nodeKind } from "./components/nodes/kinds";
import { initialState, store } from "./store";
import { strings } from "./strings";
import { paramEntry } from "./testFixtures";
import { PARAM_LAYER } from "./types";

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

const port = (name: string, type: PortView["type"]): PortView => ({
  name,
  type,
  types: [type],
  access: "item",
});

function build(kind: "raster" | "vector", extra: Partial<MapLayerBuild> = {}): MapLayerBuild {
  return {
    key: "abc.layer",
    value: {
      source: "123.raster",
      kind,
      name: "Read Raster.raster",
      colormap: null,
      color: null,
      opacity: 1,
      bands: null,
      field: null,
    },
    issues: {},
    wired: {},
    ...extra,
  };
}

function layerNode(style: MapLayerStyle, layer: MapLayerBuild | null): NodeView {
  return {
    id: "n3",
    component: PARAM_LAYER,
    title: "Map Layer",
    state: "done",
    position: [0, 0],
    display: "default",
    inputs: [
      { ...port("data", "Raster"), types: ["Raster", "Vector"] },
      port("colormap", "Colormap"),
      port("color", "Color"),
      port("opacity", "Number"),
      port("bands", "Text"),
      port("name", "Text"),
    ],
    outputs: [port("layer", "Layer")],
    style,
    layer,
  };
}

async function open(
  view: NodeView,
  opts: { wires?: WireJson[]; others?: NodeView[]; info?: Partial<MapLayerInfo> } = {},
) {
  const nodes: Record<string, NodeView> = { [view.id]: view };
  for (const n of opts.others ?? []) nodes[n.id] = n;
  const graph = { workflow: { nodes: [], wires: opts.wires ?? [], groups: [] }, nodes };
  const info: MapLayerInfo = {
    ...(view.layer ?? { key: null, value: null, issues: {}, wired: {} }),
    node: view.id,
    state: view.state ?? null,
    style: view.style ?? {},
    columns: null,
    bands: null,
    ...opts.info,
  };
  vi.spyOn(store.api, "layerInfo").mockResolvedValue(info);
  store.set({ graph: graph as unknown as GraphView, ramps: RAMPS, layerNode: view.id });
  await act(async () => void render(<LayerWindow />)); // and the layer info it fetches
}

const colormapNode: NodeView = {
  id: "n2",
  component: "param/colormap",
  title: "IMD classes",
  state: "out_of_date",
  position: [0, 0],
  display: "default",
  inputs: [],
  outputs: [port("value", "Colormap")],
};

describe("Map Layer", () => {
  test("is a Display entry with style inputs and a layer output, drawn as its own node", async () => {
    const entry = paramEntry("param/layer");
    expect(entry.category).toBe("Display");
    expect(entry.group).toBe("Style");
    expect(entry.inputs.map((p) => p.name)).toEqual([
      "data",
      "colormap",
      "color",
      "opacity",
      "bands",
      "name",
    ]);
    expect(entry.outputs.map((p) => p.name)).toEqual(["layer"]);
    expect(nodeKind(layerNode({}, null))).toBe("layer");
    expect(paramEntry("param/map").category).toBe("Display");
  });

  test("helpers: plain ramps, fields per kind, where a wired value comes from", async () => {
    const magma = { kind: "continuous" as const, name: "magma", min: null, max: null, reverse: false };
    expect(plainRamp(magma)).toBe("magma");
    expect(plainRamp({ ...magma, min: 0 })).toBeNull();
    expect(plainRamp({ kind: "classes", classes: [[1, "#FF0000", ""]], other: null })).toBeNull();
    expect(shownFields("raster", {})).toEqual(["colormap", "opacity", "bands", "name"]);
    expect(shownFields("vector", {})).toEqual(["colormap", "color", "opacity", "name", "field"]);
    expect(shownFields(null, {})).toEqual(["colormap", "color", "opacity", "bands", "name"]);
    expect(shownFields("raster", { color: "params" })).toContain("color");
    const wires: WireJson[] = [{ from: ["n2", "value"], to: ["n3", "colormap"] }];
    const graph = {
      workflow: { nodes: [], wires, groups: [] },
      nodes: { n2: colormapNode },
    } as unknown as GraphView;
    const b = build("raster", { wired: { colormap: "params" } });
    expect(wiredFrom(graph, b, "n3", "colormap")).toBe(strings.layerFrom("IMD classes"));
    expect(wiredFrom(graph, { ...b, wired: { colormap: "component" } }, "n3", "colormap")).toBe(
      strings.layerFromResult("IMD classes"),
    );
    expect(wiredFrom(graph, b, "n3", "opacity")).toBeNull();
  });
});

describe("Map Layer window", () => {
  test("each change is one style patch; name and bands send on Enter, empty resets", async () => {
    const patch = vi.spyOn(store, "tryPatchNode").mockResolvedValue(true);
    await open(layerNode({ bands: "1" }, build("raster")));
    fireEvent.change(screen.getByTestId("layer-colormap"), { target: { value: "magma" } });
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { colormap: "magma" } });
    fireEvent.change(screen.getByTestId("layer-colormap"), { target: { value: "" } });
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { colormap: null } });

    const name = screen.getByTestId("layer-name");
    expect(name.getAttribute("placeholder")).toBe("Read Raster.raster");
    fireEvent.change(name, { target: { value: " IMD " } });
    fireEvent.keyDown(name, { key: "Enter" });
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { name: "IMD" } });

    const bands = screen.getByTestId("layer-bands");
    expect(bands).toHaveProperty("value", "1");
    fireEvent.change(bands, { target: { value: "" } });
    fireEvent.blur(bands);
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { bands: null } });
    expect(patch).toHaveBeenCalledTimes(4);
    // a raster has no colour or field
    expect(screen.queryByTestId("layer-color-picker")).toBeNull();
    expect(screen.queryByTestId("layer-field")).toBeNull();
  });

  test("an opacity drag and a colour picker each send one patch once they rest", async () => {
    vi.useFakeTimers();
    const patch = vi.spyOn(store, "tryPatchNode").mockResolvedValue(true);
    await open(layerNode({}, build("vector")));
    const opacity = screen.getByTestId("layer-opacity");
    for (const v of ["0.9", "0.7", "0.55"]) fireEvent.change(opacity, { target: { value: v } });
    expect(screen.getByTestId("layer-opacity-value").textContent).toBe("0.55");
    expect(patch).not.toHaveBeenCalled();
    fireEvent.pointerUp(opacity);
    expect(patch).toHaveBeenCalledTimes(1);
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { opacity: 0.55 } });

    const picker = screen.getByTestId("layer-color-picker");
    fireEvent.change(picker, { target: { value: "#ff0000" } });
    fireEvent.change(picker, { target: { value: "#00ff00" } });
    expect(patch).toHaveBeenCalledTimes(1);
    act(() => void vi.advanceTimersByTime(1000));
    expect(patch).toHaveBeenCalledTimes(2);
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { color: "#00FF00" } });
  });

  test("a vector's field dropdown lists the data's columns", async () => {
    const patch = vi.spyOn(store, "tryPatchNode").mockResolvedValue(true);
    await open(layerNode({}, build("vector")), { info: { columns: ["class", "area"] } });
    const field = screen.getByTestId("layer-field") as HTMLSelectElement;
    expect(field.disabled).toBe(false);
    expect([...field.options].map((o) => o.value)).toEqual(["", "class", "area"]);
    fireEvent.change(field, { target: { value: "class" } });
    expect(patch).toHaveBeenLastCalledWith("n3", { style: { field: "class" } });
  });

  test("before the data has a result the field dropdown waits", async () => {
    await open(layerNode({}, build("vector")));
    expect((screen.getByTestId("layer-field") as HTMLSelectElement).disabled).toBe(true);
    expect(screen.getByTestId("layer-window").textContent).toContain(strings.layerFieldLater);
  });

  test("a wired input is read-only with where it comes from; issues are shown", async () => {
    const cm: ColormapJson = { kind: "classes", classes: [[1, "#FF0000", "Built"]], other: null };
    const b = build("raster", {
      wired: { colormap: "params" },
      issues: { opacity: "Score has no result yet; run it" },
    });
    b.value = { ...b.value!, colormap: cm };
    const wires: WireJson[] = [
      { from: ["n2", "value"], to: ["n3", "colormap"] },
      { from: ["n9", "score"], to: ["n3", "opacity"] },
    ];
    await open(layerNode({}, b), { wires, others: [colormapNode] });
    const wired = screen.getByTestId("layer-colormap-wired");
    expect(wired.textContent).toContain(strings.colormapClasses(1));
    expect(wired.textContent).toContain(strings.layerFrom("IMD classes"));
    expect(screen.queryByTestId("layer-colormap")).toBeNull();
    // the opacity input counts as unwired: editable, with the reason
    expect(screen.getByTestId("layer-opacity")).toBeTruthy();
    expect(screen.getByTestId("layer-issue-opacity").textContent).toBe(
      strings.layerIssue(strings.opacity, "Score has no result yet; run it"),
    );
  });

  test("without data the window says so; Reset all sends style null", async () => {
    const patch = vi.spyOn(store, "tryPatchNode").mockResolvedValue(true);
    const reset = vi.spyOn(store, "patchNode").mockResolvedValue();
    await open(
      layerNode(
        { opacity: 0.5 },
        { key: null, value: null, issues: { data: "wire a Raster or Vector into data" }, wired: {} },
      ),
    );
    expect(screen.getByTestId("layer-issue-data").textContent).toBe(
      strings.layerIssue(strings.layerData, "wire a Raster or Vector into data"),
    );
    fireEvent.click(screen.getByTestId("layer-reset-all"));
    expect(reset).toHaveBeenCalledWith("n3", { style: null });
    expect(patch).not.toHaveBeenCalled();
  });

  test("a refused value goes back to the saved one", async () => {
    vi.spyOn(store, "tryPatchNode").mockResolvedValue(false);
    await open(layerNode({ bands: "1" }, build("raster")));
    const bands = screen.getByTestId("layer-bands");
    fireEvent.change(bands, { target: { value: "nine" } });
    await act(async () => void fireEvent.keyDown(bands, { key: "Enter" }));
    expect(screen.getByTestId("layer-bands")).toHaveProperty("value", "1");
  });
});
