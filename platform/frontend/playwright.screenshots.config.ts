/**
 * `npm run screenshots`: the visual tour (e2e/screenshots.spec.ts) against the REAL running demo
 * (scripts/demo.ps1), not the fixture server, so there is no webServer here. Writes PNGs to
 * docs/screenshots/; scripts/compress_screenshots.py then shrinks them.
 */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  testMatch: "screenshots.spec.ts",
  timeout: 120_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: process.env.SCREENSHOT_BASE_URL ?? "http://localhost:5173",
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "msedge",
    viewport: { width: 1680, height: 1000 },
  },
});
