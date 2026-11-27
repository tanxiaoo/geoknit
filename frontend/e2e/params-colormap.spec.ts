// Runs after editing.spec.ts (it saves a workflow). Change 03 step 2 "Done when": a 3-class map built in the Colormap editor survives save and
// reopen; a pasted class table replaces the classes. Clears the canvas first (shared server).

import { expect, test, type Page } from "@playwright/test";

interface Graph {
  path: string | null;
  nodes: Record<string, { value?: unknown }>;
}

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

const graph = async (page: Page): Promise<Graph> => (await api(page, "GET", "/api/graph")) as Graph;
const valueOf = async (page: Page, id: string): Promise<unknown> => (await graph(page)).nodes[id].value;

/** Type into a field of the editor and send it (Enter). */
async function enter(page: Page, testId: string, text: string): Promise<void> {
  const field = page.getByTestId(testId);
  await field.fill(text);
  await field.press("Enter");
}

test("a 3-class colormap built in the editor is the same after save and reopen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  const g = await graph(page);
  await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
  const { id } = (await api(page, "POST", "/api/nodes", {
    component: "param/colormap",
    position: [200, 200],
  })) as { id: string };
  await page.reload();

  await page.getByTestId(`node-${id}`).dblclick();
  const win = page.getByTestId("colormap-window");
  await expect(win).toBeVisible();
  await expect(page.getByTestId("cm-ramp")).toHaveValue("viridis");

  await page.getByTestId("cm-kind-classes").click();
  await expect(page.getByTestId("cm-class-0")).toBeVisible();
  await page.getByTestId("cm-class-add").click();
  await page.getByTestId("cm-class-add").click();
  await expect(win.getByTestId(/^cm-class-\d$/)).toHaveCount(3);
  await enter(page, "cm-class-label-0", "Low");
  await enter(page, "cm-class-label-1", "Medium");
  await enter(page, "cm-class-label-2", "High");
  await enter(page, "cm-class-colour-1-hex", "#00ff0080");
  await page.getByTestId("cm-other-colour").check();

  const built = {
    kind: "classes",
    classes: [
      [1, "#440154", "Low"],
      [2, "#00FF0080", "Medium"],
      [3, "#2CA02C", "High"],
    ],
    other: "#808080",
  };
  await expect.poll(() => valueOf(page, id)).toEqual(built);
  await expect(page.getByTestId(`node-${id}`)).toContainText("3 classes");
  await expect(page.getByTestId("cm-preview").locator(".gk-class-chip")).toHaveCount(3);

  // each edit is one undo step
  await page.getByTestId("colormap-close").click();
  await page.keyboard.press("Control+z");
  await expect.poll(() => valueOf(page, id)).toEqual({ ...built, other: null });
  // redo once the page has the graph after the undo (it offers redo only then)
  await expect
    .poll(() => page.evaluate(() => window.__geoknit!.getState().graph?.can_redo))
    .toBe(true);
  await page.keyboard.press("Control+y");
  await expect.poll(() => valueOf(page, id)).toEqual(built);

  await api(page, "POST", "/api/workflow/save", { path: "colormap.geoknit" });
  await api(page, "POST", "/api/workflow/open", { path: "colormap.geoknit" });
  await page.reload();
  expect((await graph(page)).path).toBe("colormap.geoknit");
  expect(await valueOf(page, id)).toEqual(built);

  await page.getByTestId(`node-${id}`).dblclick();
  await expect(win.getByTestId(/^cm-class-\d$/)).toHaveCount(3);
  await expect(page.getByTestId("cm-class-label-1")).toHaveValue("Medium");
  await expect(page.getByTestId("cm-class-colour-1-hex")).toHaveValue("#00FF0080");
  await expect(page.getByTestId("cm-other-colour")).toBeChecked();
});

test("a class table pasted into the editor replaces the classes", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/");
  const g = await graph(page);
  const id = Object.keys(g.nodes).find((n) => (g.nodes[n].value as { kind?: string })?.kind);
  expect(id).toBeTruthy();
  await page.getByTestId(`node-${id}`).dblclick();
  await expect(page.getByTestId("colormap-window")).toBeVisible();

  await page.evaluate(() => navigator.clipboard.writeText("1, #FF0000, Built\n2, #00FF00, Green"));
  await page.getByTestId("cm-classes").focus();
  await page.keyboard.press("Control+v");

  await expect(page.getByTestId("colormap-window").getByTestId(/^cm-class-\d$/)).toHaveCount(2);
  await expect(page.getByTestId("cm-class-label-0")).toHaveValue("Built");
  await expect(page.getByTestId("cm-class-label-1")).toHaveValue("Green");
  await expect
    .poll(() => valueOf(page, id!))
    .toEqual({
      kind: "classes",
      classes: [
        [1, "#FF0000", "Built"],
        [2, "#00FF00", "Green"],
      ],
      other: "#808080",
    });
  // no nodes were pasted on the canvas
  expect(Object.keys((await graph(page)).nodes)).toEqual([id]);
});

test("custom stops: a drag is one patch, a click on the bar adds a stop", async ({ page }) => {
  await page.goto("/");
  const g = await graph(page);
  const id = Object.keys(g.nodes)[0];
  await page.getByTestId(`node-${id}`).dblclick();
  await page.getByTestId("cm-kind-continuous").click();
  await page.getByTestId("cm-ramp").selectOption("__custom__");
  const bar = page.getByTestId("cm-stops-bar");
  await expect(bar.getByTestId(/^cm-stop-\d+$/)).toHaveCount(11);

  const patches: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "PATCH" && r.url().includes(`/api/nodes/${id}`)) patches.push(r.postData() ?? "");
  });
  const box = (await bar.boundingBox())!;
  const stop = (await page.getByTestId("cm-stop-0").boundingBox())!;
  await page.mouse.move(stop.x + stop.width / 2, stop.y + stop.height / 2);
  await page.mouse.down();
  for (const f of [0.1, 0.2, 0.3]) await page.mouse.move(box.x + box.width * f, stop.y + 4);
  await page.mouse.up();
  await expect.poll(() => patches.length).toBe(1);
  const value = (await valueOf(page, id)) as { stops: [number, string][] };
  expect(value.stops).toHaveLength(11);
  expect(value.stops.find(([, c]) => c === "#440154")?.[0]).toBeCloseTo(0.3, 1);

  await page.mouse.click(box.x + box.width * 0.95, box.y + 4);
  await expect.poll(() => patches.length).toBe(2);
  await expect(bar.getByTestId(/^cm-stop-\d+$/)).toHaveCount(12);
  await expect(page.getByTestId("cm-stop-pos")).toHaveValue(/^0\.9[45]\d*$/);
});
