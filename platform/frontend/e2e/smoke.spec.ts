/** login -> queue -> ring detail -> verdict, against the fixture server (step 4 of the port). */
import { expect, test } from "@playwright/test";

test.beforeEach(async ({ request }) => {
  await request.post("http://127.0.0.1:8011/__reset");          // fresh fixtures: every ring open again
});

async function signIn(page: import("@playwright/test").Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("an analyst opens the top ring and confirms it", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));

  await signIn(page, "analyst@bank-a.fixture", "fixture-only-a1");
  await expect(page.getByTestId("sidebar-tenant")).toHaveText("Fixture Bank A");
  await expect(page.getByTestId("sidebar-role")).toHaveText("Role: analyst");
  await expect(page.getByTestId("ring-total")).toHaveText("104 rings match these filters");
  const rows = page.getByTestId("ring-row");
  await expect(rows).toHaveCount(50);
  await expect(rows.first()).toContainText("full-gine_causal-1-0");     // highest confidence first

  await rows.first().getByText("full-gine_causal-1-0").click();
  await expect(page).toHaveURL(/\/rings\/full-gine_causal-1-0$/);
  await expect(page.getByTestId("narrative")).toContainText("ring");
  await expect(page.getByTestId("ring-graph").locator("canvas").first()).toBeVisible();
  await expect(page.getByTestId("transaction-row").first()).toBeVisible();
  await expect(page.getByTestId("status-badge")).toHaveText("open");

  await page.getByLabel(/Note \(optional/).fill("smoke test");
  await page.getByRole("button", { name: /Confirm ring/ }).click();
  await expect(page.getByText("Verdict recorded")).toBeVisible();
  await expect(page.getByTestId("status-badge")).toHaveText("confirmed");
  await expect(page.getByTestId("ring-verdict-row")).toContainText("smoke test");

  await page.getByRole("link", { name: "Back to queue" }).click();
  await expect(page.getByTestId("ring-total")).toHaveText("103 rings match these filters");
  expect(errors).toEqual([]);
});

test("a page the role may not open says so", async ({ page }) => {
  await signIn(page, "analyst@bank-a.fixture", "fixture-only-a1");
  await expect(page.getByTestId("ring-total")).toBeVisible();
  await page.evaluate(() => {
    history.pushState({}, "", "/admin");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByText("Not permitted")).toBeVisible();
  await expect(page.getByRole("link", { name: "Admin" })).toHaveCount(0);
});
