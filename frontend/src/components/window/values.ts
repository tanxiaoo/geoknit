// Settings values in the component window: show them as Python literals,
// read typed text back (SPEC 4: number, text, True/False, None, or a list).

import type { SettingView } from "../../apiTypes";

/** How a value reads in a text field: Python spelling for non-text values. */
export function valueText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  if (Array.isArray(value)) return `[${value.map(literal).join(", ")}]`;
  return String(value);
}

function literal(value: unknown): string {
  return typeof value === "string" ? JSON.stringify(value) : valueText(value);
}

const NUMBER = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

/**
 * Read a typed value. A setting that holds text stays text; otherwise
 * `None`, `True`/`False`, numbers and `[...]` lists are understood, and
 * anything else is text.
 */
export function parseValue(text: string, original: unknown): unknown {
  if (typeof original === "string") return text;
  const t = text.trim();
  if (t === "None" || t === "") return null;
  if (t === "True") return true;
  if (t === "False") return false;
  if (NUMBER.test(t)) return Number(t);
  if ((t.startsWith("[") && t.endsWith("]")) || (t.startsWith("(") && t.endsWith(")"))) {
    const json = `[${t.slice(1, -1)}]`
      .replace(/'/g, '"')
      .replace(/\bNone\b/g, "null")
      .replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false")
      .replace(/,\s*]$/, "]");
    try {
      return JSON.parse(json) as unknown;
    } catch {
      return text;
    }
  }
  return text;
}

/** The line number in a parse error such as "line 12: settings block: ...". */
export function errorLine(parseError: string | null | undefined): number | null {
  const m = parseError ? /^line (\d+):/.exec(parseError) : null;
  return m ? Number(m[1]) : null;
}

/** The setting that gives an input its default value (SPEC 4), if any. */
export function defaultFor(settings: SettingView[], input: string): SettingView | undefined {
  return settings.find((s) => s.name === input);
}

/** A fresh port name: `x1`, `x2`, ... not used yet. */
export function freshName(prefix: string, taken: string[]): string {
  for (let i = 1; ; i++) if (!taken.includes(`${prefix}${i}`)) return `${prefix}${i}`;
}
