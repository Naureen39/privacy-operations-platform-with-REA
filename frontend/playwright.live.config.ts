import { defineConfig, devices } from "@playwright/test";

// Browser tests against the real application: the seeded database and the running API (start them
// with `python scripts/e2e_stack.py up` and `... api`). The built site is served by `vite preview`,
// which forwards /api to the API on port 8000. The tests change data, so they run one at a time.
export default defineConfig({
  testDir: "./e2e-live",
  timeout: 180_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:4174", trace: "off", viewport: { width: 1440, height: 900 } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command: "npx vite preview --host 127.0.0.1 --port 4174 --strictPort",
    url: "http://127.0.0.1:4174",
    reuseExistingServer: true,
    timeout: 60_000,
    env: { VITE_API_PROXY: "http://127.0.0.1:8000" },
  },
});
