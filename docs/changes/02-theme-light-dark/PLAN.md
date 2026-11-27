# Change 02 plan: Light and dark theme

Read `CLAUDE.md`, `docs/SPEC.md` and `docs/changes/02-theme-light-dark/SPEC.md`
before each step. Step 1 can start before change 01; step 2 needs change 01's
type list (and its category colours, which come from `GET /api/components`
after change 01 step 5).

---

## Step 1: Tokens, no visible change

- [x] Before touching any colour: add a Playwright screenshot test
      (`toHaveScreenshot`) of the synthetic workflow's canvas, component
      window and map window, and commit its baselines. None exist today: the
      e2e and docs-shots screenshots are written to files, never compared.
      Font rendering differs between Windows and Linux, so the comparison
      runs on one platform (the CI Linux job) with Linux baselines.
- [x] `frontend/src/theme.css` with the light palette, starting from the
      `:root` block of `styles.css`; `styles.css` and the TS files read every
      UI colour from tokens; map data colours moved to `palettes.ts`;
      `themeColor()` helper for MapLibre
- [x] vitest: no colour literal outside `theme.css`, `palettes.ts`, test files
      and vendored SVGs

**Done when:**
- the colour-literal test passes
- the screenshot test passes against the baselines from the first commit
  (pixel diff below the Playwright default threshold)

## Step 2: Dark palette and contrast tests

- [x] Dark block in `theme.css` with the SPEC tables, including the change 01
      types
- [x] vitest contrast tests (types ≥ 3:1, ink ≥ 4.5:1, muted ≥ 3:1, strip
      text ≥ 4.5:1), reading the values from `theme.css`
- [x] Monaco `vs-dark`, Panel dark note, icons via `currentColor`

**Done when:**
- contrast tests pass for both themes
- Playwright: with `data-theme="dark"` the synthetic workflow is readable;
  you review the screenshot and add a dark baseline to the step 1 test

## Step 3: Setting, API, toggle

- [x] `settings.json` next to the trust file, read/write (unknown keys kept);
      `GET/PATCH /api/settings`
- [x] Server route for `/` and `/index.html` ahead of the static mount,
      writing `data-theme-setting`; inline script in `frontend/index.html`
      resolving it (and `system`) to `data-theme` before the CSS
- [x] Top-bar button cycling System → Light → Dark; `system` follows
      `prefers-color-scheme` live

**Done when:**
- pytest: PATCH theme → file written → GET returns it; unknown keys survive;
  allowed during a run and on a read-only workflow; `GET /` contains the
  saved setting
- Playwright: choose Dark, reload → the first paint is dark (the `data-theme`
  attribute is set before `DOMContentLoaded`); emulated
  `prefers-color-scheme: dark` with `system` gives dark

## Step 4: Map Viewer basemap

- [x] Basemap `auto` (default) | `light` | `dark` | `none` in `tiles.BASEMAPS`,
      `merge_settings`, `map_view` and the map window; dark through MapLibre
      paint properties
- [x] A saved `light` stays `light`; no key means `auto`

**Done when:**
- vitest (`MapWindow.test.tsx`): `auto` gives the dark basemap paint in dark
  theme and the light one in light theme
- Playwright: layer colours are identical in both themes (sampled pixel of a
  classed raster)
- `docs-shots` writes the dark screenshots (SPEC section 4); README shows
  light and dark; this SPEC merged into `docs/SPEC.md`; change 02 marked
  done
