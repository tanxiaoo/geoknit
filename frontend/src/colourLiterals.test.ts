// Change 02 (SPEC 8): every UI colour comes from a token of theme.css, so no other
// .css, .ts, .tsx or .svg file under src/ may hold a colour literal. Exceptions:
// theme.css (the tokens), palettes.ts (data colours, the same in both themes), test
// files (colours as data) and the vendored icon SVGs (src/icons/vendor/).
//
// What counts as a colour literal:
// - a hex colour `#rgb`, `#rgba`, `#rrggbb`, `#rrggbbaa` (not preceded by a letter,
//   digit or `&`, not followed by a letter, digit or `-`);
// - a colour function call: rgb(), rgba(), hsl(), hsla(), hwb(), lab(), lch(),
//   oklab(), oklch();
// - a CSS named colour (`white`, `red`, …): in CSS, as a word of a declaration's value;
//   in TypeScript, as a whole string literal (`"white"`) or after a border style or a
//   length (`"1px solid red"`).
// Not colours: `transparent`, `currentColor`, `inherit` and the other CSS-wide keywords.
//
// Where it looks:
// - CSS: only declaration values, after comments are removed, so `#root` selectors,
//   `white-space` and `var(--gk-red)` are not literals.
// - TypeScript: only string literals, template literal text and JSX text, read with
//   the TypeScript parser, so comments, regular expressions and identifiers are not
//   scanned.

import { readFileSync } from "node:fs";
import { cwd } from "node:process";
import ts from "typescript";
import { describe, expect, it } from "vitest";

// The glob only lists the files; they are read from disk because vitest turns imported
// CSS into an empty string, even with `?raw`. vitest runs in frontend/ (as registry.test).
const FILES = Object.keys(
  import.meta.glob([
    "./**/*.{ts,tsx,css,svg}",
    "!./**/*.test.{ts,tsx}",
    "!./theme.css",
    "!./palettes.ts",
    "!./icons/vendor/**",
  ]),
);
const SOURCES: Record<string, string> = Object.fromEntries(
  FILES.map((f) => [f, readFileSync(`${cwd()}/src/${f.slice(2)}`, "utf-8")]),
);

// CSS Color Module Level 4 named colours (without `transparent` and `currentcolor`).
const NAMED = new Set(
  (
    "aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue " +
    "blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk " +
    "crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki " +
    "darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue " +
    "dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite " +
    "gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki " +
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen " +
    "lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen " +
    "magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen " +
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream " +
    "mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum " +
    "powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown " +
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen " +
    "steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen"
  ).split(" "),
);

const HEX = /(?<![\w&])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![\w-])/gi;
const FUNCTION = /(?<![\w-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/gi;
const WORD = /(?<![\w-])[a-z]+(?![\w-])/gi;
const AFTER_LENGTH =
  /(?<=(?:\b(?:solid|dashed|dotted|double|groove|ridge|inset|outset)|\d(?:px|em|rem|%)?)\s+)([a-z]+)(?![\w-])/gi;

/** Hex colours and colour functions in ``text``. */
function hexAndFunctions(text: string): string[] {
  return [...(text.match(HEX) ?? []), ...(text.match(FUNCTION) ?? [])];
}

/** Colour literals in the declaration values of a stylesheet. */
export function cssLiterals(css: string): string[] {
  const found: string[] = [];
  const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of code.matchAll(/([-\w]+)\s*:\s*([^;{}]*)(?=[;}])/g)) {
    const value = m[2];
    found.push(...hexAndFunctions(value));
    for (const w of value.match(WORD) ?? []) if (NAMED.has(w.toLowerCase())) found.push(w);
  }
  return found;
}

