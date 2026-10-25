/** Shared steps for the per-screen acceptance tests (docs/dashboard_checklist.md). */
import { expect, type Page, type Request } from "@playwright/test";

export const FIXTURE_API = "http://127.0.0.1:8011";

export const USERS = {
  analystA: ["analyst@bank-a.fixture", "fixture-only-a1"],
  supervisorA: ["supervisor@bank-a.fixture", "fixture-only-a2"],
  analystB: ["analyst@bank-b.fixture", "fixture-only-b1"],
  admin: ["admin@platform.fixture", "fixture-only-admin"],
} as const;

export async function signIn(page: Page, [email, password]: readonly [string, string]) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("sidebar-tenant")).toBeVisible();
}

/** In-app navigation: a full page load would sign the user out (the session is in memory only). */
export async function go(page: Page, path: string) {
  await page.evaluate((to) => {
    history.pushState({}, "", to);
    dispatchEvent(new PopStateEvent("popstate"));
  }, path);
}

/** Every request to the fixture API made from now on. */
export function apiRequests(page: Page): Request[] {
  const seen: Request[] = [];
  page.on("request", (request) => {
    if (request.url().startsWith(FIXTURE_API)) seen.push(request);
  });
  return seen;
}
