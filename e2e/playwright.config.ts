import { defineConfig, devices } from "@playwright/test";

const WEB = process.env["WEB_BASE_URL"] ?? "http://localhost:3100";
const ADMIN = process.env["ADMIN_BASE_URL"] ?? "http://localhost:3102";

export default defineConfig({
  testDir: "./tests",
  globalSetup: "./global-setup.ts",
  fullyParallel: true,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 2 : 0,
  reporter: process.env["CI"] ? "github" : "list",
  // `next dev` compiles a route on its first request, and this suite opens
  // several cold routes at once across two device projects. The 30s default is
  // ample against a built app and routinely short of a cold dev compile — the
  // resulting `page.goto` timeouts look like product failures and are not.
  timeout: 90_000,
  use: {
    trace: "on-first-retry",
    navigationTimeout: 60_000,
  },
  projects: [
    {
      name: "web-chromium",
      testMatch: /(^|\/)(home|auth|catalogue|balance|buy)\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"], baseURL: WEB },
    },
    {
      name: "web-iphone",
      testMatch: /home\.spec\.ts/,
      use: { ...devices["iPhone 14"], baseURL: WEB },
    },
    {
      name: "admin-chromium",
      testMatch: /(^|\/)admin(-catalogue|-money|-orders)?\.spec\.ts$/,
      use: { ...devices["Desktop Chrome"], baseURL: ADMIN },
    },
  ],
});
