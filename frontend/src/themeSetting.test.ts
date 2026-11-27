// Change 02 step 3: the theme setting, applied to <html>, saved through the API, and the
// inline script of index.html giving the same result as resolveTheme().

import { readFileSync } from "node:fs";
import { cwd } from "node:process";
import { createElement } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { Api } from "./api";
import { TopBar } from "./components/TopBar";
import { Store, store } from "./store";
import { strings } from "./strings";
import {
  applyThemeSetting,
  nextThemeSetting,
  pageThemeSetting,
  resolveTheme,
  type ThemeSetting,
} from "./theme";

/** A fake `matchMedia` whose dark preference can be switched, like the OS. */
function fakeSystem(dark: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  const mq = {
    get matches() {
      return dark;
    },
    addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) =>
      listeners.delete(fn),
  };
  window.matchMedia = vi.fn(() => mq as unknown as MediaQueryList);
  return {
    listeners,
    set(value: boolean) {
      dark = value;
      listeners.forEach((fn) => fn({ matches: value } as MediaQueryListEvent));
    },
  };
}

const root = document.documentElement;
const original = window.matchMedia;

afterEach(() => {
  applyThemeSetting("light"); // stop following a fake system
  window.matchMedia = original;
  root.removeAttribute("data-theme");
  root.removeAttribute("data-theme-setting");
});

describe("theme setting", () => {
  test("resolves system with the OS preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  test("the button cycles System → Light → Dark", () => {
    expect(nextThemeSetting("system")).toBe("light");
    expect(nextThemeSetting("light")).toBe("dark");
    expect(nextThemeSetting("dark")).toBe("system");
  });

  test("the page's setting: missing or unknown means system", () => {
    expect(pageThemeSetting()).toBe("system");
    root.setAttribute("data-theme-setting", "dark");
    expect(pageThemeSetting()).toBe("dark");
    root.setAttribute("data-theme-setting", "purple");
    expect(pageThemeSetting()).toBe("system");
  });

  test("system follows the OS live; a fixed choice does not", () => {
    const os = fakeSystem(false);
    applyThemeSetting("system");
    expect(root.dataset.themeSetting).toBe("system");
    expect(root.dataset.theme).toBe("light");
    os.set(true);
    expect(root.dataset.theme).toBe("dark");

    applyThemeSetting("light");
    expect(root.dataset.theme).toBe("light");
    expect(os.listeners.size).toBe(0);
    os.set(false);
    os.set(true);
    expect(root.dataset.theme).toBe("light");
  });

  test("works without matchMedia (light)", () => {
    // @ts-expect-error: jsdom may have none
    window.matchMedia = undefined;
    applyThemeSetting("system");
    expect(root.dataset.theme).toBe("light");
  });
});

describe("index.html inline script", () => {
  const html = readFileSync(`${cwd()}/index.html`, "utf-8");
  const script = /<head>[\s\S]*?<script>([\s\S]*?)<\/script>[\s\S]*?<\/head>/.exec(html)?.[1];

  const cases: [string | null, boolean][] = [
    [null, false],
    [null, true],
    ["system", true],
    ["system", false],
    ["light", true],
    ["dark", false],
    ["purple", true],
  ];
  test.each(cases)("setting %s, system dark %s: same as resolveTheme", (setting, dark) => {
    expect(script).toBeTruthy();
    fakeSystem(dark);
    root.removeAttribute("data-theme");
    if (setting === null) root.removeAttribute("data-theme-setting");
    else root.setAttribute("data-theme-setting", setting);
    new Function(script!)();
    const parsed: ThemeSetting = setting === "light" || setting === "dark" ? setting : "system";
    expect(root.dataset.theme).toBe(resolveTheme(parsed, dark));
  });
});

describe("store", () => {
  function api(theme: ThemeSetting = "dark") {
    return {
      settings: vi.fn(async () => ({ theme })),
      patchSettings: vi.fn(async (p: { theme: ThemeSetting }) => p),
    };
  }

  test("startup applies the saved setting", async () => {
    fakeSystem(false);
    const fake = api("dark");
    const s = new Store(fake as unknown as Api);
    await s.loadSettings();
    expect(s.getState().theme).toBe("dark");
    expect(root.dataset.theme).toBe("dark");
    expect(root.dataset.themeSetting).toBe("dark");
  });

  test("choosing a theme applies it at once and saves it", async () => {
    fakeSystem(true);
    const fake = api("light");
    const s = new Store(fake as unknown as Api);
    await s.setTheme("system");
    expect(fake.patchSettings).toHaveBeenCalledWith({ theme: "system" });
    expect(s.getState().theme).toBe("system");
    expect(root.dataset.theme).toBe("dark");
  });

  test("fast clicks save in click order, one PATCH at a time", async () => {
    fakeSystem(false);
    const fake = api("system");
    const started: ThemeSetting[] = [];
    let release: () => void = () => {};
    fake.patchSettings.mockImplementation(async (p: { theme: ThemeSetting }) => {
      started.push(p.theme);
      if (started.length === 1) await new Promise<void>((r) => (release = r)); // slow first PATCH
      return p;
    });
    const s = new Store(fake as unknown as Api);
    const first = s.setTheme("light");
    const second = s.setTheme("dark");
    await Promise.resolve();
    expect(started).toEqual(["light"]); // the second waits for the first
    release();
    await Promise.all([first, second]);
    expect(started).toEqual(["light", "dark"]);
    expect(root.dataset.theme).toBe("dark");
  });

  test("the top-bar button names the current choice and moves to the next", async () => {
    fakeSystem(false);
    const fake = api();
    const save = vi.spyOn(store, "setTheme").mockImplementation(async (t) => {
      store.set({ theme: t });
      await fake.patchSettings({ theme: t });
    });
    store.set({ theme: "system" });
    render(createElement(TopBar));
    const button = screen.getByTestId("theme-toggle");
    expect(button.getAttribute("title")).toBe(strings.themeHint(strings.themeNames.system));
    fireEvent.click(button);
    expect(save).toHaveBeenCalledWith("light");
    expect(screen.getByTestId("theme-toggle").getAttribute("title")).toBe(
      strings.themeHint(strings.themeNames.light),
    );
    save.mockRestore();
  });
});
