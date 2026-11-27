// Change 03 step 3 "Done when": a Map Layer fed by Read Raster and a Colormap node is done
// once Read Raster is, without a run of its own; changing the Colormap marks only the
// Colormap out of date; a Panel on the layer shows name, source and style; the layer's
// window sets opacity and name, and they persist. Also: the Display tab. Runs after
// editing.spec.ts (it needs a fresh workflow); clears the canvas first (shared server).

import { expect, test, type Page } from "@playwright/test";

interface NodeView {
  state: string | null;
  style?: Record<string, unknown>;
  layer?: { key: string | null; value: { name: string; opacity: number } | null } | null;
}
interface Graph {
  path: string | null;
  out_of_date: number;
  nodes: Record<string, NodeView>;
}

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

const graph = async (page: Page): Promise<Graph> => (await api(page, "GET", "/api/graph")) as Graph;
const stateOf = async (page: Page, id: string) => (await graph(page)).nodes[id].state;

async function runAndWait(page: Page, body: unknown, done: string) {
  await api(page, "POST", "/api/run", body);
  await expect.poll(() => stateOf(page, done), { timeout: 120_000 }).toBe("done");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
}

test("the Display tab holds Map Layer (Style) and Map Viewer (Map)", async ({ page }) => {
  await page.goto("/");
  const res = await page.request.get("/api/components");
  const { tabs } = (await res.json()) as {
    tabs: { name: string; colour: string; groups: string[] }[];
  };
  const display = tabs.find((t) => t.name === "Display");
  expect(display).toMatchObject({ colour: "#A21CAF", groups: ["Style", "Map"] });
  expect(tabs.find((t) => t.name === "Params")?.groups).not.toContain("Map");

  await page.getByTestId("tab-Display").click();
  await expect(page.locator(".gk-ribbon-group-label")).toHaveText(["Style", "Map"]);
  await expect(page.getByTestId("ribbon-group-Style").locator(".gk-component-button")).toHaveText([
    "Map Layer",
  ]);
  await expect(page.getByTestId("ribbon-group-Map").locator(".gk-component-button")).toHaveText([
    "Map Viewer",
  ]);
  await expect(page.getByTestId("ribbon-param/layer").locator(".gk-button-icon")).toHaveCSS(
    "color",
    "rgb(162, 28, 175)",
  );
});

