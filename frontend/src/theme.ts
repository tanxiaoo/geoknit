// Theme tokens for code that needs a colour value rather than a CSS `var()`, and the
// user's theme setting (change 02).

import { useSyncExternalStore } from "react";
import type { Settings } from "./apiTypes";

/** The current value of a theme.css token (`"--gk-map-bg"` or `"map-bg"`), for MapLibre
 * paint properties, which cannot resolve CSS custom properties. Read it again when the
 * theme changes (see useTheme). */
export function themeColor(token: string): string {
  const name = token.startsWith("--") ? token : `--gk-${token}`;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export type Theme = "light" | "dark";

/** The user's choice (`GET /api/settings`): `system` follows `prefers-color-scheme`. */
export type ThemeSetting = Settings["theme"];

/** The order of the top-bar button. */
export const THEME_SETTINGS: readonly ThemeSetting[] = ["system", "light", "dark"];

const DARK_QUERY = "(prefers-color-scheme: dark)";

function darkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
}

/** A value as the server or the page holds it; anything else (or nothing) means `system`. */
export function parseThemeSetting(value: unknown): ThemeSetting {
  return value === "light" || value === "dark" ? value : "system";
}

/** The theme a setting gives. The inline script of index.html does the same before the
 * first paint; keep the two in step. */
export function resolveTheme(setting: ThemeSetting, systemDark = !!darkQuery()?.matches): Theme {
  if (setting === "system") return systemDark ? "dark" : "light";
  return setting;
}

/** The setting after this one: System → Light → Dark → System. */
export function nextThemeSetting(setting: ThemeSetting): ThemeSetting {
  return THEME_SETTINGS[(THEME_SETTINGS.indexOf(setting) + 1) % THEME_SETTINGS.length];
}

/** The setting the page was served with (`data-theme-setting` on `<html>`). */
export function pageThemeSetting(): ThemeSetting {
  return parseThemeSetting(document.documentElement.getAttribute("data-theme-setting"));
}

let stopFollowing: (() => void) | null = null;

/** Apply a setting to `<html>`: `data-theme-setting` and `data-theme`. With `system`,
 * `data-theme` follows the OS live (matchMedia change events). */
export function applyThemeSetting(setting: ThemeSetting): void {
  const root = document.documentElement;
  stopFollowing?.();
  stopFollowing = null;
  root.setAttribute("data-theme-setting", setting);
  root.setAttribute("data-theme", resolveTheme(setting));
  const mq = setting === "system" ? darkQuery() : null;
  if (mq) {
    const onChange = (e: MediaQueryListEvent) =>
      root.setAttribute("data-theme", resolveTheme("system", e.matches));
    mq.addEventListener("change", onChange);
    stopFollowing = () => mq.removeEventListener("change", onChange);
  }
}

/** The current theme: `data-theme` on `<html>` (no attribute means light). */
export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

/** The current theme; re-renders when the `data-theme` attribute of `<html>` changes. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}
