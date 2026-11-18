import { defineConfig, devices } from "@playwright/test";

const baseURL = "http://127.0.0.1:4179";
export default defineConfig({
  testDir: "./tests",
  workers: 2,
  timeout: 20_000,
  globalTimeout: 240_000,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [
    { name: "chrome", use: { ...devices["Desktop Chrome"], channel: "chrome" } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
  ],
  webServer: {
    command: "npm run dev -- --host 127.0.0.1 --port 4179 --strictPort",
    url: baseURL,
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
