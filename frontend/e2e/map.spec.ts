// PLAN Phase 7 "Done when" (Map Viewer):
// 1. the synthetic predicted raster and the reference points show in the right place;
// 2. the clicked pixel value is the value the server reads there (the server test compares
//    that with rasterio: tests/server/test_map_viewer.py);
// 3. tiles come from overviews (server test); here: the tiles load and follow style changes.
// The basemap is set to "none" so the test needs no internet.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

interface MapLayerView {
  id: string;
  status: string;
  key: string | null;
  raster?: { bounds: [number, number, number, number] };
  vector?: { bounds: [number, number, number, number]; features: number };
}

const WORKFLOW = fileURLToPath(new URL("../../examples/synthetic/imd.geoknit", import.meta.url));

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

async function graph(page: Page) {
  return (await api(page, "GET", "/api/graph")) as {
    running: boolean;
    nodes: Record<string, { state: string }>;
  };
}

/** Pixel position of lon/lat inside the map canvas, in page coordinates. */
async function pagePoint(page: Page, lon: number, lat: number) {
  const box = (await page.getByTestId("map-canvas").boundingBox())!;
  const p = await page.evaluate(
    ([x, y]) => window.__geoknitMap!.project([x, y]),
    [lon, lat] as const,
  );
  return { x: box.x + p.x, y: box.y + p.y };
}

test.describe.serial("map viewer", () => {
  let page: Page;
  let viewer = "";
  let pred = ""; // Predict Raster
  let split = ""; // Split Points

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");
    const g = await graph(page);
    await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });

    // the synthetic workflow, pasted through the API (the project has its data/ folder)
    const doc = JSON.parse(readFileSync(WORKFLOW, "utf-8")) as {
      nodes: { id: string; component: string }[];
      wires: unknown[];
    };
    const { ids } = (await api(page, "POST", "/api/paste", {
      nodes: doc.nodes,
      wires: doc.wires,
      offset: [0, 0],
    })) as { ids: string[] };
    const newId = (old: string) => ids[doc.nodes.findIndex((n) => n.id === old)];
    pred = newId("n17");
    split = newId("n10");

    const node = (await api(page, "POST", "/api/nodes", {
      component: "param/map",
      position: [2100, 300],
    })) as { id: string };
    viewer = node.id;
    await api(page, "POST", "/api/wires", { from: [pred, "map"], to: [viewer, "layers"] });
    await api(page, "POST", "/api/wires", { from: [split, "test"], to: [viewer, "layers"] });
    await api(page, "PATCH", `/api/nodes/${viewer}`, { map: { basemap: "none" } });

    await api(page, "POST", "/api/run", { mode: "all" });
    await expect
      .poll(async () => {
        const now = await graph(page);
        return !now.running && Object.values(now.nodes).every((n) => n.state === "done");
      }, { timeout: 120_000 })
      .toBe(true);
    await page.reload();
    await expect(page.getByTestId(`map-count-${viewer}`)).toContainText("2 layers");
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("double-click opens the map with both layers in the right place", async () => {
    const tile = page.waitForResponse((r) => r.url().includes("/tiles/") && r.status() === 200);
    await page.getByTestId(`node-${viewer}`).dblclick();
    await expect(page.getByTestId("map-window")).toBeVisible();
    await expect(page.getByTestId(`layer-${pred}.map`)).toHaveAttribute("data-status", "ready");
    await expect(page.getByTestId(`layer-${split}.test`)).toHaveAttribute("data-status", "ready");
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
    expect((await tile).headers()["content-type"]).toBe("image/png");
    // the map is really on screen (not just rendered off-screen)
    const box = (await page.getByTestId("map-canvas").boundingBox())!;
    const hit = await page.evaluate(
      ([x, y]) => document.elementFromPoint(x, y)?.tagName,
      [box.x + box.width / 2, box.y + box.height / 2] as const,
    );
    expect(hit).toBe("CANVAS");

    const layers = ((await api(page, "GET", `/api/map/${viewer}`)) as { layers: MapLayerView[] })
      .layers;
    const [west, south, east, north] = layers[0].raster!.bounds;
    // the view is framed on the raster: it contains it, and is not much larger
    const view = await page.evaluate(() => window.__geoknitMap!.getBounds().toArray());
    expect(view[0][0]).toBeLessThanOrEqual(west);
    expect(view[0][1]).toBeLessThanOrEqual(south);
    expect(view[1][0]).toBeGreaterThanOrEqual(east);
    expect(view[1][1]).toBeGreaterThanOrEqual(north);
    expect(view[1][1] - view[0][1]).toBeLessThan(4 * (north - south));

    // all 42 reference points are drawn, inside the raster
    await expect
      .poll(() =>
        page.evaluate(
          (id) =>
            window.__geoknitMap!.queryRenderedFeatures({ layers: [`gk-layer-${id}-circle`] }).length,
          `${split}.test`,
        ),
      )
      .toBe(42);
    const [pw, ps, pe, pn] = layers[1].vector!.bounds;
    expect(pw >= west && pe <= east && ps >= south && pn <= north).toBe(true);
    await expect(page.getByTestId(`legend-${pred}.map`)).toHaveAttribute("data-kind", "ramp");
  });

  test("a click shows the value of the pixel under it", async () => {
    const layers = ((await api(page, "GET", `/api/map/${viewer}`)) as { layers: MapLayerView[] })
      .layers;
    const [west, south, east, north] = layers[0].raster!.bounds;
    const at = await pagePoint(page, west + 0.37 * (east - west), south + 0.61 * (north - south));
    await page.mouse.click(at.x, at.y);

    const panel = page.getByTestId("inspect");
    const cell = page.getByTestId(`inspect-value-${pred}.map-IMD`);
    await expect(cell).toBeVisible();
    const lon = Number(await panel.getAttribute("data-lon"));
    const lat = Number(await panel.getAttribute("data-lat"));
    const found = (await api(page, "GET", `/api/map/${viewer}/inspect?lon=${lon}&lat=${lat}`)) as {
      layers: { id: string; values: { value: number }[] }[];
    };
    const value = found.layers.find((l) => l.id === `${pred}.map`)!.values[0].value;
    expect(Number(await cell.textContent())).toBeCloseTo(value, 2);
  });

  test("a new colormap is saved and redraws the tiles", async () => {
    const tile = page.waitForResponse((r) => r.url().includes("colormap=magma"));
    await page.getByTestId(`layer-colormap-${pred}.map`).selectOption("magma");
    expect((await tile).status()).toBe(200);
    await expect
      .poll(async () => {
        const g = (await api(page, "GET", "/api/graph")) as {
          nodes: Record<string, { map?: { styles?: Record<string, { colormap?: string }> } }>;
        };
        return g.nodes[viewer].map?.styles?.[`${pred}.map`]?.colormap;
      })
      .toBe("magma");
    await page.screenshot({ path: test.info().outputPath("map-window.png") });
    await page.getByTestId("map-close").click();
    await expect(page.getByTestId("map-window")).toHaveCount(0);
  });
});
