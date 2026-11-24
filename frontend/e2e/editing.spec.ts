// PLAN Phase 5: save / open, undo / redo, copy / paste, groups, autosave, hover summaries.
// Runs after canvas.spec.ts on the same server, starting from whatever workflow is open.

import { expect, test, type Page } from "@playwright/test";

interface Graph {
  path: string | null;
  dirty: boolean;
  recovery: boolean;
  workflow: {
    nodes: { id: string; component: string; value?: unknown }[];
    wires: { from: [string, string]; to: [string, string] }[];
    groups: { title: string; nodes: string[] }[];
  };
  nodes: Record<string, { state: string }>;
}

async function graph(page: Page): Promise<Graph> {
  return (await page.request.get("/api/graph")).json() as Promise<Graph>;
}

async function nodeCount(page: Page): Promise<number> {
  return (await graph(page)).workflow.nodes.length;
}

/** Edit through the API (as an agent would), then let the page catch up. */
async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  await page.evaluate(() => window.__geoknit?.refreshGraph());
  return res.status() === 204 ? undefined : res.json();
}

function node(page: Page, id: string) {
  return page.locator(`.react-flow__node[data-id="${id}"]`);
}

test.describe.serial("editing", () => {
  let page: Page;
  let text = "";
  const ctrl = "Control";

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("Ctrl+S on a new workflow asks for a name, then saves", async () => {
    expect((await graph(page)).path).toBeNull();
    await page.getByTestId("canvas").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press(`${ctrl}+s`);
    const input = page.getByTestId("save-as-input");
    await expect(input).toBeVisible();
    await input.fill("synthetic");
    await input.press("Enter");
    await expect(page.getByTestId("file-name")).toContainText("synthetic.geoknit");
    await expect(page.getByTestId("save-state")).toContainText("saved");
    await expect(page.getByTestId("file-synthetic.geoknit")).toBeVisible();
    expect((await graph(page)).dirty).toBe(false);
  });

  test("deleting everything is one step: Ctrl+Z brings it all back, Ctrl+Y removes it again", async () => {
    const g = await graph(page);
    const all = g.workflow.nodes.map((n) => n.id);
    await api(page, "POST", "/api/delete", { nodes: all, wires: [] });
    await expect(page.locator(".react-flow__node")).toHaveCount(0);
    await expect(page.getByTestId("save-state")).toContainText("unsaved changes");

    await page.keyboard.press(`${ctrl}+z`);
    await expect.poll(() => nodeCount(page)).toBe(all.length);
    await expect(page.locator(".react-flow__node")).toHaveCount(all.length);
    expect((await graph(page)).workflow.wires).toEqual(g.workflow.wires);
    await expect(page.getByTestId("save-state")).toContainText("saved");

    await page.getByTestId("redo").click();
    await expect.poll(() => nodeCount(page)).toBe(0);
  });

  test("copy, paste at the pointer, group, rename, ungroup, delete and undo", async () => {
    const added = (await api(page, "POST", "/api/nodes", {
      component: "param/text",
      position: [100, 100],
    })) as { id: string };
    text = added.id;
    await api(page, "PATCH", `/api/nodes/${text}`, { value: "abc" });

    await node(page, text).click();
    await page.keyboard.press(`${ctrl}+c`);
    const box = (await node(page, text).boundingBox())!;
    await page.mouse.move(box.x + 40, box.y + 160);
    await page.keyboard.press(`${ctrl}+v`);
    await expect.poll(() => nodeCount(page)).toBe(2);
    const copy = (await graph(page)).workflow.nodes.find((n) => n.id !== text)!;
    expect(copy.value).toBe("abc");
    await expect(node(page, copy.id)).toHaveClass(/selected/); // the pasted node is selected

    await node(page, text).click({ modifiers: [ctrl] });
    await page.keyboard.press(`${ctrl}+g`);
    await expect(page.getByTestId("group-0")).toBeVisible();
    await expect(page.getByTestId("group-title-0")).toHaveText("Group");
    expect((await graph(page)).workflow.groups[0].nodes.sort()).toEqual([text, copy.id].sort());

    await page.getByTestId("group-title-0").dblclick();
    await page.getByTestId("group-title-input-0").fill("Inputs");
    await page.getByTestId("group-title-input-0").press("Enter");
    await expect(page.getByTestId("group-title-0")).toHaveText("Inputs");

    await page.getByTestId("group-title-0").click({ button: "right" });
    await page.getByTestId("menu-ungroup").click();
    await expect(page.getByTestId("group-0")).toHaveCount(0);

    await page.getByTestId("canvas").click({ position: { x: 5, y: 5 } }); // clear the selection
    await node(page, text).click();
    await node(page, copy.id).click({ modifiers: [ctrl] });
    await page.keyboard.press("Delete");
    await expect.poll(() => nodeCount(page)).toBe(0);
    await page.getByTestId("undo").click();
    await expect.poll(() => nodeCount(page)).toBe(2);
    await page.keyboard.press(`${ctrl}+z`); // the ungroup
    await expect(page.getByTestId("group-title-0")).toHaveText("Inputs");
  });

  test("hovering a port or a wire shows what it carries after a run", async () => {
    const panel = (await api(page, "POST", "/api/nodes", {
      component: "param/panel",
      position: [400, 100],
    })) as { id: string };
    await api(page, "POST", "/api/wires", { from: [text, "value"], to: [panel.id, "data"] });

    await page.getByTestId(`port-${panel.id}-in-data`).hover();
    await expect(page.getByTestId("tip")).toContainText("run to see");

    await api(page, "POST", "/api/run", { mode: "to_node", node_id: panel.id });
    await expect.poll(async () => (await graph(page)).nodes[panel.id].state).toBe("done");
    await expect(page.getByTestId(`panel-text-${panel.id}`)).toContainText("abc");

    await page.mouse.move(5, 5);
    await expect(page.getByTestId("tip")).toHaveCount(0);
    await page.getByTestId(`port-${text}-out-value`).hover();
    await expect(page.getByTestId("tip")).toContainText("value: Text");
    await expect(page.getByTestId("tip")).toContainText("abc");
    await expect(page.getByTestId("tip")).not.toContainText("run to see");

    const edge = page.getByTestId(`wire-${text}.value>${panel.id}.data`);
    const path = edge.locator("path").first();
    const b = (await path.boundingBox())!;
    await page.mouse.move(5, 5);
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await expect(page.getByTestId("tip")).toContainText("value → data");
  });

  test("reopening with unsaved changes offers the autosave, and Restore brings them back", async () => {
    const before = await graph(page);
    expect(before.dirty).toBe(true);
    page.once("dialog", (d) => void d.accept()); // "Discard the unsaved changes…?"
    await page.getByTestId("file-name").click();
    await page.getByTestId("menu-open-synthetic.geoknit").click();
    await expect(page.getByTestId("recovery")).toBeVisible();
    await expect.poll(() => nodeCount(page)).not.toBe(before.workflow.nodes.length);

    await page.getByTestId("recovery-restore").click();
    await expect(page.getByTestId("recovery")).toHaveCount(0);
    const after = await graph(page);
    expect(after.workflow.nodes).toEqual(before.workflow.nodes);
    expect(after.workflow.groups).toEqual(before.workflow.groups);
    await expect(page.getByTestId("save-state")).toContainText("unsaved changes");

    await page.keyboard.press(`${ctrl}+s`);
    await expect(page.getByTestId("save-state")).toContainText("saved");
    expect((await graph(page)).recovery).toBe(false);
  });
});
