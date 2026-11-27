import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { GraphView, MapLayer, MapView, NodeView } from "../../apiTypes";
import { paramEntry } from "../../testFixtures";
import { initialState, store } from "../../store";
import { nodeKind } from "../nodes/kinds";
import {
  effectiveStyle,
  formatValue,
  legendFor,
  renderLayers,
  statsFor,
  tileUrl,
  unionBounds,
} from "./layers";
import { MapWindow } from "./MapWindow";

// MapLibre needs WebGL, which jsdom lacks: a stub records what the canvas would draw.
const canvas = vi.hoisted(() => ({ props: null as null | Record<string, unknown> }));
vi.mock("./MapCanvas", () => ({
  MapCanvas: (p: Record<string, unknown>) => {
    canvas.props = p;
    return <div data-testid="map-canvas" />;
  },
}));

const KEY = "a".repeat(64);

const pred: MapLayer = {
  id: "n17.map",
  title: "Predict Raster › map",
  source: ["n17", "map"],
  key: `${KEY}.map`,
  status: "ready",
  message: null,
  type: "Raster",
  raster: {
    bands: ["IMD"],
    dtype: "float32",
    width: 200,
    height: 200,
    nodata: null,
    crs: "EPSG:32632",
    bounds: [9.1, 45.4, 9.2, 45.5],
    stats: { min: 2, max: 90, classes: null },
    default_style: { bands: [1], colormap: "viridis", min: 2, max: 90, opacity: 1, visible: true },
  },
};

const predictors: MapLayer = {
  ...pred,
  id: "n12.raster",
  title: "Read Raster › raster",
  key: `${KEY}.raster`,
  raster: {
    ...pred.raster!,
    bands: ["A00", "A01", "A02", "A03"],
    stats: { min: -1, max: 1, classes: null },
    default_style: { bands: [1], colormap: "viridis", min: -1, max: 1 },
  },
};

const classes: MapLayer = {
  ...pred,
  id: "n4.classes",
  title: "Reclassify › classes",
  key: `${KEY}.classes`,
  raster: {
    ...pred.raster!,
    stats: { min: 1, max: 7, classes: [{ value: 1, color: "#ff7f0e" }, { value: 2, color: "#2ca02c" }] },
    default_style: { bands: [1], colormap: "categorical", min: 1, max: 7 },
  },
};

const points: MapLayer = {
  id: "n10.test",
  title: "Split Points › test",
  source: ["n10", "test"],
  key: `${KEY}.test`,
  status: "ready",
  message: null,
  type: "Vector",
  vector: {
    features: 42,
    shown: 42,
    geometry: ["Point"],
    columns: ["IMD"],
    crs: "EPSG:32632",
    bounds: [9.12, 45.42, 9.18, 45.48],
    default_style: { color: "#d62728", opacity: 1, visible: true },
  },
};

const model: MapLayer = {
  id: "n16.model",
  title: "Random Forest › model",
  source: ["n16", "model"],
  key: `${KEY}.model`,
  status: "unsupported",
  message: "a Model cannot be shown on a map",
  type: "Model",
};

const COLORMAPS = { viridis: ["#440154", "#21918c", "#fde725"], magma: ["#000004", "#fcfdbf"] };

function mapView(layers: MapLayer[]): MapView {
  return { basemap: "light", layers, basemaps: ["light", "none"], colormaps: COLORMAPS, max_features: 50000 };
}

const viewer: NodeView = {
  id: "n30",
  component: "param/map",
  title: "Map Viewer",
  state: "done",
  position: [0, 0],
  display: "default",
  inputs: [{ name: "layers", type: "Any", access: "list" }],
  outputs: [],
  map: {},
};

