/**
 * Smoke test against the fixture server (no Postgres). Its own ports (8011, 5174), so it does not
 * collide with a dev session. Runs on the installed Microsoft Edge, so no browser download is needed;
 * set PLAYWRIGHT_CHANNEL=chrome to use Chrome instead. PYTHON is the interpreter with FastAPI.
 */
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";

// PYTHON wins; else the platform venv next to the repo (E:/JSJ/venv-platform); else python on PATH
const venvPython = resolve(dirname(fileURLToPath(import.meta.url)), "../../../venv-platform/Scripts/python.exe");
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : "python");
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
      command: `${python} fixtures/fixture_server.py --port ${apiPort}`,
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