test("a Map Layer is a view node: done with its data, restyled without a Run", async ({ page }) => {
  // every node the worker starts (a Map Layer must never be one)
  const started: string[] = [];
  page.on("websocket", (ws) =>
    ws.on("framereceived", (f) => {
      const ev = JSON.parse(String(f.payload)) as { type?: string; node?: string };
      if (ev.type === "started" && ev.node) started.push(ev.node);
    }),
  );
  await page.goto("/");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  const g0 = await graph(page);
  await api(page, "POST", "/api/delete", { nodes: Object.keys(g0.nodes), wires: [] });
  const add = async (component: string, position: [number, number]) =>
    ((await api(page, "POST", "/api/nodes", { component, position })) as { id: string }).id;
  const wire = (from: [string, string], to: [string, string]) =>
    api(page, "POST", "/api/wires", { from, to });

  const path = await add("param/text", [0, 0]);
  await api(page, "PATCH", `/api/nodes/${path}`, { value: "data/imd.tif" });
  const bandsText = await add("param/text", [0, 150]);
  await api(page, "PATCH", `/api/nodes/${bandsText}`, { value: "1" });
  const raster = await add("builtin/raster/read_raster", [220, 0]);
  const select = await add("builtin/raster/band_select", [460, 150]);
  const colormap = await add("param/colormap", [220, 260]);
  await api(page, "PATCH", `/api/nodes/${colormap}`, {
    value: {
      kind: "classes",
      classes: [
        [1, "#FF0000", "Low"],
        [2, "#0000FF", "High"],
      ],
      other: null,
    },
  });
  const layer = await add("param/layer", [460, 300]);
  const panel = await add("param/panel", [720, 300]);
  await wire([path, "value"], [raster, "path"]);
  await wire([raster, "raster"], [select, "raster"]);
  await wire([bandsText, "value"], [select, "bands"]);
  await wire([raster, "raster"], [layer, "data"]);
  await wire([colormap, "value"], [layer, "colormap"]);
  await wire([layer, "layer"], [panel, "data"]);
  await api(page, "PATCH", `/api/nodes/${panel}`, { size: [360, 120] });
  await page.reload();

  // the node: data and style inputs, a layer output
  const node = page.getByTestId(`node-${layer}`);
  await expect(node).toBeVisible();
  for (const p of ["data", "colormap", "color", "opacity", "bands", "name"]) {
    await expect(page.getByTestId(`port-${layer}-in-${p}`)).toBeVisible();
  }
  await expect(page.getByTestId(`port-${layer}-out-layer`)).toHaveAttribute("data-type", "Layer");

  // the window sets opacity and name: one patch each
  const patches: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "PATCH" && r.url().endsWith(`/api/nodes/${layer}`)) {
      patches.push(r.postData() ?? "");
    }
  });
  await node.dblclick();
  const win = page.getByTestId("layer-window");
  await expect(win).toBeVisible();
  await expect(page.getByTestId("layer-colormap-wired")).toContainText("2 classes");
  await page.getByTestId("layer-opacity").fill("0.5");
  await expect.poll(() => patches.length).toBe(1);
  await page.getByTestId("layer-name").fill("IMD classes");
  await page.getByTestId("layer-name").press("Enter");
  await expect.poll(() => patches.length).toBe(2);
  await expect
    .poll(async () => (await graph(page)).nodes[layer].style)
    .toEqual({ opacity: 0.5, name: "IMD classes" });
  expect(patches.map((p) => JSON.parse(p))).toEqual([
    { style: { opacity: 0.5 } },
    { style: { name: "IMD classes" } },
  ]);
  await page.getByTestId("layer-close").click();

  // Read Raster alone: the layer is done with it, Band Select still needs a run
  await runAndWait(page, { mode: "to_node", node_id: raster }, raster);
  await expect.poll(() => stateOf(page, layer)).toBe("done");
  expect(await stateOf(page, select)).not.toBe("done");
  await expect(node).toHaveAttribute("data-state", "done");

  // everything: the Panel shows the layer's name, source and style
  await runAndWait(page, { mode: "all" }, panel);
  const g1 = await graph(page);
  expect(g1.out_of_date).toBe(0);
  expect(started).not.toContain(layer);
  expect(started).toContain(raster);
  const panelNode = page.getByTestId(`node-${panel}`);
  await expect(panelNode).toContainText("Layer · IMD classes · raster");
  await expect(panelNode).toContainText("source ");
  await expect(panelNode).toContainText("opacity 0.5");
  await expect(panelNode).toContainText("colormap");

  // a new class colour in the Colormap editor: only the Colormap is out of date
  const keyBefore = g1.nodes[layer].layer?.key;
  expect(keyBefore).toBeTruthy();
  const startedBefore = started.length;
  await page.getByTestId(`node-${colormap}`).dblclick();
  await expect(page.getByTestId("colormap-window")).toBeVisible();
  const hex = page.getByTestId("cm-class-colour-0-hex");
  await hex.fill("#00FF00");
  await hex.press("Enter");
  await expect.poll(async () => (await graph(page)).nodes[layer].layer?.key).not.toBe(keyBefore);
  const g2 = await graph(page);
  expect(g2.nodes[colormap].state).toBe("out_of_date");
  for (const id of [raster, select, layer, panel]) expect(g2.nodes[id].state, id).toBe("done");
  expect(g2.out_of_date).toBe(1);
  await expect(page.getByTestId("banner-text")).toContainText("1 component out of date");
  await expect(node).toHaveAttribute("data-state", "done");
  await expect(page.getByTestId(`node-${select}`)).toHaveAttribute("data-state", "done");
  expect(started.length).toBe(startedBefore); // nothing ran
  await page.getByTestId("colormap-close").click();

  // opacity and name persist: save, reopen, the window shows them
  await api(page, "POST", "/api/workflow/save", { path: "layer.geoknit" });
  await api(page, "POST", "/api/workflow/open", { path: "layer.geoknit" });
  await page.reload();
  expect((await graph(page)).path).toBe("layer.geoknit");
  expect((await graph(page)).nodes[layer].style).toEqual({ opacity: 0.5, name: "IMD classes" });
  await page.getByTestId(`node-${layer}`).dblclick();
  await expect(page.getByTestId("layer-opacity")).toHaveValue("0.5");
  await expect(page.getByTestId("layer-opacity-value")).toHaveText("0.50");
  await expect(page.getByTestId("layer-name")).toHaveValue("IMD classes");
  await page.getByTestId("layer-close").click();
});
