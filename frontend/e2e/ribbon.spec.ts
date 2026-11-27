// Change 01 step 5 "Done when": the Raster tab shows its groups in layout order
// (geoknit/components/builtin/_layout.yaml), each labelled, and search shows
// "Tab › Group". Read-only: it does not touch the shared server's workflow.

import { expect, test } from "@playwright/test";

interface Tab {
  name: string;
  colour: string;
  groups: string[];
}

test("the Raster tab shows its groups in layout order", async ({ page }) => {
  await page.goto("/");
  const res = await page.request.get("/api/components");
  expect(res.ok()).toBeTruthy();
  const { tabs } = (await res.json()) as { tabs: Tab[] };
  const raster = tabs.find((t) => t.name === "Raster");
  expect(raster?.groups).toEqual(["Files", "Bands", "Calculate", "Extent"]);

  // tabs in the fixed order (allTextContents does not wait: wait for the ribbon first)
  await expect(page.getByTestId("tab-Raster")).toBeVisible();
  const names = await page.locator(".gk-tab").allTextContents();
  expect(names.slice(0, 3)).toEqual(["Params", "Vector", "Raster"]);

  await page.getByTestId("tab-Raster").click();
  await expect(page.locator(".gk-ribbon-group-label")).toHaveText(["Files", "Bands", "Calculate", "Extent"]);
  await expect(page.getByTestId("ribbon-group-Files").locator(".gk-component-button")).toHaveText([
    "Read Raster",
    "Write Raster",
  ]);
  await expect(page.getByTestId("ribbon-group-Extent").locator(".gk-component-button")).toHaveText([
    "Clip",
    "Align Raster",
  ]);
  // the centre-strip colour comes from the tabs answer
  await expect(
    page.getByTestId("ribbon-builtin/raster/clip").locator(".gk-button-icon"),
  ).toHaveCSS("color", "rgb(11, 122, 124)");
  // Change 01 step 7: a vendored Font-GIS icon, drawn inline in currentColor.
  const legend = page
    .getByTestId("ribbon-builtin/raster/reclassify")
    .locator('[data-icon="gis:map-legend"] svg');
  await expect(legend).toHaveAttribute("fill", "currentColor");
  await expect(legend).toHaveCSS("color", "rgb(11, 122, 124)");
  const box = await legend.boundingBox();
  expect(box?.width).toBe(16);

  await page.getByTestId("ribbon-search").fill("align");
  await expect(page.locator(".gk-search-results")).toContainText("Align Raster Raster › Extent");
});
