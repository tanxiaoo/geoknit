// PLAN Phase 5 "Done when", on the synthetic example:
// 1. build the workflow from scratch with drag and drop, run it, the metrics Panel fills in;
// 2. change a slider: exactly the downstream nodes turn out of date; Run recomputes only those;
// 3. reload the page: the workflow comes back identical.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));

interface RecipeNode {
  id: string;
  component: string;
  position: [number, number];
  value?: unknown;
  style?: Record<string, unknown>;
  min?: number;
  max?: number;
  step?: number;
}
interface Recipe {
  nodes: RecipeNode[];
  wires: { from: [string, string]; to: [string, string] }[];
}

const recipe = JSON.parse(
  readFileSync(join(here, "..", "..", "examples", "synthetic", "imd.geoknit"), "utf-8"),
) as Recipe;

// Settings are edited in the component window (Phase 6). Until then the canvas
// builds the same workflow with default settings: Stratified Sample stores the
// sampled value in "value" (not "IMD") and Split Points is not stratified.
const textValue = (v: unknown) => (v === "IMD" ? "value" : String(v));

/** Files the folder tree drags onto the canvas instead of typing them. */
const FROM_TREE = new Set(["data/imd.tif", "data/aoi.gpkg", "data/predictors.tif"]);

const TABS: Record<string, string> = {
  raster: "Raster",
  vector: "Vector",
  sampling: "Sampling",
  model: "Model",
  validation: "Validation",
};

/** Params nodes outside the Params tab (ribbon groups, `_layout.yaml`). */
const PARAM_TABS: Record<string, string> = { "param/layer": "Display", "param/map": "Display" };

const ids: Record<string, string> = {}; // recipe id → id on the canvas

async function nodeIds(page: Page): Promise<string[]> {
  return page
    .locator(".react-flow__node")
    .evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.id ?? ""));
}

async function viewport(page: Page) {
  const transform = await page
    .locator(".react-flow__viewport")
    .evaluate((e) => (e as HTMLElement).style.transform);
  const m = /translate\(([-\d.]+)px, ?([-\d.]+)px\) scale\(([-\d.]+)\)/.exec(transform);
  if (!m) throw new Error(`unexpected viewport transform ${transform}`);
  return { x: Number(m[1]), y: Number(m[2]), zoom: Number(m[3]) };
}

