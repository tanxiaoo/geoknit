/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../geoknit/server/static",
    emptyOutDir: true,
    // Monaco (the Code tab) is one ~3 MB chunk, loaded only when a Code tab opens.
    chunkSizeWarningLimit: 3500,
  },
  server: {
    proxy: {
      "/api": backend,
      "/tiles": backend,
      "/ws": { target: backend.replace("http", "ws"), ws: true },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    globals: true,
  },
});
