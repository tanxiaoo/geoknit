import { defineConfig } from "@playwright/test";

// Screenshots for docs/milan-walkthrough.md, taken on the real Milan data:
//   npm run build && npm run screenshots
// GEOKNIT_MILAN_DATA points at the data folder (default examples/milan_imd/data).
const port = Number(process.env.GEOKNIT_SHOTS_PORT ?? 8766);
const python = process.env.PYTHON ?? "python";

export default defineConfig({
  testDir: ".",
  timeout: 600_000,
  expect: { timeout: 60_000 },
  workers: 1,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 1,
  },
  webServer: {
    command: `${python} serve_milan.py ${port}`, // runs in this folder
    url: `http://127.0.0.1:${port}/api/status`,
    timeout: 120_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
