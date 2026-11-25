// PLAN Phase 6 "Done when" (component window):
// 1. change n_trees in Settings → the Code tab shows the new value, and the reverse;
// 2. break the code → Output shows the traceback with the right line; a broken settings
//    block → the Settings tab shows the parse error;
// 3. edit Reclassify's code, save the workflow, reopen: the edit is still there and the
//    node shows "modified".
// Runs last on the shared server (after editing.spec.ts); it clears the canvas first.

import { expect, test, type Page } from "@playwright/test";

interface NodeView {
  id: string;
  component: string;
  source?: string;
  modified?: boolean;
  parse_error?: string | null;
  inputs: { name: string; type: string }[];
}
interface Graph {
  path: string | null;
  nodes: Record<string, NodeView>;
  workflow: { nodes: { id: string; component: string }[] };
}

async function graph(page: Page): Promise<Graph> {
  return (await page.request.get("/api/graph")).json() as Promise<Graph>;
}

async function api(page: Page, method: string, path: string, data?: unknown): Promise<unknown> {
  const res = await page.request.fetch(path, { method, data });
  expect(res.ok(), await res.text()).toBeTruthy();
  return res.status() === 204 ? undefined : res.json();
}

async function add(page: Page, component: string, position: [number, number]): Promise<string> {
  const node = (await api(page, "POST", "/api/nodes", { component, position })) as { id: string };
  return node.id;
}

function node(page: Page, id: string) {
  return page.locator(`.react-flow__node[data-id="${id}"]`);
}

const editorText = (page: Page) => page.evaluate(() => window.__geoknitEditor?.getValue() ?? "");

async function setEditorText(page: Page, text: string): Promise<void> {
  await page.waitForFunction(() => !!window.__geoknitEditor); // Monaco mounts asynchronously
  await page.evaluate((t) => window.__geoknitEditor?.setValue(t), text);
}

const BROKEN = `# geoknit: component
# name: Python
# category: Script
# outputs:
#   out: Text

# --- settings ---

# --- code ---
print("before the error")
raise ValueError("broken on purpose")
`;

