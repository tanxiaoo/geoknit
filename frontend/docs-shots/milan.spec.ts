// Screenshots for docs/milan-walkthrough.md, on a scratch copy of the Milan example
// (serve_milan.py). They are written to docs/img/milan/; run again after UI changes.
// A dark pass (change 02) writes 01-opened-dark.png and 06-map-viewer-dark.png; the theme
// is set through the API (the settings file is private to the run, see serve_milan.py)
// and set back to `system` (light here: colorScheme in the config) afterwards. The map
// shots (change 03) use the example's own Map Viewer, then wire the predicted map into it.

import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "img", "milan");
const shot = (name: string) => join(OUT, name);

interface Graph {
  running: boolean;
  nodes: Record<string, { state: string; component: string }>;
}

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

async function runAndWait(page: Page): Promise<void> {
  await page.getByTestId("run").click();
  await expect
    .poll(
      async () => {
        const g = (await api(page, "GET", "/api/graph")) as Graph;
        return !g.running && Object.values(g.nodes).every((n) => n.state === "done");
      },
      { timeout: 540_000, intervals: [2_000] },
    )
    .toBe(true);
}

/** The Assistant placeholder takes room the screenshots need; it reopens on reload. */
async function collapseAssistant(page: Page): Promise<void> {
  const head = page.getByTestId("assistant").locator(".gk-assistant-head button");
  if (await head.count()) await head.click();
}

/**
 * Fit the workflow, then wheel-zoom in until the zoom reaches `percent`, around a
 * point on empty canvas just right of `target` (that point stays put, so `target`
 * and what is left of it grow towards the left and stay on screen).
 */
async function zoomLeftOf(page: Page, target: Locator, percent: number): Promise<void> {
  await page.getByTestId("fit").click();
  const box = (await target.boundingBox())!;
  await page.mouse.move(box.x + box.width + 20, box.y + box.height / 2);
  const zoom = async () => Number((await page.getByTestId("zoom").innerText()).replace("%", ""));
  for (let i = 0; i < 60 && (await zoom()) < percent; i++) {
    await page.mouse.wheel(0, -60);
    await page.waitForTimeout(60);
  }
}

/** Save the theme setting and reload the page in it. */
async function setTheme(page: Page, theme: "system" | "dark"): Promise<void> {
  await api(page, "PATCH", "/api/settings", { theme });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme === "dark" ? "dark" : "light");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  await collapseAssistant(page);
}

const node = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);

/** A screenshot of `boxes` together, with a margin, clipped to the viewport. */
async function shotAround(page: Page, path: string, boxes: Locator[], margin = 16): Promise<void> {
  const rects = await Promise.all(boxes.map(async (b) => (await b.boundingBox())!));
  const x = Math.max(0, Math.min(...rects.map((r) => r.x)) - margin);
  const y = Math.max(0, Math.min(...rects.map((r) => r.y)) - margin);
  const right = Math.max(...rects.map((r) => r.x + r.width)) + margin;
  const bottom = Math.max(...rects.map((r) => r.y + r.height)) + margin;
  const view = page.viewportSize()!;
  await page.screenshot({
    path,
    clip: { x, y, width: Math.min(right, view.width) - x, height: Math.min(bottom, view.height) - y },
  });
}

