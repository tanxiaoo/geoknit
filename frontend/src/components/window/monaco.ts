// Monaco, bundled locally (no CDN: GeoKnit works offline). Loaded on demand by
// CodeEditor so the canvas does not pay for it until a Code tab opens.
//
// Only the editor core and the Python grammar are included, not every
// language Monaco ships.

// @ts-expect-error: the core bundle has no .d.ts of its own; it is typed as "monaco-editor" below
import * as core from "monaco-editor/esm/vs/editor/edcore.main.js";
import "monaco-editor/esm/vs/basic-languages/python/python.contribution.js";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

// Monaco's own typings declare window.MonacoEnvironment.
window.MonacoEnvironment = { getWorker: () => new EditorWorker() };

export const monaco = core as typeof import("monaco-editor");
