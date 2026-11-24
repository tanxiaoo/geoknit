# UI mockups

Reference screens for Phase 5–7. They show the Milan IMD workflow with mock
values. Match the layout, node style, colours and interactions; the exact
pixel sizes and the numbers shown are illustrative.

| File | What it shows |
|------|---------------|
| `01-main.png` | Whole editor: top bar, ribbon, project folder, canvas, status bar, Assistant placeholder. `n_trees` was just changed, so downstream components are out of date. |
| `02-icon-mode.png` | Same canvas with "Show as: Icon". |
| `03-component-settings.png` | Component window, Settings tab (Random Forest): wired inputs show their source, unwired inputs an editable default; Output always at the bottom. |
| `04-component-code.png` | Same component, Code tab: the full component file (header, settings block, code) as in SPEC section 4. |
| `05-reclassify-settings.png` | Reclassify settings and the Panel showing its 7-class output. |
| `06-python-component.png` | Python component editor with port chips, code and Output log. |
| `07-map-viewer-settings.png` | Map Viewer component settings (it takes several wires; double-click opens the map window). |

Notes:
- The Python component in `06` uses an older window layout. In the app it
  should use the same Settings | Code window as every other component, with
  port editing (add, remove, rename, set type) in the Settings tab.
- The Map Viewer map window itself is not drawn; follow SPEC section 8.
