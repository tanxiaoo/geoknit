# Change 02: Light and dark theme

Status: done (merged into `docs/SPEC.md`, 27 Nov 2026) · Touches `docs/SPEC.md`
sections 3, 8, 9, 12

## Questions for Xiao

None: the decision (light and dark, per user, following the system by
default) fits the code. The corrections below are about how it is built.

---

GeoKnit gets two themes: **light** (today's look) and **dark**. The theme
belongs to the user, not the workflow: opening a colleague's `.geoknit` file
never changes it.

---

## 1. Choosing the theme (SPEC 8, 9)

- Setting `theme`: `system` (default) | `light` | `dark`. `system` follows
  the browser's `prefers-color-scheme` and updates live when the OS switches.
- Stored in `settings.json` in the same folder as `trusted.json` and
  `autosave/` (`~/.geoknit/`, or the folder of `GEOKNIT_TRUST_FILE` /
  `create_app(trust_file=…)`, which the tests already use), as
  `{"theme": "system"}`. A missing or unreadable
  file means the defaults. Unknown keys are kept and written back.
- API: `GET /api/settings` → `{theme}`; `PATCH /api/settings` `{theme}`.
  Not part of undo, never makes anything out of date, allowed during a run
  and on a read-only workflow. Another theme value answers `422` (like any
  invalid request body) and `null` answers `400`; nothing is written.
- Top bar: one button (Lucide `sun-moon`) that cycles System → Light → Dark,
  with a tooltip naming the current choice.
- **No flash before the first paint.** Today the built frontend is served by
  a `StaticFiles` mount at `/` (`server/app.py`), so `index.html` goes out
  unchanged. Two parts:
  - The server gets a route for `/` and `/index.html`, ahead of the mount. It
    writes the saved choice into the page as
    `<html data-theme-setting="dark">`.
  - A small inline script in `frontend/index.html` turns that into
    `data-theme="light|dark"` before any CSS applies, resolving `system`
    with `matchMedia("(prefers-color-scheme: dark)")`. The server cannot
    resolve `system` itself.
  - Under `npm run dev` (Vite serves `index.html`) the attribute is missing.
    The script then falls back to `system`, and the app applies the saved
    choice once `GET /api/settings` answers. A flash in dev mode is
    acceptable.

## 2. Colour tokens (SPEC 8)

All colours come from CSS custom properties in one file,
`frontend/src/theme.css`, with a block per theme:

```css
:root[data-theme="light"] { --gk-canvas-bg: #E5E8EC; … }
:root[data-theme="dark"]  { --gk-canvas-bg: #111827; … }
```

Today `styles.css` already starts with a `:root` block of 13 custom
properties (`--ink`, `--muted`, `--canvas-bg`, `--node-bg`, …). That block is
the start of `theme.css`, but about 120 more lines of `styles.css` still
contain literals.

- No other `.css`, `.ts` or `.tsx` file under `frontend/src` contains a
  colour literal (hex, `rgb()`, `hsl()`, named colour). Two exceptions:
  - test files (`*.test.ts(x)` use colours as data);
  - `frontend/src/palettes.ts`, the one home of **data colours**: the class
    palette and the vector colour choices of the Map Viewer (today in
    `components/map/layers.ts`, matching `PALETTE` in `server/tiles.py`).
    They mean the same in both themes, so they are not theme tokens.

  A vitest test scans `frontend/src` and fails on any literal elsewhere.
  Today's literals outside `styles.css` are in `types.ts` (port and category
  colours), `components/map/layers.ts`, `components/map/MapCanvas.tsx` (map
  background, marker, circle stroke), `components/TypedEdge.tsx` (fallback
  colour, selection glow) and `components/Canvas.tsx` (grid colour).
- Most TypeScript colours can stay in CSS: wire strokes, port dots and the
  React Flow grid accept `var(--gk-…)` in inline styles and props. Only
  MapLibre paint properties need a value. They go through one helper,
  `themeColor(token)` (reads `getComputedStyle`), re-read when the theme
  changes.
- Token groups:
  - surfaces: `app-bg`, `panel-bg`, `canvas-bg`, `canvas-grid`, `node-bg`,
    `node-border`, `topbar-bg`, `map-bg` (the map background for basemap
    `none`);
  - text: `ink`, `muted`, `on-strip`;
  - states: `out-of-date`, `error`, `selected`, `running`;
  - Panel: `panel-note-bg`, `panel-note-ink`, `panel-note-border`;
  - one token per data type (`type-number`, …) and one per category strip
    (`cat-raster`, …);
  - wires: `wire-width`, `wire-faded-opacity`.

  The top bar is navy (`--navy`) in light today and stays dark in both
  themes.

## 3. Palettes

Surfaces and text:

