// PLAN Phase 8: Export .py from the top bar (SPEC 10).
// Runs on the shared server after the other specs: it clears the canvas first.

import { expect, test, type Page } from "@playwright/test";

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

test("Export .py writes the script next to the workflow and asks before replacing it", async ({
  page,
}) => {
  await page.goto("/");
  const graph = (await api(page, "GET", "/api/graph")) as {
    workflow: { nodes: { id: string }[] };
  };
  await api(page, "POST", "/api/delete", { nodes: graph.workflow.nodes.map((n) => n.id) });
  const text = (await api(page, "POST", "/api/nodes", { component: "param/text" })) as { id: string };
  await api(page, "PATCH", `/api/nodes/${text.id}`, { value: "hello" });
  const panel = (await api(page, "POST", "/api/nodes", { component: "param/panel" })) as {
    id: string;
  };
  await api(page, "POST", "/api/wires", { from: [text.id, "value"], to: [panel.id, "data"] });
  await api(page, "POST", "/api/workflow/save", { path: "exported.geoknit" });
  await page.reload();
  // The export name defaults from the open workflow: wait until the page knows it.
  await expect(page.getByTestId("file-name")).toContainText("exported.geoknit");

  await page.getByTestId("export-py").click();
  await expect(page.getByTestId("export-input")).toHaveValue("exported.py");
  await page.getByTestId("export-ok").click();
  await expect(page.getByTestId("toast")).toContainText("Exported to exported.py");
  await expect(page.getByTestId("export-menu")).toHaveCount(0);

  // A second export asks first; declining keeps the menu open.
  page.once("dialog", (d) => void d.dismiss());
  await page.getByTestId("export-py").click();
  await page.getByTestId("export-ok").click();
  await expect(page.getByTestId("export-menu")).toBeVisible();

  const result = (await api(page, "POST", "/api/export/py", {})) as { script: string };
  expect(result.script).toContain("N01_DATA = 'hello'");
  expect(result.script).toContain(`_panel("${panel.id}", N01_DATA)`);
});
