// Data colours (change 02, SPEC 8): colours that mean the same in both themes, so they are
// not theme tokens. The only .ts file besides tests allowed to hold colour literals
// (src/colourLiterals.test.ts); UI colours live in theme.css.

/** A vector layer's default colour: the server's default style (`PALETTE[3]` in
 * `server/tiles.py`). */
export const DEFAULT_VECTOR_COLOUR = "#d62728";

/** Swatches offered for vector layers in the Map Viewer. */
export const VECTOR_COLOURS = [
  "#d62728",
  "#1f77b4",
  "#2ca02c",
  "#ff7f0e",
  "#9467bd",
  "#111827",
  "#e377c2",
  "#17becf",
];

/** What a Color Swatch shows and its picker starts from when the value is not a hex colour. */
export const FALLBACK_COLOR_VALUE = "#000000";

/** Colours the Colormap editor gives new classes, in turn (change 03, section 2). */
export const NEW_CLASS_COLOURS = [
  "#1F77B4",
  "#FF7F0E",
  "#2CA02C",
  "#D62728",
  "#9467BD",
  "#8C564B",
  "#E377C2",
  "#17BECF",
];

/** The colour "Other values" starts from when it stops being transparent. */
export const DEFAULT_OTHER_COLOUR = "#808080";

/** What a vector feature gets for "other values" of a transparent classes Colormap, and when
 * its field has no number (Map Viewer colour by field, change 03). */
export const TRANSPARENT = "rgba(0, 0, 0, 0)";

/** A colour MapLibre reads: `#RRGGBBAA` becomes `rgba(r, g, b, a)`, the rest is kept. */
export function cssColour(hex: string): string {
  const m = /^#([0-9a-fA-F]{6})([0-9a-fA-F]{2})$/.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const a = Number((parseInt(m[2], 16) / 255).toFixed(3));
  return "rgba(" + [(n >> 16) & 255, (n >> 8) & 255, n & 255, a].join(", ") + ")";
}
