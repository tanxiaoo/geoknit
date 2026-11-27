// Change 02 step 3: the theme setting. The top-bar button saves it (`PATCH /api/settings`),
// the server writes it into the page (`data-theme-setting` on <html>) and the inline script
// of index.html turns it into `data-theme` before the first paint: checked by recording
// the attribute in a DOMContentLoaded listener registered before any page script runs.
// `system` follows the emulated prefers-color-scheme, also live.

import { expect, test, type Page } from "@playwright/test";

declare global {
  interface Window {
    __themeAtDomContentLoaded?: string | null;
    __themeAtStylesheet?: string | null;
  }
}

async function saveTheme(page: Page, theme: string): Promise<void> {
  const res = await page.request.patch("/api/settings", { data: { theme } });
  expect(res.ok(), await res.text()).toBeTruthy();
}

/** Record `data-theme` as it is when DOMContentLoaded fires and when the parser reaches the
 * stylesheet (before the app's own script has run), on every load of the page. */
async function recordFirstTheme(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const theme = () => document.documentElement.getAttribute("data-theme");
    new MutationObserver((records, observer) => {
      for (const r of records) {
        for (const n of r.addedNodes) {
          if (n instanceof HTMLLinkElement && n.rel === "stylesheet") {
            window.__themeAtStylesheet = theme();
            observer.disconnect();
            return;
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
    document.addEventListener("DOMContentLoaded", () => {
      window.__themeAtDomContentLoaded = theme();
    });
  });
}

const firstTheme = async (page: Page) => {
  const seen = await page.evaluate(() => [
    window.__themeAtStylesheet,
    window.__themeAtDomContentLoaded,
  ]);
  expect(seen[0], "data-theme when the stylesheet is parsed").toBe(seen[1]);
  return seen[1];
};

test.describe.serial("theme setting", () => {
  test.afterAll(async ({ request }) => {
    await request.patch("/api/settings", { data: { theme: "system" } });
  });

  test("the page resolves the theme before any stylesheet", async ({ request }) => {
    await request.patch("/api/settings", { data: { theme: "dark" } });
    const html = await (await request.get("/")).text();
    expect(html).toContain('data-theme-setting="dark"');
    const script = html.indexOf('root.setAttribute("data-theme"');
    const css = html.indexOf('rel="stylesheet"');
    expect(script).toBeGreaterThan(0);
    expect(css).toBeGreaterThan(script);
  });

  test("choose Dark in the top bar, reload: dark from the first paint", async ({ page }) => {
    await saveTheme(page, "system");
    await recordFirstTheme(page);
    await page.goto("/");
    const button = page.getByTestId("theme-toggle");
    await expect(button).toHaveAttribute("title", /System/);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light"); // emulated light

    await button.click();
    await expect(button).toHaveAttribute("title", /Light/);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await button.click();
    await expect(button).toHaveAttribute("title", /Dark/);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const saved = async () => {
      const res = await page.request.get("/api/settings");
      return ((await res.json()) as { theme: string }).theme;
    };
    await expect.poll(saved).toBe("dark");

    await page.reload();
    expect(await firstTheme(page)).toBe("dark");
    await expect(page.locator("html")).toHaveAttribute("data-theme-setting", "dark");
    await expect(page.getByTestId("theme-toggle")).toHaveAttribute("title", /Dark/);

    await button.click(); // Dark → System
    await expect(button).toHaveAttribute("title", /System/);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });

  test("system follows prefers-color-scheme: dark, and changes live", async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: "dark" });
    const page = await context.newPage();
    try {
      await saveTheme(page, "system");
      await recordFirstTheme(page);
      await page.goto("/");
      expect(await firstTheme(page)).toBe("dark");
      await expect(page.getByTestId("theme-toggle")).toHaveAttribute("title", /System/);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

      await page.emulateMedia({ colorScheme: "light" });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
      await page.emulateMedia({ colorScheme: "dark" });
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    } finally {
      await context.close();
    }
  });
});