function graphWith(node: NodeView): GraphView {
  return {
    workflow: { nodes: [], wires: [], groups: [], view: {} },
    nodes: { [node.id]: node },
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

async function open(layers: MapLayer[], node: NodeView = viewer) {
  vi.spyOn(store.api, "mapView").mockResolvedValue(mapView(layers));
  const stats = vi
    .spyOn(store.api, "rasterStats")
    .mockResolvedValue({ min: 10, max: 20, classes: null });
  const patch = vi.spyOn(store, "patchNode").mockResolvedValue();
  store.set({ graph: graphWith(node), mapNode: node.id });
  await act(async () => {
    render(<MapWindow />);
  });
  return { patch, stats };
}

afterEach(() => {
  vi.restoreAllMocks();
  canvas.props = null;
  act(() => store.set({ ...initialState }));
});

describe("map logic", () => {
  test("saved styles override the server's defaults", () => {
    const s = effectiveStyle(pred, { colormap: "magma", min: null });
    expect(s).toMatchObject({ bands: [1], colormap: "magma", min: null, max: 90, opacity: 1 });
    expect(effectiveStyle(points).color).toBe("#d62728");
  });

  test("tile URLs carry bands, colormap and only the min/max that are set", () => {
    const s = effectiveStyle(pred, { min: null });
    expect(tileUrl(pred.key!, s)).toBe(
      `/tiles/${KEY}.map/{z}/{x}/{y}.png?bands=1&colormap=viridis&max=90`,
    );
    expect(tileUrl(pred.key!, effectiveStyle(pred, { bands: [3, 2, 1] }))).toContain("bands=3%2C2%2C1");
  });

  test("legends: ramp, classes, RGB", () => {
    const ramp = legendFor(pred, effectiveStyle(pred), pred.raster!.stats, COLORMAPS);
    expect(ramp).toEqual({ kind: "ramp", colours: COLORMAPS.viridis, min: 2, max: 90 });
    const cls = legendFor(classes, effectiveStyle(classes), classes.raster!.stats, COLORMAPS);
    expect(cls).toMatchObject({ kind: "classes" });
    const style = effectiveStyle(predictors, { bands: [3, 2, 1], min: 0, max: 1 });
    expect(legendFor(predictors, style, null, COLORMAPS)).toEqual({
      kind: "rgb",
      bands: ["A02", "A01", "A00"],
      min: 0,
      max: 1,
    });
  });

  test("statistics come from the layer for its default bands, else from what was fetched", () => {
    expect(statsFor(pred, effectiveStyle(pred), {})).toBe(pred.raster!.stats);
    const other = effectiveStyle(predictors, { bands: [3] });
    expect(statsFor(predictors, other, {})).toBeNull();
    const fetched = { [`${KEY}.raster|3`]: { min: 5, max: 6, classes: null } };
    expect(statsFor(predictors, other, fetched)?.min).toBe(5);
  });

  test("only ready layers are drawn and framed; classes use nearest pixels", () => {
    const drawn = renderLayers([pred, model, classes, points], {});
    expect(drawn.map((l) => l.id)).toEqual(["n10.test", "n17.map", "n4.classes"]); // vectors on top
    expect(drawn.find((l) => l.id === "n4.classes")).toMatchObject({ kind: "raster", nearest: true });
    expect(drawn.find((l) => l.id === "n10.test")).toMatchObject({
      kind: "vector",
      url: `/api/vector/${KEY}.test.geojson`,
    });
    expect(unionBounds([pred, points, model])).toEqual([9.1, 45.4, 9.2, 45.5]);
    expect(formatValue(28.95213890075)).toBe("28.952");
    expect(formatValue(null)).toBe("–");
  });

  test("Map Viewer is a Params entry with a list input, drawn as its own node", () => {
    const entry = paramEntry("param/map");
    expect(entry.inputs).toEqual([{ name: "layers", type: "Any", types: ["Any"], access: "list" }]);
    expect(entry.outputs).toEqual([]);
    expect(nodeKind(viewer)).toBe("map");
  });
});

describe("map window", () => {
  test("lists every wired layer, with a reason when it cannot be drawn", async () => {
    await open([pred, points, model]);
    expect(screen.getByTestId("layer-n17.map").dataset.status).toBe("ready");
    expect(screen.getByTestId("layer-n16.model").textContent).toContain("cannot be shown");
    expect(screen.getByTestId("layer-n10.test").textContent).toContain("42 features");
    expect(screen.getByTestId("legend-n17.map").dataset.kind).toBe("ramp");
    const drawn = canvas.props?.layers as { id: string }[];
    expect(drawn.map((l) => l.id)).toEqual(["n10.test", "n17.map"]);
    expect(canvas.props?.basemap).toBe("light");
  });

  test("style changes are saved on the node (one patch each)", async () => {
    const { patch } = await open([pred, points]);
    fireEvent.change(screen.getByTestId("layer-colormap-n17.map"), { target: { value: "magma" } });
    expect(patch).toHaveBeenLastCalledWith("n30", {
      map: { styles: { "n17.map": { colormap: "magma" } } },
    });
    const min = screen.getByTestId("layer-min-n17.map") as HTMLInputElement;
    fireEvent.blur(min); // untouched: no change sent
    expect(patch).toHaveBeenCalledTimes(1);
    fireEvent.change(min, { target: { value: "5" } });
    fireEvent.keyDown(min, { key: "Enter" });
    expect(patch).toHaveBeenLastCalledWith("n30", { map: { styles: { "n17.map": { min: 5 } } } });
    fireEvent.click(screen.getByTestId("layer-visible-n10.test"));
    expect(patch).toHaveBeenLastCalledWith("n30", {
      map: { styles: { "n10.test": { visible: false } } },
    });
    fireEvent.click(screen.getByTestId("layer-colour-n10.test-1f77b4"));
    expect(patch).toHaveBeenLastCalledWith("n30", {
      map: { styles: { "n10.test": { color: "#1f77b4" } } },
    });
    fireEvent.change(screen.getByTestId("map-basemap"), { target: { value: "none" } });
    expect(patch).toHaveBeenLastCalledWith("n30", { map: { basemap: "none" } });
  });

  test("a saved style is drawn, and Reset removes it", async () => {
    const node = { ...viewer, map: { basemap: "none" as const, styles: { "n17.map": { opacity: 0.4 } } } };
    const { patch } = await open([pred], node);
    expect(canvas.props?.basemap).toBe("none");
    expect((canvas.props?.layers as { opacity: number }[])[0].opacity).toBe(0.4);
    fireEvent.click(screen.getByTestId("layer-reset-n17.map"));
    expect(patch).toHaveBeenLastCalledWith("n30", { map: { styles: { "n17.map": null } } });
  });

  test("other bands: the stretch is reset and fetched for the new bands", async () => {
    const node = { ...viewer, map: { styles: { "n12.raster": { bands: [3], min: null, max: null } } } };
    const { patch, stats } = await open([predictors], node);
    expect(stats).toHaveBeenCalledWith(`${KEY}.raster`, [3]);
    await act(async () => undefined);
    expect(screen.getByTestId("legend-n12.raster").textContent).toContain("10");
    fireEvent.click(screen.getByTestId("layer-rgb-n12.raster"));
    expect(patch).toHaveBeenLastCalledWith("n30", {
      map: { styles: { "n12.raster": { bands: [3, 2, 1], min: null, max: null } } },
    });
  });

  test("a click shows every raster's values and the vector features hit", async () => {
    await open([pred, points]);
    const inspect = vi.spyOn(store.api, "mapInspect").mockResolvedValue({
      lon: 9.15,
      lat: 45.45,
      layers: [
        { id: "n17.map", title: "Predict Raster › map", outside: false, values: [{ band: "IMD", value: 41.25 }] },
      ],
    });
    const onInspect = canvas.props?.onInspect as (
      lon: number,
      lat: number,
      hits: { layer: string; properties: Record<string, unknown> }[],
    ) => void;
    await act(async () => onInspect(9.15, 45.45, [{ layer: "n10.test", properties: { IMD: 33 } }]));
    expect(inspect).toHaveBeenCalledWith("n30", 9.15, 45.45);
    expect(screen.getByTestId("inspect-value-n17.map-IMD").textContent).toBe("41.25");
    expect(screen.getByTestId("inspect-n10.test").textContent).toContain("Split Points › test");
    expect(screen.getByTestId("inspect-n10.test").textContent).toContain("33");
  });
});
