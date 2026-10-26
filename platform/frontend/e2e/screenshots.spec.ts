/**
 * The visual tour in docs/SCREENSHOTS.md, captured from the REAL demo (scripts/demo.ps1: seed-1 rings,
 * L4 explanations, seeded demo users), not the fixture server. Run on a fresh demo:
 *
 *   .\scripts\demo.ps1
 *   npm run screenshots          (in platform/frontend)
 *
 * Not part of `npm run test:e2e` (playwright.config.ts ignores this file). Shot 08 records a partial
 * verdict, so a second run against the same database skips it; every other shot only reads.
 * Logins come from platform/demo-credentials.txt (written by the demo, gitignored); nothing from it
 * is shown: the login shot is taken empty. Verdict times change on every run and are masked.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Locator, type Page } from "@playwright/test";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const OUT = resolve(ROOT, "docs/screenshots");
const RING = "full-gine_causal-1-0";          // bank 12's top ring: FAN-OUT, five members, roles visible
const REGEN_RING = "full-gine_causal-1-1";    // the ring shot 08 corrects, so RING stays open

function credentials(): Record<string, string> {
  const text = readFileSync(resolve(ROOT, "platform/demo-credentials.txt"), "utf-8");
  return Object.fromEntries(text.split(/\r?\n/).map((line) => line.match(/^([^=]+)=(.*)$/)).filter(Boolean)
    .map((m) => [m![1], m![2]]));
}
const CREDS = credentials();
const login = (key: string) => [CREDS[`${key}_email`], CREDS[`${key}_password`]] as const;

async function signIn(page: Page, key: string) {
  const [email, password] = login(key);
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("sidebar-tenant")).toBeVisible();
}

/** In-app navigation: a page load would sign the user out (the session is in memory only). */
async function go(page: Page, path: string) {
  await page.evaluate((to) => { history.pushState({}, "", to); dispatchEvent(new PopStateEvent("popstate")); }, path);
}

const masks = (page: Page): Locator[] => [
  page.locator('[data-testid="verdict-row"] td:first-child'),
  page.locator('[data-testid="ring-verdict-row"] td:first-child'),
  page.getByTestId("latest-verdict"),
];

async function shot(page: Page, name: string, theme: string, target?: Locator) {
  await page.waitForLoadState("networkidle");
  const path = resolve(OUT, `${name}-${theme}.png`);
  if (target) await target.screenshot({ path, mask: masks(page), animations: "disabled" });
  else await page.screenshot({ path, mask: masks(page), animations: "disabled" });
}

const card = (page: Page, title: string) =>
  page.locator("div.bg-card").filter({ has: page.getByText(title, { exact: true }) }).first();

for (const theme of ["light", "dark"] as const) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => window.localStorage.setItem("ringshield-theme", value), theme);
    });

    test(`01 login (${theme})`, async ({ page }) => {
      await page.goto("/login");
      await shot(page, "01-login", theme);
    });

    test(`02-07 analyst at bank 12 (${theme})`, async ({ page }) => {
      await signIn(page, "tenant_12_analyst");
      await expect(page.getByTestId("ring-row").first()).toBeVisible();
      await shot(page, "02-ring-queue", theme);

      await page.getByTestId("ring-row").first().getByRole("button", { name: "Confirm" }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await shot(page, "07-quick-verdict", theme);
      await page.getByRole("button", { name: "Cancel confirmation" }).click();

      await go(page, `/rings/${RING}?bank=12`);
      await expect(page.getByTestId("narrative")).toBeVisible();
      await expect(page.getByTestId("ring-graph")).toBeVisible();
      await page.waitForTimeout(1500);                        // the graph layout settles
      await shot(page, "03-ring-detail-graph", theme, card(page, "Graph"));
      await shot(page, "04-ring-detail-evidence", theme, card(page, "Evidence"));
      await shot(page, "05-ring-detail-narrative", theme, card(page, "Narrative"));

      const form = card(page, "Record a verdict");
      await form.getByRole("textbox").first().fill("Fan-out from one sender; amounts and timing match the narrative.");
      await shot(page, "06-verdict-form", theme, form);
    });

    test(`08 partial verdict regenerates the narrative (${theme})`, async ({ page }) => {
      await signIn(page, "tenant_12_analyst");
      await go(page, `/rings/${REGEN_RING}?bank=12`);
      const partial = page.getByRole("button", { name: /Partially correct/ });
      await expect(page.getByTestId("narrative")).toBeVisible();
      test.skip(!(await partial.isEnabled()), "already corrected in this database (shot 08 needs a fresh demo)");
      await partial.click();
      await page.getByRole("checkbox", { name: /^Keep account / }).last().click();
      await page.getByLabel("Note (required for partial)").fill("This account is not part of the ring.");
      await page.getByRole("button", { name: /Submit partial verdict/ }).click();
      await expect(page.getByText(/Regenerat/).first()).toBeVisible({ timeout: 60_000 });
      await shot(page, "08-regeneration", theme);
    });

    test(`09-11 supervisor at bank 12 (${theme})`, async ({ page }) => {
      await signIn(page, "tenant_12_supervisor");
      await go(page, "/verdicts");
      await expect(page.getByRole("heading", { name: "Verdict history" })).toBeVisible();
      await shot(page, "09-verdicts", theme);
      await go(page, "/models");
      await expect(page.getByRole("heading", { name: "Models" })).toBeVisible();
      await shot(page, "10-models", theme);
      await go(page, "/drift");
      await expect(page.getByTestId("drift-statement")).toBeVisible();
      await shot(page, "11-drift", theme);
    });

    test(`12 administrator (${theme})`, async ({ page }) => {
      await signIn(page, "admin");
      await go(page, "/admin");
      await expect(page.getByTestId("r10-summary")).toBeVisible();
      await shot(page, "12-admin", theme);
    });

    test(`13 analyst at bank 20 (${theme})`, async ({ page }) => {
      await signIn(page, "tenant_20_analyst");
      await expect(page.getByTestId("ring-row").first()).toBeVisible();
      await shot(page, "13-tenant-isolation", theme);
    });
  });
}

test.describe("phone width", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("queue and ring detail at 390 x 844", async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("ringshield-theme", "light"));
    await signIn(page, "tenant_12_analyst");
    await expect(page.getByTestId("ring-row").first()).toBeVisible();
    await shot(page, "15-mobile-queue", "light");
    await go(page, `/rings/${RING}?bank=12`);
    await expect(page.getByTestId("narrative")).toBeVisible();
    await shot(page, "16-mobile-ring-detail", "light");
  });
});

test("14 API docs (Swagger UI)", async ({ page }) => {
  await page.goto(`${process.env.SCREENSHOT_API_URL ?? "http://127.0.0.1:8000"}/docs`);
  await expect(page.getByText("RingShield", { exact: false }).first()).toBeVisible();
  await page.screenshot({ path: resolve(OUT, "14-api-docs.png"), animations: "disabled" });
});
