import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ColormapJson, GraphView, MapLayer, MapView, NodeView } from "../../apiTypes";
import { paramEntry } from "../../testFixtures";
import { initialState, store } from "../../store";
import { nodeKind } from "../nodes/kinds";
import {
  BASEMAP_PAINT,
  effectiveStyle,
  fieldColour,
  formatValue,
  gradientStops,
  legendFor,
  renderLayers,
  statsFor,
  tileUrl,
  unionBounds,
} from "./layers";
import { MapWindow } from "./MapWindow";
import { cssColour, TRANSPARENT } from "../../palettes";

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
  return { basemap: "auto", layers, basemaps: ["auto", "light", "dark", "none"], colormaps: COLORMAPS, max_features: 50000 };
}

const viewer: NodeView = {
  id: "n30",
  component: "param/map",
  title: "Map Viewer",
  state: "done",
  position: [0, 0],
  display: "default",
  inputs: [{ name: "layers", type: "Raster", types: ["Raster", "Vector", "Layer"], access: "list" }],
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
  document.documentElement.removeAttribute("data-theme");
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

  test("a Colormap style goes to the tiles as compact JSON in cmap", () => {
    const cm: ColormapJson = { kind: "classes", classes: [[1, "#FF0000", "Built"]], other: null };
    const url = tileUrl(classes.key!, effectiveStyle(classes, { colormap: cm }));
    const q = new URLSearchParams(url.split("?")[1]);
    expect(q.get("cmap")).toBe('{"kind":"classes","classes":[[1,"#FF0000","Built"]],"other":null}');
    expect(q.has("colormap")).toBe(false);
    expect(JSON.parse(q.get("cmap")!)).toEqual(cm);
    // a classes Colormap draws nearest pixels; a continuous one does not
    const styles = { "n4.classes": { colormap: cm }, "n17.map": { colormap: cm } };
    const ramp: ColormapJson = { kind: "continuous", name: "magma", min: null, max: null, reverse: false };
    expect(renderLayers([classes, pred], styles).map((l) => l.kind === "raster" && l.nearest)).toEqual([
      true,
      true,
    ]);
    expect(renderLayers([pred], { "n17.map": { colormap: ramp } })[0]).toMatchObject({ nearest: false });
  });

  test("legends of a classes Colormap: labels (value when empty) and the other colour", () => {
    const cm: ColormapJson = {
      kind: "classes",
      classes: [
        [1, "#FF0000", "Built"],
        [2.5, "#0000FF80", ""],
      ],
      other: "#CCCCCC",
    };
    const style = effectiveStyle(classes, { colormap: cm });
    expect(legendFor(classes, style, classes.raster!.stats, COLORMAPS)).toEqual({
      kind: "classes",
      classes: [
        { value: 1, color: "#FF0000", label: "Built" },
        { value: 2.5, color: "#0000FF80", label: "2.5" },
      ],
      other: "#CCCCCC",
    });
    const transparent = effectiveStyle(classes, { colormap: { ...cm, other: null } });
    expect(legendFor(classes, transparent, null, COLORMAPS)).not.toHaveProperty("other");
  });

  test("legends of a continuous Colormap: custom stops, reverse, its own min/max", () => {
    const cm: ColormapJson = {
      kind: "continuous",
      name: null,
      stops: [
        [0, "#000000"],
        [0.25, "#FF0000"],
        [1, "#FFFFFF"],
      ],
      min: 10,
      max: null,
      reverse: false,
    };
    const legend = legendFor(pred, effectiveStyle(pred, { colormap: cm }), pred.raster!.stats, COLORMAPS);
    expect(legend).toEqual({
      kind: "ramp",
      colours: ["#000000", "#FF0000", "#FFFFFF"],
      positions: [0, 0.25, 1],
      min: 10, // the Colormap's, not the style's 2
      max: 90, // auto: the stretch
    });
    expect(gradientStops(legend as Extract<typeof legend, { kind: "ramp" }>)).toBe(
      "#000000 0%, #FF0000 25%, #FFFFFF 100%",
    );
    const back = effectiveStyle(pred, { colormap: { ...cm, reverse: true } });
    const reversed = legendFor(pred, back, null, COLORMAPS);
    expect(reversed).toMatchObject({ colours: ["#FFFFFF", "#FF0000", "#000000"], positions: [0, 0.75, 1] });
    // a named ramp: the server's colours (reversed when asked), evenly spaced
    const named: ColormapJson = { kind: "continuous", name: "viridis", min: null, max: null, reverse: true };
    expect(legendFor(pred, effectiveStyle(pred, { colormap: named }), null, COLORMAPS)).toEqual({
      kind: "ramp",
      colours: [...COLORMAPS.viridis].reverse(),
      min: 2,
      max: 90,
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
    expect(entry.inputs).toEqual([
      { name: "layers", type: "Raster", types: ["Raster", "Vector", "Layer"], access: "list" },
    ]);
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

  test("auto follows the theme: dark paint in dark, light paint in light, live", async () => {
    const paint = () => BASEMAP_PAINT[canvas.props?.basemap as "light" | "dark"];
    document.documentElement.setAttribute("data-theme", "dark");
    await open([pred]);
    expect((screen.getByTestId("map-basemap") as HTMLSelectElement).value).toBe("auto");
    expect(canvas.props?.basemap).toBe("dark");
    expect(paint()).toMatchObject({
      "raster-brightness-min": 1,
      "raster-brightness-max": 0,
      "raster-hue-rotate": 180,
    });
    await act(async () => document.documentElement.setAttribute("data-theme", "light"));
    expect(canvas.props?.basemap).toBe("light");
    expect(paint()).toMatchObject({ "raster-saturation": -0.85, "raster-brightness-min": 0.25 });
  });

  test("a saved light or dark basemap does not follow the theme", async () => {
    document.documentElement.setAttribute("data-theme", "dark");
    await open([pred], { ...viewer, map: { basemap: "light" } });
    expect(canvas.props?.basemap).toBe("light");
    await act(async () => document.documentElement.setAttribute("data-theme", "light"));
    expect(canvas.props?.basemap).toBe("light");
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

// ── change 03, step 4: layers from Map Layers, colour by field, legends ──

const CLASSES_CM: ColormapJson = {
  kind: "classes",
  classes: [
    [1, "#FF0000", "Low"],
    [2, "#0000FF80", ""],
  ],
  other: null,
};

/** The classes raster drawn through a Map Layer (n40) with a classes Colormap and opacity. */
const fromLayer: MapLayer = {
  ...classes,
  id: "n40.layer",
  title: "IMD classes",
  source: ["n40", "layer"],
  from_layer: "n40",
  locked: ["colormap", "opacity"],
  style: { ...classes.raster!.default_style, colormap: CLASSES_CM, opacity: 0.5, visible: true },
};

/** Points coloured by `IMD` through a Map Layer (n41), its range from the GeoJSON. */
const byField: MapLayer = {
  ...points,
  id: "n41.layer",
  title: "Points by IMD",
  source: ["n41", "layer"],
  from_layer: "n41",
  locked: ["colormap", "field"],
  vector: { ...points.vector!, field: { name: "IMD", numeric: true, min: 10, max: 30 } },
  style: {
    color: "#d62728",
    opacity: 1,
    visible: true,
    field: "IMD",
    colormap: { kind: "continuous", name: "viridis", min: null, max: null, reverse: false },
  },
};

describe("map layers from Map Layers (change 03)", () => {
  test("locked fields win over saved styles; show/hide stays the viewer's", () => {
    const s = effectiveStyle(fromLayer, { colormap: "magma", opacity: 0.9, visible: false });
    expect(s.colormap).toEqual(CLASSES_CM);
    expect(s.opacity).toBe(0.5);
    expect(s.visible).toBe(false);
  });

  test("colour by classes: match on integers, case otherwise, other or transparent", () => {
    expect(fieldColour(CLASSES_CM, "cls", null, COLORMAPS)).toEqual([
      "match",
      ["get", "cls"],
      1,
      "#FF0000",
      2,
      "rgba(0, 0, 255, 0.502)",
      TRANSPARENT,
    ]);
    const half: ColormapJson = { kind: "classes", classes: [[0.5, "#00FF00", "half"]], other: "#808080" };
    expect(fieldColour(half, "v", null, COLORMAPS)).toEqual([
      "case",
      ["==", ["get", "v"], 0.5],
      "#00FF00",
      "#808080",
    ]);
  });

  test("colour by a continuous Colormap: interpolate over the field range, or its own min/max", () => {
    const viridis: ColormapJson = { kind: "continuous", name: "viridis", min: null, max: null, reverse: false };
    const get = ["get", "IMD"];
    expect(fieldColour(viridis, "IMD", [10, 30], COLORMAPS)).toEqual([
      "case",
      ["==", ["typeof", get], "number"],
      ["interpolate", ["linear"], get, 10, "#440154", 20, "#21918c", 30, "#fde725"],
      TRANSPARENT,
    ]);
    const fixed: ColormapJson = {
      kind: "continuous",
      name: null,
      stops: [
        [0, "#000000"],
        [0.25, "#FF000080"],
        [1, "#FFFFFF"],
      ],
      min: 0,
      max: 100,
      reverse: false,
    };
    const expr = fieldColour(fixed, "IMD", [10, 30], COLORMAPS) as unknown[];
    expect(expr[2]).toEqual([
      "interpolate",
      ["linear"],
      get,
      0,
      "#000000",
      25,
      "rgba(255, 0, 0, 0.502)",
      100,
      "#FFFFFF",
    ]);
    // no range yet: transparent; one value: one colour
    expect(fieldColour(viridis, "IMD", null, COLORMAPS)).toBe(TRANSPARENT);
    expect(fieldColour(viridis, "IMD", [5, 5], COLORMAPS)).toBe("#fde725");
  });

  test("a vector by field is drawn with the expression; one without uses its colour", () => {
    const drawn = renderLayers([byField, points], {}, COLORMAPS);
    const field = drawn.find((l) => l.id === "n41.layer");
    expect(field?.kind === "vector" && Array.isArray(field.colour)).toBe(true);
    expect(drawn.find((l) => l.id === "n10.test")).toMatchObject({ colour: "#d62728" });
    expect(cssColour("#11223344")).toBe("rgba(17, 34, 51, 0.267)");
    expect(cssColour("#112233")).toBe("#112233");
  });

  test("legends: class labels (value when empty), vector swatch with name, field ramp", () => {
    const style = effectiveStyle(fromLayer);
    expect(legendFor(fromLayer, style, fromLayer.raster!.stats, COLORMAPS)).toEqual({
      kind: "classes",
      classes: [
        { value: 1, color: "#FF0000", label: "Low" },
        { value: 2, color: "#0000FF80", label: "2" },
      ],
    });
    expect(legendFor(points, effectiveStyle(points), null, COLORMAPS)).toEqual({
      kind: "vector",
      colour: "#d62728",
      name: "Split Points › test",
    });
    expect(legendFor(byField, effectiveStyle(byField), null, COLORMAPS)).toEqual({
      kind: "ramp",
      colours: COLORMAPS.viridis,
      min: 10,
      max: 30,
    });
    const classesByField = { ...byField, style: { ...byField.style, colormap: CLASSES_CM } };
    expect(legendFor(classesByField, effectiveStyle(classesByField), null, COLORMAPS)).toMatchObject({
      kind: "classes",
    });
  });

  test("the window shows locked fields read-only, from the Map Layer, with Go to", async () => {
    const { patch } = await open([fromLayer, byField]);
    expect(screen.getByTestId("layer-from-n40.layer").textContent).toContain(
      "from Map Layer IMD classes",
    );
    expect((screen.getByTestId("layer-colormap-n40.layer") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByTestId("layer-opacity-n40.layer") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByTestId("legend-n40.layer").textContent).toContain("Low");
    expect(screen.getByTestId("layer-field-n41.layer").textContent).toContain("IMD");
    expect((screen.getByTestId("layer-opacity-n41.layer") as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(screen.getByTestId("layer-visible-n40.layer"));
    expect(patch).toHaveBeenLastCalledWith("n30", {
      map: { styles: { "n40.layer": { visible: false } } },
    });
    fireEvent.click(screen.getByTestId("layer-goto-n40.layer"));
    expect(store.getState().pendingSelect).toEqual(["n40"]);
  });

  test("a map_changed event for the open viewer re-reads its layers", async () => {
    await open([fromLayer]);
    const read = store.api.mapView as unknown as { mock: { calls: unknown[] } };
    const before = read.mock.calls.length;
    vi.spyOn(store, "refreshGraph").mockResolvedValue();
    await act(async () => store.applyEvent({ type: "map_changed", node: "n40", viewers: ["n99"] }));
    expect(read.mock.calls.length).toBe(before);
    await act(async () => store.applyEvent({ type: "map_changed", node: "n40", viewers: ["n30"] }));
    expect(read.mock.calls.length).toBe(before + 1);
  });
});
