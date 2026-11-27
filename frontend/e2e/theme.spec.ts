// Change 02 step 1: screenshot baselines of the synthetic workflow's canvas, a component
// window and the Map Viewer window, taken before any colour moves to theme tokens, so the
// token refactor can be checked to change nothing visible.
//
// Font rendering differs between Windows and Linux, so the comparison runs on Linux only
// (the CI ubuntu job) against the `*-chromium-linux.png` baselines next to this file.
// GEOKNIT_SCREENSHOTS=1 forces it on any platform (to try the test locally; do not commit
// the baselines that writes).
//
// Deterministic by construction: the workflow is pasted fresh (shared server: earlier specs
// leave other nodes, groups and the Show as Text/Icon choice behind), run, then the page is
// reloaded so nothing is selected or hovered, and the canvas is fitted again once every
// node is measured; the map shows only seeded synthetic data
// (the input raster and the test points), on no basemap (no internet tiles); the Panel's
// metrics and the Random Forest log are masked (they depend on the scikit-learn version);
// animations are disabled.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const WORKFLOW = fileURLToPath(new URL("../../examples/synthetic/imd.geoknit", import.meta.url));

const COMPARE = process.platform === "linux" || process.env.GEOKNIT_SCREENSHOTS === "1";

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

interface Graph {
  running: boolean;
  nodes: Record<string, { state: string }>;
  workflow: { groups?: unknown[] };
}

const graph = async (page: Page) => (await api(page, "GET", "/api/graph")) as Graph;

test.describe.serial("theme screenshots", () => {
  test.skip(!COMPARE, "screenshot baselines are Linux-only (set GEOKNIT_SCREENSHOTS=1 to force)");

  let page: Page;
  let viewer = "";
  let raster = ""; // Read Raster (data/imd.tif)
  let split = ""; // Split Points
  let forest = ""; // Random Forest
  let panel = ""; // Panel with the metrics

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");

    // a clean canvas: no nodes, no groups, text display, as the example ships
    const g = await graph(page);
    await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
    for (let n = (await graph(page)).workflow.groups?.length ?? 0; n > 0; n--) {
      await api(page, "DELETE", "/api/groups/0");
    }
    await api(page, "PATCH", "/api/view", { display: "text" });

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
    raster = newId("n2");
    split = newId("n10");
    forest = newId("n16");
    panel = newId("n22");

    const node = (await api(page, "POST", "/api/nodes", {
      component: "param/map",
      position: [2420, 300],
    })) as { id: string };
    viewer = node.id;
    await api(page, "POST", "/api/wires", { from: [raster, "raster"], to: [viewer, "layers"] });
    await api(page, "POST", "/api/wires", { from: [split, "test"], to: [viewer, "layers"] });
    await api(page, "PATCH", `/api/nodes/${viewer}`, { map: { basemap: "none" } });

    // Cached results have no run log; map.spec.ts (or a restarted worker of this spec) may
    // already have run this workflow, so start from an empty cache: every node really runs.
    await api(page, "POST", "/api/cache/clear");
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
    await page.reload(); // fit the view to the workflow; no run logs, nothing selected
    await expect(page.getByTestId(`map-count-${viewer}`)).toContainText("2 layers");
    await expect(page.getByTestId(`panel-text-${panel}`)).toHaveClass(/gk-panel-view/);
    // The fit on page load can run before every node is measured, so the framing varies;
    // fit again now that all nodes (and the Panel's table) are drawn.
    await page.getByTestId("fit").click();
    await page.mouse.move(0, 0); // no hover highlight
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("canvas", async () => {
    await expect(page.getByTestId(`node-${panel}`)).toHaveAttribute("data-state", "done");
    await expect(page.getByTestId("canvas")).toHaveScreenshot("canvas.png", {
      animations: "disabled",
      mask: [page.getByTestId(`panel-text-${panel}`)],
    });
  });

  test("component window", async () => {
    await page.getByTestId(`node-${forest}`).dblclick();
    const win = page.getByTestId("component-window");
    await expect(page.getByTestId("window-title")).toHaveText("Random Forest");
    // the Output loads after the window opens; its log lines (out-of-bag R²) depend on
    // scikit-learn, so they are masked once they are there
    const output = page.getByTestId("output");
    await expect(output).toContainText("trained on");
    await page.mouse.move(0, 0);
    await expect(win).toHaveScreenshot("component-window.png", {
      animations: "disabled",
      mask: [output.locator(".gk-output-body > div:not([data-testid])")],
    });
    await page.getByTestId("window-ok").click();
    await expect(win).toHaveCount(0);
  });

  test("map window", async () => {
    await page.getByTestId(`node-${viewer}`).dblclick();
    const win = page.getByTestId("map-window");
    await expect(win).toBeVisible();
    await expect(page.getByTestId("map-basemap")).toHaveValue("none");
    await expect(page.getByTestId(`layer-${raster}.raster`)).toHaveAttribute("data-status", "ready");
    await expect(page.getByTestId(`layer-${split}.test`)).toHaveAttribute("data-status", "ready");
    await expect(page.getByTestId("map-canvas")).toHaveAttribute("data-ready", "true");
    // every tile drawn and the view settled
    await page.waitForFunction(() => {
      const map = window.__geoknitMap;
      return !!map && map.loaded() && map.areTilesLoaded() && !map.isMoving();
    });
    await page.mouse.move(0, 0);
    await expect(win).toHaveScreenshot("map-window.png", { animations: "disabled" });
    await page.getByTestId("map-close").click();
    await expect(win).toHaveCount(0);
  });
});