test.describe.serial("Milan walkthrough", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");
    await collapseAssistant(page);
  });

  test.afterAll(async () => {
    await api(page, "PATCH", "/api/settings", { theme: "system" });
    await page.close();
  });

  test("the workflow before running", async () => {
    await page.getByTestId("fit").click();
    await page.screenshot({ path: shot("01-opened.png") });
    await setTheme(page, "dark");
    await page.getByTestId("fit").click();
    await page.mouse.move(0, 0);
    await page.screenshot({ path: shot("01-opened-dark.png") });
    await setTheme(page, "system");
  });

  test("after Run: the canvas and the metrics Panel", async () => {
    await runAndWait(page);
    await expect(page.getByTestId("panel-text-n22")).toContainText("RMSE");
    await page.getByTestId("fit").click();
    await page.screenshot({ path: shot("02-ran.png") });
    await zoomLeftOf(page, node(page, "n22"), 100);
    await shotAround(page, shot("03-metrics.png"), [node(page, "n21"), node(page, "n22")], 24);
  });

  test("the component window: settings and code", async () => {
    await page.getByTestId("node-n16").dblclick();
    const win = page.getByTestId("component-window");
    await expect(page.getByTestId("window-title")).toHaveText("Random Forest");
    await expect(page.getByTestId("output-state")).toBeVisible();
    await shotAround(page, shot("04-settings.png"), [win]);
    await page.getByTestId("window-tab-code").click();
    await expect(win.locator(".monaco-editor .view-lines")).toBeVisible();
    await page.waitForTimeout(500); // syntax colours
    await shotAround(page, shot("05-code.png"), [win]);
    await page.getByTestId("window-ok").click();
    await expect(win).toHaveCount(0);
  });

  /** Open the Map Viewer and wait for `layers` and their tiles. */
  async function openMap(id: string, layers: string[]): Promise<Locator> {
    await page.getByTestId(`node-${id}`).dblclick();
    const win = page.getByTestId("map-window");
    await expect(win).toBeVisible();
    for (const layer of layers) {
      await expect(page.getByTestId(`layer-${layer}`)).toHaveAttribute("data-status", "ready");
    }
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
    await page.waitForTimeout(4_000); // basemap and raster tiles
    await page.waitForFunction(() => !!window.__geoknitMap?.loaded(), null, { timeout: 30_000 });
    return win;
  }

  // The example's Map Viewer (n25): Map Layer n24 draws Reclassify's classes with the
  // IMD class Colormap n23, and the test points of Split Points come in raw.
  const VIEWER = "n25";
  const CLASSES = "n24.layer";
  const POINTS = "n10.test";

  test("the map nodes and the Colormap editor", async () => {
    await zoomLeftOf(page, node(page, "n24"), 100);
    await shotAround(page, shot("06-map-nodes.png"), [
      node(page, "n23"),
      node(page, "n24"),
      node(page, VIEWER),
    ], 24);
    await page.getByTestId("node-n23").dblclick();
    const editor = page.getByTestId("colormap-window");
    await expect(editor).toBeVisible();
    await shotAround(page, shot("06-colormap.png"), [editor]);
    await page.getByTestId("colormap-close").click();
    await expect(editor).toHaveCount(0);
  });

  test("the Map Viewer: IMD classes from a Map Layer, and the test points", async () => {
    await page.getByTestId("fit").click();
    await shotAround(page, shot("06-map-viewer.png"), [await openMap(VIEWER, [CLASSES, POINTS])]);
    await expect(page.getByTestId(`layer-from-${CLASSES}`)).toBeVisible();
    await page.getByTestId("map-close").click();

    // dark: basemap "auto" (the default) follows the theme
    await setTheme(page, "dark");
    const dark = await openMap(VIEWER, [CLASSES, POINTS]);
    await expect(page.getByTestId("map-basemap")).toHaveValue("auto");
    await shotAround(page, shot("06-map-viewer-dark.png"), [dark]);
    await page.getByTestId("map-close").click();
    await setTheme(page, "system");
  });

  test("the predicted map in the same viewer", async () => {
    await api(page, "POST", "/api/wires", { from: ["n17", "map"], to: [VIEWER, "layers"] });
    await page.reload();
    await collapseAssistant(page);
    await expect(page.getByTestId("worker-status")).toContainText("idle");
    await openMap(VIEWER, [CLASSES, POINTS, "n17.map"]);
    // the classes are drawn above the predicted map (wire order); hide them
    const visible = page.getByTestId(`layer-visible-${CLASSES}`);
    await visible.click(); // saved through the API, then drawn: not checked at once
    await expect(visible).not.toBeChecked();
    await page.waitForTimeout(2_000);
    await shotAround(page, shot("06-map-prediction.png"), [page.getByTestId("map-window")]);
    await page.getByTestId("map-close").click();
  });

  test("Export .py", async () => {
    await page.getByTestId("export-py").click();
    await expect(page.getByTestId("export-input")).toHaveValue("milan_imd.py");
    await shotAround(page, shot("07-export.png"), [
      page.getByTestId("export-py"),
      page.getByTestId("export-menu"),
    ]);
    await page.keyboard.press("Escape");
  });
});
