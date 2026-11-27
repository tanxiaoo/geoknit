// Theme tokens for code that needs a colour value rather than a CSS `var()` (change 02).

/** The current value of a theme.css token (`"--gk-map-bg"` or `"map-bg"`), for MapLibre
 * paint properties, which cannot resolve CSS custom properties. Read it again when the
 * theme changes. */
export function themeColor(token: string): string {
  const name = token.startsWith("--") ? token : `--gk-${token}`;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