async function centre(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("element not visible");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/** Drop something onto the canvas so the new node lands at ``position``. */
async function dropAt(page: Page, source: Locator, position: [number, number]): Promise<string> {
  const before = new Set(await nodeIds(page));
  // Keep the recipe's layout, scaled to the zoom, from the canvas's top-left corner.
  const { zoom } = await viewport(page);
  const target = { x: 30 + position[0] * zoom, y: 30 + position[1] * zoom };
  await source.dragTo(page.getByTestId("canvas"), { targetPosition: target });
  await expect.poll(async () => (await nodeIds(page)).length).toBe(before.size + 1);
  const added = (await nodeIds(page)).find((id) => !before.has(id));
  if (!added) throw new Error("no node was added");
  return added;
}

async function wireCount(page: Page): Promise<number> {
  const graph = await (await page.request.get("/api/graph")).json();
  return graph.workflow.wires.length;
}

async function wire(page: Page, from: [string, string], to: [string, string]) {
  const edges = page.locator(".react-flow__edge");
  const count = await wireCount(page);
  const a = await centre(page.getByTestId(`port-${ids[from[0]]}-out-${from[1]}`));
  const b = await centre(page.getByTestId(`port-${ids[to[0]]}-in-${to[1]}`));
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move((a.x + b.x) / 2, (a.y + b.y) / 2, { steps: 5 });
  await page.mouse.move(b.x, b.y, { steps: 5 });
  await page.mouse.up();
  await expect.poll(() => wireCount(page)).toBe(count + 1);
  await expect(edges).toHaveCount(count + 1);
}

function metrics(text: string): Record<string, number> {
  const lines = text.split("\n");
  const header = lines.findIndex((l) => l.includes("RMSE"));
  const names = lines[header].trim().split(/\s+/);
  const values = lines[header + 1].trim().split(/\s+/).slice(1).map(Number);
  return Object.fromEntries(names.map((n, i) => [n, values[i]]));
}

function panelId(): string {
  return ids[recipe.nodes.find((n) => n.component === "param/panel")!.id];
}

async function snapshot(page: Page) {
  const nodes = await page.locator(".react-flow__node").evaluateAll((els) =>
    els
      .map((e) => {
        const el = e as HTMLElement;
        const inner = el.querySelector<HTMLElement>("[data-state]");
        return [el.dataset.id, el.style.transform, inner?.dataset.state, el.innerText].join("|");
      })
      .sort(),
  );
  const edges = await page
    .locator(".react-flow__edge")
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-testid") ?? "").sort());
  return { nodes, edges };
}

test.describe.serial("canvas", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("build the synthetic workflow by drag and drop, run it, read the metrics", async () => {
    await page.getByRole("button", { name: "Collapse" }).click(); // more room for the canvas
    for (let i = 0; i < 3; i++) await page.getByTestId("zoom-out").click();

    for (const n of recipe.nodes) {
      const value = n.value === undefined ? undefined : textValue(n.value);
      if (n.component === "param/text" && value && FROM_TREE.has(value)) {
        ids[n.id] = await dropAt(page, page.getByTestId(`file-${value}`), n.position);
        await expect(page.getByTestId(`node-${ids[n.id]}`)).toContainText(value);
        continue;
      }
      const tab = n.component.startsWith("param/")
        ? (PARAM_TABS[n.component] ?? "Params")
        : TABS[n.component.split("/")[1]];
      await page.getByTestId(`tab-${tab}`).click();
      ids[n.id] = await dropAt(page, page.getByTestId(`ribbon-${n.component}`), n.position);
      const id = ids[n.id];

      if (n.component === "param/text") {
        await page.getByTestId(`node-${id}`).dblclick();
        await page.getByTestId(`text-input-${id}`).fill(value ?? "");
        await page.getByTestId(`text-input-${id}`).press("Enter");
        await expect(page.getByTestId(`node-${id}`)).toContainText(value ?? "");
      } else if (n.component === "param/slider") {
        await page.getByTestId(`slider-value-${id}`).dblclick();
        await page.getByTestId("slider-min").fill(String(n.min));
        await page.getByTestId("slider-max").fill(String(n.max));
        await page.getByTestId("slider-step").fill(String(n.step));
        await page.getByTestId("slider-value").fill(String(n.value));
        await page.getByTestId("slider-ok").click();
        await expect(page.getByTestId(`slider-value-${id}`)).toHaveText(String(n.value));
      } else if (n.component === "param/colormap" || n.component === "param/layer") {
        // The IMD class Colormap and the Map Layer's name, as in the file (their editors
        // are tested in params-colormap.spec.ts and layer.spec.ts).
        const change = n.component === "param/colormap" ? { value: n.value } : { style: n.style };
        const res = await page.request.patch(`/api/nodes/${id}`, { data: change });
        expect(res.ok(), await res.text()).toBeTruthy();
      }
    }

    for (const w of recipe.wires) await wire(page, w.from, w.to);

    const graph = await (await page.request.get("/api/graph")).json();
    expect(Object.keys(graph.nodes)).toHaveLength(recipe.nodes.length);
    expect(graph.workflow.wires).toHaveLength(recipe.wires.length);

    await page.getByTestId("run").click();
    const panel = page.getByTestId(`panel-text-${panelId()}`);
    await expect(panel).toContainText("RMSE", { timeout: 180_000 });
    const m = metrics(await panel.innerText());
    expect(m.n).toBe(42); // the held-out 30 % of 7 × 20 sample points
    expect(m["R²"]).toBeGreaterThan(0.5);
    await expect(page.locator('[data-state]:not([data-state="done"])')).toHaveCount(0);
  });

  test("changing a slider marks exactly the downstream nodes; Run recomputes only those", async () => {
    const slider = ids["n15"]; // n_trees
    const graph = await (await page.request.get("/api/graph")).json();
    const wires = graph.workflow.wires as { from: [string, string]; to: [string, string] }[];
    const expected = new Set([slider]);
    for (let grew = true; grew; ) {
      grew = false;
      for (const w of wires) {
        if (expected.has(w.from[0]) && !expected.has(w.to[0])) {
          expected.add(w.to[0]);
          grew = true;
        }
      }
    }

    await page.getByTestId(`slider-value-${slider}`).dblclick();
    await page.getByTestId("slider-value").fill("150");
    await page.getByTestId("slider-ok").click();
    await expect(page.getByTestId(`slider-value-${slider}`)).toHaveText("150");

    await expect
      .poll(() =>
        page
          .locator('[data-state="out_of_date"]')
          .evaluateAll((els) => els.map((e) => e.getAttribute("data-testid")!.slice(5)).sort()),
      )
      .toEqual([...expected].sort());
    await expect(page.getByTestId("banner-text")).toContainText("n_trees changed");
    // the banner counts components only, never Params (the slider, Panels)
    const kinds = new Map<string, string>(
      (graph.workflow.nodes as { id: string; component: string }[]).map((n) => [n.id, n.component]),
    );
    const components = [...expected].filter((id) => !kinds.get(id)!.startsWith("param/"));
    await expect(page.getByTestId("banner-text")).toContainText(
      `${components.length} components out of date`,
    );

    const runs = await page.evaluate(() => window.__geoknit!.getState().runCount);
    await page.getByTestId("banner-run").click();
    await page.waitForFunction((n) => window.__geoknit!.getState().runCount > n, runs, {
      timeout: 180_000,
    });
    const report = await page.evaluate(() => window.__geoknit!.getState().lastReport);
    expect(report?.ok).toBe(true);
    expect([...(report?.ran ?? []), ...(report?.cached ?? [])].sort()).toEqual(
      [...expected].sort(),
    );
    await expect(page.locator('[data-state]:not([data-state="done"])')).toHaveCount(0);
    await expect(page.getByTestId(`panel-text-${panelId()}`)).toContainText("RMSE");
  });

  test("reloading the page brings the workflow back identical", async () => {
    await expect(page.getByTestId(`panel-text-${panelId()}`)).toContainText("RMSE");
    const before = await snapshot(page);
    expect(before.nodes).toHaveLength(recipe.nodes.length);

    await page.reload();
    await expect(page.locator(".react-flow__node")).toHaveCount(recipe.nodes.length);
    await expect(page.getByTestId(`panel-text-${panelId()}`)).toContainText("RMSE");
    expect(await snapshot(page)).toEqual(before);
  });
});