test.describe.serial("component window", () => {
  let page: Page;
  let rf = "";
  let rc = "";
  let py = "";

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto("/");
    await expect(page.getByTestId("worker-status")).toContainText("idle");
    const g = await graph(page);
    await api(page, "POST", "/api/delete", { nodes: Object.keys(g.nodes), wires: [] });
    rf = await add(page, "builtin/model/random_forest", [0, 0]);
    rc = await add(page, "builtin/raster/reclassify", [300, 0]);
    py = await add(page, "builtin/script/python", [600, 0]);
    await page.reload(); // fit the view to the new nodes
    await expect(node(page, py)).toBeVisible();
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("n_trees in Settings shows up in the Code tab, and the reverse", async () => {
    await node(page, rf).dblclick();
    const win = page.getByTestId("component-window");
    await expect(win).toBeVisible();
    await expect(page.getByTestId("window-title")).toHaveText("Random Forest");

    const field = page.getByTestId("setting-n_trees");
    await field.fill("500");
    await field.press("Enter");
    await expect
      .poll(async () => (await graph(page)).nodes[rf].source)
      .toContain("n_trees = 500  #");

    await page.getByTestId("window-tab-code").click();
    await expect.poll(() => editorText(page)).toContain("n_trees = 500  # range: 1..5000");

    const code = await editorText(page);
    await setEditorText(page, code.replace("n_trees = 500", "n_trees = 900"));
    await page.getByTestId("window-tab-settings").click();
    await expect(page.getByTestId("setting-n_trees")).toHaveValue("900");
    expect((await graph(page)).nodes[rf].source).toContain("n_trees = 900  # range: 1..5000");

    // a settings change is not a code change: the node is not "modified"
    await expect(page.getByTestId(`modified-${rf}`)).toHaveCount(0);
    await page.getByTestId("window-ok").click();
    await expect(win).toHaveCount(0);
  });

  test("broken code: Test shows the traceback with the line in the component file", async () => {
    await node(page, py).dblclick();
    await page.getByTestId("window-tab-code").click();
    await expect.poll(() => editorText(page)).toContain("# geoknit: component");
    await setEditorText(page, BROKEN);
    await page.getByTestId("window-test").click();

    const output = page.getByTestId("output");
    await expect(page.getByTestId("output-error")).toContainText("line 11");
    await expect(page.getByTestId("output-error")).toContainText("ValueError: broken on purpose");
    await expect(output).toContainText("before the error");
    await expect(page.getByTestId("output-state")).toContainText("Failed");
    await expect(page.getByTestId(`node-${py}`)).toHaveAttribute("data-state", "error");
  });

  test("a broken settings block: the Settings tab shows the parse error", async () => {
    const broken = BROKEN.replace("# --- settings ---\n", "# --- settings ---\nband = [1,\n");
    await setEditorText(page, broken);
    await page.getByTestId("window-tab-settings").click();
    await expect(page.getByTestId("settings-parse-error")).toContainText("settings block");
    await expect(page.getByTestId("settings-tab").locator("fieldset")).toHaveAttribute(
      "disabled",
      "",
    );
    await expect(page.getByTestId("add-input")).toBeDisabled();

    // fix it: the Settings tab comes back
    await page.getByTestId("window-tab-code").click();
    await setEditorText(page, BROKEN.replace('raise ValueError("broken on purpose")\n', "a = 1\n"));
    await page.getByTestId("window-tab-settings").click();
    await expect(page.getByTestId("settings-parse-error")).toHaveCount(0);
  });

  test("Python component: add, rename and retype ports from the Settings tab", async () => {
    await page.getByTestId("add-input").click();
    await expect(page.getByTestId("port-name-x1")).toBeVisible();
    await page.getByTestId("port-name-x1").fill("raster");
    await page.getByTestId("port-name-x1").press("Enter");
    await expect(page.getByTestId("port-type-raster")).toBeVisible();
    await page.getByTestId("port-type-raster").selectOption("Raster");
    await expect
      .poll(async () => (await graph(page)).nodes[py].inputs)
      .toEqual([{ name: "raster", type: "Raster", access: "item", file: null }]);
    await expect(node(page, py)).toContainText("raster");

    await page.getByTestId("window-tab-code").click();
    await expect.poll(() => editorText(page)).toContain("# inputs:\n#   raster: Raster\n");
  });

  test("Save as component… puts it in the ribbon as a user component", async () => {
    await page.getByTestId("window-tab-code").click();
    const code = await editorText(page);
    await setEditorText(page, code.replace("# name: Python", "# name: Band Peek"));
    await page.getByTestId("save-component").click();
    await expect(page.getByTestId("toast")).toContainText("user/script/band_peek");
    await page.getByTestId("window-ok").click();
    await page.getByTestId("tab-Script").click();
    await expect(page.getByTestId("ribbon-user/script/band_peek")).toContainText("user component");
  });

  test("an edited Reclassify is still edited and 'modified' after save and reopen", async () => {
    await node(page, rc).dblclick();
    await page.getByTestId("window-tab-code").click();
    await expect.poll(() => editorText(page)).toContain("# name: Reclassify");
    const code = await editorText(page);
    const edited = code.replace("import numpy as np", "import numpy as np  # edited in GeoKnit");
    await setEditorText(page, edited);
    await page.getByTestId("window-ok").click();
    await expect(page.getByTestId(`modified-${rc}`)).toBeVisible();

    await api(page, "POST", "/api/workflow/save", { path: "window.geoknit" });
    await api(page, "POST", "/api/workflow/open", { path: "window.geoknit" });
    await page.reload();

    const g = await graph(page);
    expect(g.path).toBe("window.geoknit");
    expect(g.nodes[rc].source).toBe(edited);
    expect(g.nodes[rc].modified).toBe(true);
    expect(g.workflow.nodes.find((n) => n.id === rc)?.component).toBe("inline");
    await expect(page.getByTestId(`modified-${rc}`)).toBeVisible();

    await node(page, rc).dblclick();
    await expect(page.getByTestId("component-window")).toContainText("modified");
    await page.getByTestId("window-tab-code").click();
    await expect.poll(() => editorText(page)).toContain("# edited in GeoKnit");
  });
});
