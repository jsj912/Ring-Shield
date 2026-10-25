/** Cross-cutting: FR-D100 / NFR-D30 (error state with request id and retry on every screen) and FR-D104. */
import { expect, test, type Page } from "@playwright/test";
import { FIXTURE_API, USERS, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

/** Every API call after sign-in answers 500 with a request id until `heal` is called. */
async function failEverything(page: Page) {
  let failing = true;
  await page.route(`${FIXTURE_API}/**`, (route) => {
    if (!failing || route.request().method() === "OPTIONS") return route.fallback();
    return route.fulfill({
      status: 500, contentType: "application/json", headers: { "X-Request-ID": "req-500-test" },
      body: JSON.stringify({ error: "internal", message: "simulated failure", request_id: "req-500-test" }),
    });
  });
  return () => { failing = false; };
}

const SCREENS: [string, readonly [string, string], string][] = [
  ["/rings", USERS.analystA, "ring-total"],
  ["/rings/full-gine_causal-1-0", USERS.analystA, "narrative"],
  ["/verdicts", USERS.analystA, "verdict-row"],
  ["/models", USERS.analystA, "model-row"],
  ["/drift", USERS.supervisorA, "drift-event-row"],
  ["/admin", USERS.admin, "tenant-registry"],
];

for (const [path, user, ready] of SCREENS) {
  test(`FR-D100, NFR-D30: ${path} shows the error, its request id and a retry, then recovers`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await signIn(page, user);
    const heal = await failEverything(page);
    await go(page, path);
    if (path === "/rings") {                                    // the queue is cached from sign-in: ask for a new page
      await page.getByLabel("Search ring ID or account ID").fill("full-gine_causal-1-0");
      await page.getByRole("button", { name: "Apply filters" }).click();
    }
    const alert = page.getByRole("alert").filter({ hasText: "req-500-test" }).first();
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("simulated failure");
    await expect(page.getByTestId("sidebar-tenant")).toBeVisible();                 // never a blank page
    heal();
    // each panel fails and retries on its own (NFR-D32): retry them all
    // (on ring detail the panels' own errors appear once the ring itself has loaded)
    for (let i = 0; i < 10 && !(await page.getByTestId(ready).count()); i += 1) {
      await page.getByRole("button", { name: "Retry" }).first().click({ timeout: 2000 }).catch(() => undefined);   // may recover first
      await page.waitForTimeout(300);
    }
    await expect(page.getByTestId(ready).first()).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("FR-D100: every screen shows a loading state first", async ({ page }) => {
  await signIn(page, USERS.supervisorA);
  await page.route(`${FIXTURE_API}/**`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    return route.fallback();
  });
  for (const path of ["/verdicts", "/models", "/drift"]) {
    await go(page, path);
    await expect(page.locator('[data-slot="skeleton"], .animate-pulse').first()).toBeVisible();
  }
});

test("FR-D104: no response or screen carries ground truth, pattern ids or account numbers", async ({ page }) => {
  const bodies: Promise<string>[] = [];
  page.on("response", (response) => {
    if (response.url().startsWith(FIXTURE_API)) bodies.push(response.text().catch(() => ""));
  });
  await signIn(page, USERS.supervisorA);
  for (const path of ["/rings", "/rings/full-gine_causal-1-0", "/verdicts", "/models", "/drift"]) {
    await go(page, path);
    await page.waitForLoadState("networkidle");
  }
  const text = (await Promise.all(bodies)).join("\n") + (await page.content());
  for (const key of ["is_laundering", "pattern_id", "ground_truth", "laundering_attempt", "account_number", "Account Number"]) {
    expect(text).not.toContain(key);
  }
});
