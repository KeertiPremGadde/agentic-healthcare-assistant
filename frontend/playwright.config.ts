import { defineConfig, devices } from "@playwright/test";

const WEB_PORT = 3100;
const API_PORT = 8765;
const API_URL = `http://localhost:${API_PORT}`;

/**
 * The smoke test runs the real frontend against a mock API (tests/e2e/mock-api.mjs) that speaks
 * the real contract, so it needs no database, no API key and costs nothing.
 * In CI the app is built first (`npm run build`) and served; locally the dev server is used.
 */
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: false, // the mock API keeps state; tests reset it
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: "node tests/e2e/mock-api.mjs",
      url: `${API_URL}/v1/auth/me`,
      // 401 is fine: it proves the server is up.
      ignoreHTTPSErrors: true,
      reuseExistingServer: !process.env.CI,
      env: { MOCK_API_PORT: String(API_PORT) },
    },
    {
      command: process.env.CI
        ? `npm run start -- --port ${WEB_PORT}`
        : `npm run dev -- --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/login`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: API_URL },
    },
  ],
});
