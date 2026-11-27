import { defineConfig } from "@playwright/test";

// End-to-end tests (PLAN Phase 5): a real GeoKnit server on a temporary
// project with the synthetic data, serving the built frontend (`npm run build`).
const port = Number(process.env.GEOKNIT_E2E_PORT ?? 8765);
const python = process.env.PYTHON ?? "python";

export default defineConfig({
  testDir: "e2e",
  timeout: 300_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0, // the tests share one server and build on each other
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1920, height: 1080 },
    // the app follows prefers-color-scheme (theme setting `system`): never the host's
    colorScheme: "light",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `${python} e2e/serve.py ${port}`,
    url: `http://127.0.0.1:${port}/api/status`,
    timeout: 180_000,
    reuseExistingServer: false,
    stdout: "pipe",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
