// Change 01 step 6 "Done when": clicking a Boolean Toggle flips it, marks downstream out of
// date, and Ctrl+Z restores it. Clears the canvas first (shared server).

import { expect, test, type Page } from "@playwright/test";

const FLIP = `# geoknit: component
# name: Flip
# category: Script
# inputs:
#   flag: Boolean
# outputs:
#   flipped: Boolean

# --- code ---
flipped = not flag
`;

interface Graph {
  workflow: { nodes: { id: string; value?: unknown }[] };
  nodes: Record<string, { state: string; value?: unknown }>;
}

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

async function graph(page: Page): Promise<Graph> {
  return (await api(page, "GET", "/api/graph")) as Graph;
}

test("a Boolean Toggle flips on a click, marks downstream out of date, and Ctrl+Z restores it", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByTestId("worker-status")).toContainText("idle");
  const g = await graph(page);
  await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
  const add = async (body: unknown) =>
    ((await api(page, "POST", "/api/nodes", body)) as { id: string }).id;
  const toggle = await add({ component: "param/toggle", position: [100, 100] });
  const flip = await add({ component: "inline", source: FLIP, position: [400, 100] });
  await api(page, "POST", "/api/wires", { from: [toggle, "value"], to: [flip, "flag"] });

  await page.reload(); // show the nodes added through the API
  const sw = page.getByTestId(`toggle-${toggle}`);
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId(`port-${toggle}-out-value`)).toHaveAttribute("data-type", "Boolean");

  await page.getByTestId("run").click();
  await expect(page.getByTestId(`node-${flip}`)).toHaveAttribute("data-state", "done");

  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "true");
  await expect(sw).toContainText("True");
  await expect(page.getByTestId(`node-${flip}`)).toHaveAttribute("data-state", "out_of_date");
  expect((await graph(page)).nodes[toggle].value).toBe(true);

  await page.keyboard.press("Control+z");
  await expect(sw).toHaveAttribute("aria-checked", "false");
  expect((await graph(page)).nodes[toggle].value).toBe(false);
});
