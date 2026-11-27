// Change 01 step 3: a component returning a list has a double-line port and wire, a list
// dragged onto an item input is refused, and a Panel shows the list. Clears the canvas
// first (shared server).

import { expect, test, type Page } from "@playwright/test";

const NUMBERS = `# geoknit: component
# name: Numbers
# category: Script
# outputs:
#   values: {type: Number, access: list}

# --- code ---
values = [3, 1, 2]
`;

const SUM = `# geoknit: component
# name: Sum
# category: Script
# inputs:
#   x: Number
# outputs:
#   total: Number

# --- code ---
total = x
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

test("a list output is a double line, refused by an item input, shown by a Panel", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  const g = (await api(page, "GET", "/api/graph")) as { nodes: Record<string, unknown> };
  await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
  const add = async (body: unknown) =>
    ((await api(page, "POST", "/api/nodes", body)) as { id: string }).id;
  const nums = await add({ component: "inline", source: NUMBERS, position: [100, 100] });
  const sum = await add({ component: "inline", source: SUM, position: [450, 100] });
  const panel = await add({ component: "param/panel", position: [450, 300] });
  await api(page, "POST", "/api/wires", { from: [nums, "values"], to: [panel, "data"] });

  await page.reload(); // show the nodes added through the API
  const out = page.getByTestId(`port-${nums}-out-values`);
  await expect(out).toHaveAttribute("data-access", "list");
  await expect(page.getByTestId(`port-${sum}-in-x`)).toHaveAttribute("data-access", "item");
  await expect(page.getByTestId(`port-${panel}-out-data`)).toHaveAttribute("data-access", "list");
  const wire = page.getByTestId(`wire-${nums}.values>${panel}.data`);
  await expect(wire).toHaveAttribute("data-access", "list");

  // drag the list onto Sum's item input: refused while dragging and by the server
  const message = 'Numbers gives a list; "x" takes one value — use List Item';
  const input = page.getByTestId(`port-${sum}-in-x`);
  const a = await centre(page, `port-${nums}-out-values`);
  const b = await centre(page, `port-${sum}-in-x`);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move((a.x + b.x) / 2, (a.y + b.y) / 2, { steps: 5 });
  await expect(input).toHaveClass(/gk-misfit/);
  await page.mouse.move(b.x, b.y, { steps: 5 });
  await expect(page.getByTestId("tip")).toHaveText(message);
  await page.mouse.up();
  await expect(page.getByTestId("toast")).toHaveText(message);

  // the Panel shows the list after a run: one row per element with its index
  await page.getByTestId("run").click();
  await expect(page.getByTestId(`panel-header-${panel}`)).toHaveText("list of 3 Number");
  const rows = page.getByTestId(`panel-list-${panel}`).locator("tr");
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0).locator("th, td")).toHaveText(["0", "3"]);
  await expect(rows.nth(2).locator("th, td")).toHaveText(["2", "2"]);
});