/** Colour literals in the strings, template text and JSX text of TypeScript code. */
export function tsLiterals(code: string, fileName = "file.tsx"): string[] {
  const source = ts.createSourceFile(fileName, code, ts.ScriptTarget.Latest, true);
  const found: string[] = [];
  const check = (text: string) => {
    found.push(...hexAndFunctions(text));
    if (NAMED.has(text.trim().toLowerCase())) found.push(text.trim());
    for (const m of text.matchAll(AFTER_LENGTH)) if (NAMED.has(m[1].toLowerCase())) found.push(m[1]);
  };
  const visit = (node: ts.Node) => {
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node)
    ) {
      check(node.text);
    }
    node.forEachChild(visit);
  };
  visit(source);
  return found;
}

/** Colour literals of one source file, by its extension. */
function literals(path: string, text: string): string[] {
  if (path.endsWith(".css")) return cssLiterals(text);
  if (path.endsWith(".svg")) return hexAndFunctions(text);
  return tsLiterals(text, path);
}

describe("no colour literal outside theme.css and palettes.ts", () => {
  it("scans the frontend sources", () => {
    const files = Object.keys(SOURCES);
    expect(files).toContain("./styles.css");
    expect(files).toContain("./types.ts");
    expect(files).toContain("./components/map/MapCanvas.tsx");
    expect(files).not.toContain("./theme.css");
    expect(files).not.toContain("./palettes.ts");
    expect(SOURCES["./styles.css"]).toContain("var(--gk-ink)");
  });

  it("finds none", () => {
    const offenders: Record<string, string[]> = {};
    for (const [path, text] of Object.entries(SOURCES)) {
      const found = literals(path, text);
      if (found.length) offenders[path] = found;
    }
    expect(offenders).toEqual({});
  });
});

describe("the colour-literal scanner", () => {
  it("catches literals in CSS values", () => {
    expect(cssLiterals(".a { color: #fff; }")).toEqual(["#fff"]);
    expect(cssLiterals(".a { box-shadow: 0 0 0 1px rgb(15 23 42 / 0.2) }")).toEqual(["rgb("]);
    expect(cssLiterals(".a { border: 1px solid Red; }")).toEqual(["Red"]);
    expect(cssLiterals(".a { background: hsl(0 0% 0%); }")).toEqual(["hsl("]);
    expect(cssLiterals(".a { --x: #0B7A7C80; }")).toEqual(["#0B7A7C80"]);
    expect(cssLiterals(".a { stroke: var(--gk-x, #64748b); }")).toEqual(["#64748b"]);
  });

  it("leaves selectors, comments, tokens and keywords alone", () => {
    const css = [
      "/* #ff0000 and white in a comment */",
      "html, body, #root, #add { margin: 0; }",
      ".gk-red:hover { white-space: nowrap; color: var(--gk-red); }",
      ".a { background: transparent; color: currentColor; border-color: inherit; }",
      '.a { font-family: "Segoe UI", system-ui; }',
    ].join("\n");
    expect(cssLiterals(css)).toEqual([]);
  });

  it("catches literals in TypeScript strings, templates and JSX", () => {
    expect(tsLiterals('const c = "#d4d8de";')).toEqual(["#d4d8de"]);
    expect(tsLiterals("const c = `drop-shadow(0 0 2px ${x}) rgba(0, 0, 0, ${a})`;")).toEqual(["rgba("]);
    expect(tsLiterals('const s = { color: "white" };')).toEqual(["white"]);
    expect(tsLiterals('const s = { border: "2px solid black" };')).toEqual(["black"]);
    expect(tsLiterals('const e = <Background color="#d4d8de" />;')).toEqual(["#d4d8de"]);
  });

  it("leaves comments, ids, hashes, regexes and words alone", () => {
    const code = [
      "// a comment naming #0B7A7C and red",
      "/** `#fff` in a doc comment */",
      'const url = "/api/vector/#section";',
      'const sel = document.querySelector("#root");',
      'const hash = "#3f2a9c1b07e4";', // a 12-digit hash is not a colour
      "const HEX = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i;",
      'const label = "The red dot marks out-of-date nodes";',
      'const css = "var(--gk-type-number)";',
      'const t = "transparent";',
      "const e = <p>Pick a colour, e.g. white</p>;",
    ].join("\n");
    expect(tsLiterals(code)).toEqual([]);
  });
});