| Token | Light | Dark |
|-------|-------|------|
| app-bg / panel-bg | `#FFFFFF` / `#F8FAFC` | `#0B1220` / `#111827` |
| canvas-bg | `#E5E8EC` | `#111827` |
| canvas-grid | `#D4D8DE` | `#1F2937` |
| node-bg | `#EEF0F3` | `#1E293B` |
| node-border | `#64748B` | `#475569` |
| ink / muted | `#0F172A` / `#64748B` | `#E5E7EB` / `#94A3B8` |
| panel-note-bg / ink | `#FEF6C7` / `#0F172A` | `#3B3416` / `#FDE68A` |
| out-of-date / error / selected | `#D97706` / `#DC2626` / `#16A34A` | `#F59E0B` / `#F87171` / `#4ADE80` |
| map-bg | `#F1F3F4` | `#1F2937` |

The light values are today's (`styles.css`, the grid colour in `Canvas.tsx`,
the map background in `MapCanvas.tsx`), so step 1 changes nothing visible.

Data types (ports and wires). The light values are SPEC 3 plus change 01;
dark values are the lighter shades of the same hues so wires stay visible on
a dark canvas:

| Type | Light | Dark |
|------|-------|------|
| Number | `#64748B` | `#94A3B8` |
| Text | `#A16207` | `#FBBF24` |
| Raster | `#0B7A7C` | `#2DD4BF` |
| Vector | `#C2410C` | `#FB923C` |
| Table | `#7C3AED` | `#A78BFA` |
| Model | `#BE185D` | `#F472B6` |
| Boolean | `#0369A1` | `#38BDF8` |
| Color | `#4D7C0F` | `#A3E635` |
| Colormap | `#4338CA` | `#818CF8` |
| Layer | `#A21CAF` | `#E879F9` |

Category strips keep the **same colours in both themes** (change 01, section
7). They are filled areas with white text, which read well on both
backgrounds, and keeping them identical makes screenshots in the docs valid
for both themes.

Contrast checks (vitest, computed WCAG contrast ratio):

- every type colour against `canvas-bg` and `node-bg` of its theme: ≥ 3:1;
- `ink` and `muted` against `panel-bg`, `node-bg` and `panel-note-bg`:
  ≥ 4.5:1 for `ink`, ≥ 3:1 for `muted`;
- `on-strip` (white) against every category strip colour: ≥ 4.5:1.

If a value above fails, the test decides: adjust the value and update this
table. (Checked by hand for the light strips, including the new Sampling
`#B45309`: all are about 5:1 or more against white.)

## 4. Parts that are not plain CSS

- **Monaco** (Code tab): `vs` in light, `vs-dark` in dark, switched live
  (`monaco.editor.setTheme`).
- **Map Viewer basemap**: the saved basemap gains `auto`, `light`, `dark`,
  `none` (today `light` | `none`, `BASEMAPS` in `server/tiles.py`).
  - `auto` follows the theme and is the default.
  - Today the greying of `light` is done with MapLibre raster paint
    properties (`raster-saturation`, `raster-brightness-min`,
    `raster-contrast` in `MapCanvas.tsx`), not CSS. `dark` uses the same
    OpenStreetMap tiles with paint properties too:
    `raster-brightness-min: 1` and `raster-brightness-max: 0` invert the
    brightness, then `raster-hue-rotate: 180` and a lower saturation. No new
    tile provider and no API key.
  - A CSS filter is not used, because it would also recolour the data layers
    drawn on the same canvas.
  - A map saved without a `basemap` key shows `light` today; after this
    change it shows `auto`. Only a map whose `basemap` was changed has the
    key, so an older map cannot be told apart. Nothing is published, so this
    is accepted. A saved `light` stays `light`.
- **Map Viewer layers** are never recoloured by the theme: a Colormap means
  the same colours in both themes. A vector layer's default colour stays the
  server's default style (`PALETTE[3]`, `#d62728` in `tiles.py`), the same in
  both themes. The basemap-`none` background (`map-bg`), the click marker
  and the point outline are UI and do follow the theme.
- **Icons** use `currentColor` and follow the text colour.
- **Native form controls** (scrollbars, checkboxes, range sliders, select menus) follow
  the theme through `color-scheme: light | dark` in each theme block; text fields and
  selects take their background from the `field-bg` token.
- **Fills with text on them**: white stays on the strips, primary buttons and toasts.
  Where a fill is a light colour in dark (a type colour behind a badge, the slider value,
  the banner buttons) the text uses its own token (`on-type`, `slider-ink`,
  `banner-button-ink`), dark ink in the dark theme and white in light.
- **Panel** keeps its "sticky note" look in dark with the muted yellow above.
- **Screenshots.** `docs/ui/` holds the design mockups, which are not made
  from the app, so they stay as they are. The app screenshots are
  `docs/img/milan/`, made by `npm run screenshots`
  (`frontend/docs-shots/milan.spec.ts`). That script gets a dark pass
  writing `01-opened-dark.png` and `06-map-viewer-dark.png`, and the README
  shows the light and dark main canvas side by side.

## Not in this change

- More themes or user-defined colours.
- High-contrast mode (the contrast tests make it easy to add later).
- Theming exported scripts or written files: they carry no UI colours.
