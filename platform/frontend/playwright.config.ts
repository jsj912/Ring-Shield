/**
 * Smoke test against the fixture server (no Postgres). Its own ports (8011, 5174), so it does not
 * collide with a dev session. Runs on the installed Microsoft Edge, so no browser download is needed;
 * set PLAYWRIGHT_CHANNEL=chrome to use Chrome instead. PYTHON is the interpreter with FastAPI.
 */
import { defineConfig } from "@playwright/test";

const python = process.env.PYTHON ?? "python";
const apiPort = 8011;
const webPort = 5174;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: 0,
  use: {
    baseURL: `http://localhost:${webPort}`,
    channel: process.env.PLAYWRIGHT_CHANNEL ?? "msedge",
    viewport: { width: 1680, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} ../dashboard/fixture_server.py --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/docs`,
      env: { RINGSHIELD_CORS_ORIGINS: `http://localhost:${webPort}` },
      reuseExistingServer: false,
    },
    {
      command: `npx vite --port ${webPort} --strictPort`,
      url: `http://localhost:${webPort}`,
      env: { VITE_API_URL: `http://127.0.0.1:${apiPort}` },
      reuseExistingServer: false,
    },
  ],
});
