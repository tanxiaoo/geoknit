// The few Node.js APIs registry.test.tsx uses to check and write docs/icons.md
// (vitest runs on Node; the app itself never imports them). Declared here so
// the frontend does not need @types/node.

declare module "node:fs" {
  export function existsSync(path: string): boolean;
  export function readFileSync(path: string, encoding: "utf-8"): string;
  export function writeFileSync(path: string, data: string, encoding: "utf-8"): void;
  export function readdirSync(path: string): string[];
  export function mkdirSync(path: string, options: { recursive: true }): void;
  export function rmSync(path: string): void;
}

declare module "node:process" {
  export const env: Record<string, string | undefined>;
  export function cwd(): string;
}
