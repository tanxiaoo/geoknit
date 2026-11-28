// Change 03 step 4 "Done when" (Map Viewer with Layers):
// 1. two layers (the classed raster through a Map Layer with a classes Colormap that has
//    labels, and the sample points wired raw) show in the right order; the raster legend
//    lists the class labels;
// 2. changing a class colour in the Colormap editor recolours the open map without any node
//    running (no `started` WebSocket event): the next tile request carries the new `cmap`.
// (3. the clicked-pixel test in map.spec.ts still passes.)
// Clears the canvas first (the specs share one server). The basemap is "none": no internet.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const WORKFLOW = fileURLToPath(new URL("../../examples/synthetic/imd.geoknit", import.meta.url));
const LABELS = ["nodata", "very low", "low", "medium", "high", "very high", "full", "other"];
const CLASSES = LABELS.map((label, v) => [v, ["#1F77B4", "#FF7F0E", "#2CA02C", "#D62728"][v % 4], label]);

interface Graph {
  running: boolean;
  nodes: Record<string, { state: string | null }>;
}

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

const graph = async (page: Page) => (await api(page, "GET", "/api/graph")) as Graph;

test("a Map Layer and a raw wire on one map; a new class colour redraws it without a Run", async ({
  page,
}) => {
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

  // the synthetic workflow's sampling part (Reclassify n4, Stratified Sample n9)
  const doc = JSON.parse(readFileSync(WORKFLOW, "utf-8")) as {
    nodes: { id: string }[];
    wires: unknown[];
  };
  const { ids } = (await api(page, "POST", "/api/paste", {
    nodes: doc.nodes,
    wires: doc.wires,
    offset: [0, 0],
  })) as { ids: string[] };
  const newId = (old: string) => ids[doc.nodes.findIndex((n) => n.id === old)];
  const classes = newId("n4");
  const sample = newId("n9");
  const add = async (component: string, position: [number, number]) =>
    ((await api(page, "POST", "/api/nodes", { component, position })) as { id: string }).id;
  const wire = (from: [string, string], to: [string, string]) =>
    api(page, "POST", "/api/wires", { from, to });
  const colormap = await add("param/colormap", [-500, 0]);
  await api(page, "PATCH", `/api/nodes/${colormap}`, {
    value: { kind: "classes", classes: CLASSES, other: null },
  });
  const layer = await add("param/layer", [-500, 200]);
  const viewer = await add("param/map", [-500, 400]);
  await wire([classes, "classes"], [layer, "data"]);
  await wire([colormap, "value"], [layer, "colormap"]);
  await api(page, "PATCH", `/api/nodes/${layer}`, { style: { name: "IMD classes" } });
  await wire([layer, "layer"], [viewer, "layers"]);
  await wire([sample, "points"], [viewer, "layers"]);
  await api(page, "PATCH", `/api/nodes/${viewer}`, { map: { basemap: "none" } });

  // run what the viewer needs
  await api(page, "POST", "/api/run", { mode: "to_node", node_id: viewer });
  await expect
    .poll(async () => {
      const g = await graph(page);
      return !g.running && g.nodes[viewer].state === "done";
    }, { timeout: 120_000 })
    .toBe(true);
  expect(started).not.toContain(layer);
  expect(started).not.toContain(viewer);
  await page.reload();
  await expect(page.getByTestId("worker-status")).toContainText("idle");

  // open the map: the layer from the Map Layer first, the raw points second (wire order)
  const rasterId = `${layer}.layer`;
  const pointsId = `${sample}.points`;
  const firstTile = page.waitForResponse((r) => r.url().includes("/tiles/") && r.status() === 200);
  await page.getByTestId(`node-${viewer}`).dblclick();
  const win = page.getByTestId("map-window");
  await expect(win).toBeVisible();
  await expect(win.locator(".gk-map-layers > li")).toHaveCount(2);
  const order = await win
    .locator(".gk-map-layers > li")
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")));
  expect(order).toEqual([`layer-${rasterId}`, `layer-${pointsId}`]);
  await expect(page.getByTestId(`layer-${rasterId}`)).toHaveAttribute("data-status", "ready");
  await expect(page.getByTestId(`layer-${pointsId}`)).toHaveAttribute("data-status", "ready");
  await expect(page.getByTestId(`layer-from-${rasterId}`)).toContainText("from Map Layer IMD classes");
  await expect(page.getByTestId(`layer-colormap-${rasterId}`)).toBeDisabled();
  expect(decodeURIComponent((await firstTile).url())).toContain('"#1F77B4"');

  // the raster legend lists the class labels
  const legend = page.getByTestId(`legend-${rasterId}`);
  await expect(legend).toHaveAttribute("data-kind", "classes");
  await expect(legend.locator("li")).toHaveText(LABELS);

  // drawn: the points above the raster (vectors on top, as for raw wires)
  await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
  await expect
    .poll(() =>
      page.evaluate(() => window.__geoknitMap!.getStyle().layers.map((l) => l.id)),
    )
    .toEqual(expect.arrayContaining([`gk-layer-${rasterId}`, `gk-layer-${pointsId}-circle`]));
  const drawn = await page.evaluate(() => window.__geoknitMap!.getStyle().layers.map((l) => l.id));
  expect(drawn.indexOf(`gk-layer-${pointsId}-circle`)).toBeGreaterThan(
    drawn.indexOf(`gk-layer-${rasterId}`),
  );

  // move the map aside, then give class 0 a new colour in the Colormap editor
  const header = win.locator(".gk-window-header");
  const box = (await header.boundingBox())!;
  await page.mouse.move(box.x + 200, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 650, box.y + box.height / 2, { steps: 5 });
  await page.mouse.up();
  const startedBefore = started.length;
  await page.getByTestId(`node-${colormap}`).dblclick();
  await expect(page.getByTestId("colormap-window")).toBeVisible();
  const recoloured = page.waitForResponse(
    (r) =>
      r.url().includes("/tiles/") &&
      decodeURIComponent(r.url()).includes('"#00FF00"') &&
      r.status() === 200,
  );
  const hex = page.getByTestId("cm-class-colour-0-hex");
  await hex.fill("#00FF00");
  await hex.press("Enter");
  await recoloured;
  await expect(legend.locator("li").first().locator(".gk-map-swatch-small")).toHaveCSS(
    "background-color",
    "rgb(0, 255, 0)",
  );
  expect(started.length).toBe(startedBefore); // nothing ran
  const g = await graph(page);
  expect(g.running).toBe(false);
  for (const id of [classes, sample, layer, viewer]) expect(g.nodes[id].state, id).toBe("done");
  await page.getByTestId("colormap-close").click();

  // Go to Map Layer selects that node on the canvas
  await page.getByTestId(`layer-goto-${rasterId}`).click();
  await expect(page.locator(`.react-flow__node[data-id="${layer}"]`)).toHaveClass(/selected/);
  await page.getByTestId("map-close").click();
});
