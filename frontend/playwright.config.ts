import { defineConfig } from "@playwright/test";
import path from "node:path";

// Runs against the real app and worker on loopback, with its own data directory.
const dataDir = path.resolve(import.meta.dirname, "../data/e2e_app");
export default defineConfig({
  testDir: "./tests",
  timeout: 240_000,
  workers: 1, // the app has one analysis worker, and tests share its data directory
  // Existing specs exercise the detailed view and the manual start; tests/simple.spec.ts clears this to test the defaults.
  use: { baseURL: "http://127.0.0.1:8318", video: "off", storageState: { cookies: [], origins: [{ origin: "http://127.0.0.1:8318", localStorage: [
    { name: "climbreview.view", value: "detailed" }, { name: "climbreview.autoAnalyze", value: "off" }] }] } },
  reporter: [["list"]],
  webServer: {
    command: `CLIMBREVIEW_DATA_DIR="${dataDir}" CLIMBREVIEW_PORT=8318 ../.venv/bin/python ../scripts/run_app.py`,
    url: "http://127.0.0.1:8318/api/attempts",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
