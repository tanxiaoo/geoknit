// Theme tokens for code that needs a colour value rather than a CSS `var()` (change 02).

import { useSyncExternalStore } from "react";

/** The current value of a theme.css token (`"--gk-map-bg"` or `"map-bg"`), for MapLibre
 * paint properties, which cannot resolve CSS custom properties. Read it again when the
 * theme changes (see useTheme). */
export function themeColor(token: string): string {
  const name = token.startsWith("--") ? token : `--gk-${token}`;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export type Theme = "light" | "dark";

/** The theme in force: `data-theme` on `<html>` (no attribute means light). */
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
