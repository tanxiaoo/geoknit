// Change 02 step 4: the theme never recolours the data on the map. The synthetic
// Reclassify output (a classed raster, drawn with its class palette and nearest pixels) is
// shown in the Map Viewer in the light theme and in the dark theme, and the pixels of the
// map canvas at the same places on the data must be identical.
//
// MapLibre does not keep its drawing buffer, so the pixels are read from a screenshot of
// the map canvas, decoded by drawing it into a 2D canvas in the page. The sampled points
// are inside the raster's bounds, away from the edges (and the controls); a point where the
// light map background shows through (no data) is dropped. Basemap `none`: no internet.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

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

type Rgba = [number, number, number, number];

test.describe.serial("map layers in both themes", () => {
  let page: Page;
  let viewer = "";
  let classes = ""; // Reclassify

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");
    const g = await graph(page);
    await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });

    const doc = JSON.parse(readFileSync(WORKFLOW, "utf-8")) as {
      nodes: { id: string; component: string }[];
      wires: unknown[];
    };
    const { ids } = (await api(page, "POST", "/api/paste", {
      nodes: doc.nodes,
      wires: doc.wires,
      offset: [0, 0],
    })) as { ids: string[] };
    classes = ids[doc.nodes.findIndex((n) => n.id === "n4")];

    const node = (await api(page, "POST", "/api/nodes", {
      component: "param/map",
      position: [2100, 300],
    })) as { id: string };
    viewer = node.id;
    await api(page, "POST", "/api/wires", { from: [classes, "classes"], to: [viewer, "layers"] });
    await api(page, "PATCH", `/api/nodes/${viewer}`, { map: { basemap: "none" } });
    await api(page, "POST", "/api/run", { mode: "all" });
    await expect
      .poll(
        async () => {
          const now = await graph(page);
          return !now.running && Object.values(now.nodes).every((n) => n.state === "done");
        },
        { timeout: 120_000 },
      )
      .toBe(true);
  });

  test.afterAll(async () => {
    await api(page, "PATCH", "/api/settings", { theme: "system" });
    await page.close();
  });

  /** Open the map in ``theme`` and read the canvas pixels at the given fractions of the
   * raster's bounds; also the map background colour of that theme. */
  async function sample(theme: "light" | "dark", at: [number, number][]) {
    await api(page, "PATCH", "/api/settings", { theme });
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByTestId(`map-count-${viewer}`)).toContainText("1 layer");
    await page.getByTestId(`node-${viewer}`).dblclick();
    await expect(page.getByTestId("map-window")).toBeVisible();
    await expect(page.getByTestId(`layer-${classes}.classes`)).toHaveAttribute("data-status", "ready");
    await expect(page.getByTestId(`legend-${classes}.classes`)).toHaveAttribute("data-kind", "classes");
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
    await page.waitForFunction(() => {
      const map = window.__geoknitMap;
      return !!map && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    });
    await page.mouse.move(0, 0);

    const layers = ((await api(page, "GET", `/api/map/${viewer}`)) as {
      layers: { raster?: { bounds: [number, number, number, number] } }[];
    }).layers;
    const [west, south, east, north] = layers[0].raster!.bounds;
    const points = await page.evaluate(
      (lonLats) => lonLats.map((p) => window.__geoknitMap!.project(p)).map((p) => [p.x, p.y]),
      at.map(([fx, fy]) => [west + fx * (east - west), south + fy * (north - south)] as [number, number]),
    );
    const png = await page.locator(".maplibregl-canvas").screenshot({ animations: "disabled" });
    const { pixels, background } = await page.evaluate(
      async ({ b64, pts }) => {
        const img = new Image();
        img.src = `data:image/png;base64,${b64}`;
        await img.decode();
        const c = document.createElement("canvas");
        c.width = img.width;
        c.height = img.height;
        const ctx = c.getContext("2d", { willReadFrequently: true })!;
        ctx.drawImage(img, 0, 0);
        const read = ([x, y]: number[]) => Array.from(ctx.getImageData(Math.round(x), Math.round(y), 1, 1).data);
        // the map-bg token as RGBA, through the same 2D canvas
        ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--gk-map-bg").trim();
        ctx.fillRect(0, 0, 1, 1);
        return { pixels: pts.map(read), background: read([0, 0]) };
      },
      { b64: png.toString("base64"), pts: points },
    );
    await page.getByTestId("map-close").click();
    await expect(page.getByTestId("map-window")).toHaveCount(0);
    return { pixels: pixels as Rgba[], background: background as Rgba };
  }

  test("a classed raster has the same colours in light and dark", async () => {
    const at: [number, number][] = [];
    for (const fx of [0.3, 0.5, 0.7]) for (const fy of [0.3, 0.5, 0.7]) at.push([fx, fy]);

    const light = await sample("light", at);
    const dark = await sample("dark", at);
    expect(dark.background).not.toEqual(light.background); // the themes really differ

    const same = (a: Rgba, b: Rgba) => a.every((v, i) => Math.abs(v - b[i]) <= 2);
    const onData = at.map((_, i) => i).filter((i) => !same(light.pixels[i], light.background));
    expect(onData.length).toBeGreaterThanOrEqual(5); // the samples are on the data
    for (const i of onData) {
      expect(dark.pixels[i], `pixel at ${at[i].join(", ")} of the bounds`).toEqual(light.pixels[i]);
      expect(same(dark.pixels[i], dark.background)).toBe(false);
    }
  });
});
