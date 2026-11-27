// Change 01 step 2 "Done when": dragging a Raster wire onto a [Table, Vector]
// input shows the refusal tooltip. Clears the canvas first (shared server).

import { expect, test, type Page } from "@playwright/test";

const SELECT = `# geoknit: component
# name: Select
# category: Table
# inputs:
#   data: [Table, Vector]
# outputs:
#   selected: {like: data}

# --- code ---
selected = data
`;

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

async function centre(page: Page, testId: string) {
  const box = await page.getByTestId(testId).boundingBox();
  if (!box) throw new Error(`${testId} not visible`);
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

test("a Raster wire dragged onto a [Table, Vector] input is refused with a tooltip", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  const g = (await api(page, "GET", "/api/graph")) as { nodes: Record<string, unknown> };
  await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
  const read = (await api(page, "POST", "/api/nodes", {
    component: "builtin/raster/read_raster",
    position: [100, 100],
  })) as { id: string };
  const sel = (await api(page, "POST", "/api/nodes", {
    component: "inline",
    source: SELECT,
    position: [450, 100],
  })) as { id: string };

  await page.reload(); // show the nodes added through the API
  const input = page.getByTestId(`port-${sel.id}-in-data`);
  await expect(input).toHaveAttribute("data-type", "Table|Vector");

  const a = await centre(page, `port-${read.id}-out-raster`);
  const b = await centre(page, `port-${sel.id}-in-data`);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move((a.x + b.x) / 2, (a.y + b.y) / 2, { steps: 5 });
  await expect(input).toHaveClass(/gk-misfit/);
  await page.mouse.move(b.x, b.y, { steps: 5 });
  await expect(page.getByTestId("tip")).toHaveText("Raster can't connect to Table | Vector");
  await page.mouse.up();
  // dropped anyway: the server refuses it with the same message
  await expect(page.getByTestId("toast")).toHaveText("Raster can't connect to Table | Vector");
  const after = (await api(page, "GET", "/api/graph")) as { workflow: { wires: unknown[] } };
  expect(after.workflow.wires).toHaveLength(0);
});
