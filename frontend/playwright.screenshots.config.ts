import { defineConfig, type PlaywrightTestConfig } from "@playwright/test";
import base from "./playwright.config";

type WebServer = NonNullable<PlaywrightTestConfig["webServer"]>;
const [mockApi, web] = base.webServer as Exclude<WebServer, unknown[]> extends never
  ? never
  : [Exclude<WebServer, unknown[]>, Exclude<WebServer, unknown[]>];

/** Same servers as the smoke test, but the frontend is a production build (no dev overlay). */
export default defineConfig({
  ...base,
  testMatch: /.*\.shots\.ts/,
  reporter: "list",
  retries: 0,
  webServer: [
    mockApi,
    {
      ...web,
      command: "npm run build && npm run start -- --port 3100",
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
