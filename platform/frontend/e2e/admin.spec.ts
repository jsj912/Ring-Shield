/** Admin: FR-D90, FR-D91, FR-D93 and override 6 (R10 from r10_registered.json). */
import { expect, test, type Page } from "@playwright/test";
import { FIXTURE_API, USERS, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

async function openAdmin(page: Page) {
  await signIn(page, USERS.admin);
  await go(page, "/admin");
  await expect(page.getByTestId("r10-primary")).toBeVisible();
}

test("FR-D90: the tenant registry", async ({ page }) => {
  await openAdmin(page);
  const registry = page.getByTestId("tenant-registry");
  for (const header of ["Tenant ID", "Bank code", "Name", "Loaded", "Rings", "Verdicts"]) {
    await expect(registry.getByRole("columnheader", { name: header })).toBeVisible();
  }
  await expect(registry.getByRole("row", { name: /Fixture Bank A/ })).toBeVisible();
});

test("override 6: registered tables first, primary and robustness apart, extras labelled, bank 70 degenerate", async ({ page }) => {
  await openAdmin(page);
  const order = await page.locator('[data-testid^="r10-"]').evaluateAll((all) => all.map((e) => e.getAttribute("data-testid")));
  const at = (id: string) => order.indexOf(id);
  expect(at("r10-primary")).toBeGreaterThanOrEqual(0);
  expect(at("r10-primary")).toBeLessThan(at("r10-robustness"));
  expect(at("r10-robustness")).toBeLessThan(at("r10-post-hoc"));                 // registered rows before the extras
  await expect(page.getByRole("heading", { name: /^Primary set \(banks 1, 20, 11, 118, 12\)$/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Robustness set \(banks 70, 12, 11, 1, 10\)$/ })).toBeVisible();
  const bank70 = page.getByTestId("r10-robustness").getByRole("row").filter({ has: page.getByRole("cell", { name: "70", exact: true }) });
  await expect(bank70).toContainText("degenerate: no ring edges visible");
  const extras = page.getByTestId("r10-post-hoc");
  await expect(extras.getByRole("heading").first()).toContainText("post-hoc, descriptive");
  for (const heading of await extras.getByRole("heading").all()) await expect(heading).toContainText("post-hoc, descriptive");
});

test("FR-D91: pooled row with CIs, overall cross-bank fraction and banks per ring above the table, chart", async ({ page }) => {
  await openAdmin(page);
  await expect(page.getByTestId("r10-summary")).toContainText(/Cross-bank rings: \d+ of \d+ \(\d+\.\d%\).*mean banks per ring/s);
  const pooled = page.getByTestId("r10-primary").getByRole("row", { name: /All five/ });
  await expect(pooled).toContainText(/\d\.\d{3} \[\d\.\d{3}, \d\.\d{3}\]/);
  const summaryBox = await page.getByTestId("r10-summary").boundingBox();
  const tableBox = await page.getByTestId("r10-primary").boundingBox();
  expect(summaryBox!.y).toBeLessThan(tableBox!.y);
  await expect(page.getByTestId("r10-chart").locator(".js-plotly-plot")).toBeVisible();
});

test("FR-D91: Run starts the job and polls it to a result", async ({ page }) => {
  await openAdmin(page);
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByTestId("r10-status")).toContainText(/queued|running/);
  await expect(page.getByTestId("r10-status")).toHaveText("Status: succeeded", { timeout: 20_000 });
  await expect(page.getByTestId("r10-primary")).toBeVisible();
});

test("FR-D93: every admin view of a tenant's rings and verdicts is read-only and labelled", async ({ page }) => {
  await signIn(page, USERS.admin);
  for (const path of ["/rings", "/rings/full-gine_causal-1-0", "/verdicts", "/drift"]) {
    await go(page, path);
    await expect(page.getByText("Read-only (administrator)")).toBeVisible();
  }
  await go(page, "/rings");
  await expect(page.getByTestId("ring-row").first()).toBeVisible();
  for (const button of await page.getByTestId("ring-row").getByRole("button").all()) await expect(button).toBeDisabled();
  await go(page, "/rings/full-gine_causal-1-0");
  for (const name of ["Confirm ring", "Reject ring", "Partially correct"]) await expect(page.getByRole("button", { name })).toBeDisabled();
});
