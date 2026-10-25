/** Login and session: FR-D01-05, NFR-D10, NFR-D11, NFR-D14. */
import { expect, test } from "@playwright/test";
import { FIXTURE_API, USERS, apiRequests, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

test("FR-D01: the sidebar shows the session's tenant and role", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await expect(page.getByTestId("sidebar-tenant")).toHaveText("Fixture Bank A");
  await expect(page.getByTestId("sidebar-role")).toHaveText("Role: analyst");
});

test("FR-D02: a wrong password and an unknown email give the same message", async ({ page }) => {
  const attempt = async (email: string, password: string) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    const message = page.getByRole("form", { name: "Sign in" }).getByText(/incorrect/i);
    await expect(message).toBeVisible();
    return message.textContent();
  };
  const wrongPassword = await attempt(USERS.analystA[0], "not-the-password");
  const unknownEmail = await attempt("nobody@bank-a.fixture", USERS.analystA[1]);
  expect(wrongPassword).toBe(unknownEmail);
  expect(wrongPassword).not.toMatch(/email (is|was)|password (is|was)|no such|unknown/i);
});

test("FR-D03, NFR-D14: a 401 from any call returns to login with 'Session expired'", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await page.route(`${FIXTURE_API}/**`, (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: '{"error":"unauthorized","message":"expired"}' }));
  await go(page, "/verdicts");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Session expired")).toBeVisible();
});

test("FR-D04: sign out clears the session; back shows login", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await expect(page.getByTestId("ring-total")).toBeVisible();
  await page.getByRole("link", { name: "Verdict history" }).click();         // a history entry to go back to
  await expect(page).toHaveURL(/\/verdicts$/);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goBack();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
  await expect(page.getByTestId("sidebar-tenant")).toHaveCount(0);
});

test("FR-D05: an analyst has no Drift or Admin entry and is refused both by URL, with no data", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await expect(page.getByRole("link", { name: "Drift" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
  const requests = apiRequests(page);
  for (const path of ["/drift", "/admin"]) {
    await go(page, path);
    await expect(page.getByText("Not permitted")).toBeVisible();
  }
  expect(requests.filter((r) => /\/drift|\/admin\//.test(r.url()))).toEqual([]);
});

test("NFR-D10: nothing about the session in storage, cookies or the URL", async ({ page, context }) => {
  await signIn(page, USERS.analystA);
  await expect(page.getByTestId("ring-total")).toBeVisible();
  const storage = await page.evaluate(() => ({
    local: Object.keys(localStorage), session: Object.keys(sessionStorage),
    values: Object.values(localStorage).join(" "),
  }));
  expect(storage.session).toEqual([]);
  expect(storage.local.filter((key) => key !== "ringshield-theme")).toEqual([]);   // theme preference only
  expect(storage.values).not.toMatch(/fixture-token|token/);
  expect(await context.cookies()).toEqual([]);
  expect(page.url()).not.toMatch(/token|tenant/i);
});

test("NFR-D11: every API call carries the bearer token and only the session's tenant id", async ({ page }) => {
  const requests = apiRequests(page);
  await signIn(page, USERS.analystA);
  await page.getByTestId("ring-row").first().click();
  await expect(page.getByTestId("narrative")).toBeVisible();
  await go(page, "/verdicts");
  await go(page, "/models");
  const after = requests.filter((r) => !r.url().endsWith("/auth/login") && r.method() !== "OPTIONS");
  expect(after.length).toBeGreaterThan(3);
  for (const request of after) {
    expect(request.headers()["authorization"]).toMatch(/^Bearer \S+/);
    const tenant = request.url().match(/\/tenants\/(\d+)/);
    if (tenant) expect(tenant[1]).toBe("1001");
  }
});
