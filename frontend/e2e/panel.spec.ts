// Change 01 step 8: the Panel viewer (section 11). A Panel on Extract Values' table shows
// the header line and the grid; a Panel on a 1000-row Table loads the next page when
// scrolled. Clears the canvas first (shared server).

import { expect, test, type Page } from "@playwright/test";

const BIG_TABLE = `# geoknit: component
# name: Big Table
# category: Script
# outputs:
#   table: Table
# requires: [pandas]

# --- code ---
import pandas as pd

table = pd.DataFrame({"i": range(1000), "square": [i * i for i in range(1000)]})
`;

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

async function freshCanvas(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  const g = (await api(page, "GET", "/api/graph")) as { nodes: Record<string, unknown> };
  await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
  const add = async (body: unknown) =>
    ((await api(page, "POST", "/api/nodes", body)) as { id: string }).id;
  const wire = (from: [string, string], to: [string, string]) =>
    api(page, "POST", "/api/wires", { from, to });
  const param = async (component: string, value: unknown, position: [number, number]) => {
    const id = await add({ component, position });
    await api(page, "PATCH", `/api/nodes/${id}`, { value });
    return id;
  };
  return { add, wire, param };
}

/** Reload to show the nodes added through the API, once the page holds the workflow. */
async function reloadShowing(page: Page, nodeId: string) {
  await page.reload();
  await expect(page.getByTestId(`node-${nodeId}`)).toBeVisible();
}

async function runTo(page: Page, nodeId: string) {
  await api(page, "POST", "/api/run", { mode: "to_node", node_id: nodeId });
  await expect
    .poll(
      async () => {
        const g = (await api(page, "GET", "/api/graph")) as {
          nodes: Record<string, { state: string }>;
        };
        return g.nodes[nodeId].state;
      },
      { timeout: 120_000 },
    )
    .toBe("done");
}

test("a Panel on Extract Values' table shows the header line and the grid", async ({ page }) => {
  const { add, wire, param } = await freshCanvas(page);
  const rasterPath = await param("param/text", "data/predictors.tif", [0, 0]);
  const aoiPath = await param("param/text", "data/aoi.gpkg", [0, 150]);
  const n = await param("param/number", 30, [0, 300]);
  const seed = await param("param/number", 1, [0, 400]);
  const raster = await add({ component: "builtin/raster/read_raster", position: [200, 0] });
  const aoi = await add({ component: "builtin/vector/read_vector", position: [200, 150] });
  const sample = await add({ component: "builtin/sampling/random_sample", position: [420, 150] });
  const extract = await add({ component: "builtin/sampling/extract_values", position: [640, 0] });
  const panel = await add({ component: "param/panel", position: [860, 0] });
  await wire([rasterPath, "value"], [raster, "path"]);
  await wire([aoiPath, "value"], [aoi, "path"]);
  await wire([raster, "raster"], [sample, "raster"]);
  await wire([aoi, "vector"], [sample, "aoi"]);
  await wire([n, "value"], [sample, "n"]);
  await wire([seed, "value"], [sample, "seed"]);
  await wire([sample, "points"], [extract, "points"]);
  await wire([raster, "raster"], [extract, "raster"]);
  await wire([extract, "table"], [panel, "data"]);
  await api(page, "PATCH", `/api/nodes/${panel}`, { size: [360, 220] });
  await reloadShowing(page, panel);

  await runTo(page, panel);
  const out = (await api(page, "GET", `/api/nodes/${extract}/output`)) as {
    views: { table: { total_rows: number; columns: string[] } };
  };
  const { total_rows: rows, columns } = out.views.table;
  expect(rows).toBeGreaterThan(0);
  const header = page.getByTestId(`panel-header-${panel}`);
  await expect(header).toHaveText(
    `${rows} row${rows === 1 ? "" : "s"} × ${columns.length} column${columns.length === 1 ? "" : "s"}`,
  );
  const grid = page.getByTestId(`panel-grid-${panel}`);
  await expect(grid.locator("thead th")).toHaveText(["", ...columns]);
  await expect(grid).toHaveAttribute("data-rows", String(rows));
  await expect(page.getByTestId(`panel-row-${panel}-0`).locator("th")).toHaveText("0");
  // the grid scrolls inside the Panel, which keeps its size
  const box = await page.getByTestId(`node-${panel}`).boundingBox();
  expect(box?.height).toBeLessThan(260);
});

test("a Panel on a 1000-row Table loads the next page when scrolled", async ({ page }) => {
  const { add, wire } = await freshCanvas(page);
  const big = await add({ component: "inline", source: BIG_TABLE, position: [100, 100] });
  const panel = await add({ component: "param/panel", position: [450, 100] });
  await wire([big, "table"], [panel, "data"]);
  await api(page, "PATCH", `/api/nodes/${panel}`, { size: [300, 240] });
  await reloadShowing(page, panel);

  await runTo(page, panel);
  await expect(page.getByTestId(`panel-header-${panel}`)).toHaveText("1000 rows × 2 columns");
  const grid = page.getByTestId(`panel-grid-${panel}`);
  await expect(grid).toHaveAttribute("data-rows", "200");
  await expect(page.getByTestId(`panel-row-${panel}-200`)).toHaveCount(0);

  await grid.evaluate((el) => el.scrollTo(0, el.scrollHeight));
  await expect(grid).toHaveAttribute("data-rows", "400");
  const row = page.getByTestId(`panel-row-${panel}-399`);
  await expect(row.locator("th, td")).toHaveText(["399", "399", String(399 * 399)]);
  await expect(page.getByTestId(`panel-note-${panel}`)).toHaveCount(0);
  await expect(page.getByTestId(`panel-error-${panel}`)).toHaveCount(0);
});
