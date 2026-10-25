/** Verdict form: FR-D50-55, NFR-D13, NFR-D31. */
import { expect, test, type Page } from "@playwright/test";
import { FIXTURE_API, USERS, apiRequests, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

async function openRing(page: Page, ringId: string, user: readonly [string, string] = USERS.analystA) {
  await signIn(page, user);
  await go(page, `/rings/${ringId}`);
  await expect(page.getByRole("heading", { name: new RegExp(ringId) })).toBeVisible();
}

const nodeCount = (page: Page) => page.evaluate(() => {
  const element = document.querySelector('[data-testid="ring-graph"]') as HTMLElement & { _cyreg?: { cy: any } };
  return element._cyreg ? element._cyreg.cy.nodes().length : -1;
});

test("FR-D50, FR-D51: partial needs a note, a removal and at least one account", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0");
  await page.getByRole("button", { name: "Partially correct" }).click();
  const accounts = page.getByRole("checkbox", { name: /^Keep account/ });
  await expect(accounts.first()).toBeChecked();                                  // pre-ticked from the ring
  await page.getByRole("button", { name: "Submit partial verdict" }).click();
  await expect(page.getByText("Remove at least one account or transaction")).toBeVisible();

  await accounts.first().click();
  await page.getByRole("button", { name: "Submit partial verdict" }).click();
  await expect(page.getByText("A note is required for a partial verdict.")).toBeVisible();

  for (const box of await accounts.all()) if (await box.isChecked()) await box.click();
  await page.getByLabel("Note (required for partial)").fill("untick all");
  await page.getByRole("button", { name: "Submit partial verdict" }).click();
  await expect(page.getByText("Keep at least one account for a partial correction.")).toBeVisible();
  await expect(page.getByTestId("status-badge")).toHaveText("open");            // nothing was sent
});

test("FR-D52: a partial verdict regenerates the ring: graph, narrative, evidence and status", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0");
  await expect.poll(() => nodeCount(page)).toBe(6);
  const before = await page.getByTestId("narrative").textContent();
  const accountRows = await page.getByRole("tab", { name: "Accounts" }).click().then(() => page.getByTestId("account-row").count());
  await page.getByRole("button", { name: "Partially correct" }).click();
  await page.getByRole("checkbox", { name: /^Keep account/ }).last().click();
  await page.getByLabel("Note (required for partial)").fill("last account is a bystander");
  await page.getByRole("button", { name: "Submit partial verdict" }).click();

  await expect(page.getByText("Explanation regenerated for the corrected ring.")).toBeVisible();
  await expect(page.getByTestId("status-badge")).toHaveText("partial");
  await expect(page.getByTestId("ring-verdict-row").first()).toContainText("last account is a bystander");
  await expect(page.getByTestId("narrative")).not.toHaveText(before!);
  await expect(page.getByTestId("narrative")).toContainText("Regenerated after the analyst's correction.");
  await expect.poll(() => nodeCount(page)).toBe(5);
  await expect(page.getByTestId("account-row")).toHaveCount(accountRows - 1);
});

test("FR-D53: a double click records one verdict", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0");
  const requests = apiRequests(page);
  await page.getByRole("button", { name: /Confirm ring/ }).dblclick();
  await expect(page.getByText("Verdict recorded")).toBeVisible();
  expect(requests.filter((r) => r.method() === "POST" && r.url().endsWith("/verdicts"))).toHaveLength(1);
});

test("FR-D54: simulated verdicts carry the 'Simulated' tag", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-10");
  await expect(page.getByTestId("ring-verdict-row").filter({ hasText: "Simulated" }).first()).toBeVisible();
});

test("FR-D55: the administrator's form is disabled with the message", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0", USERS.admin);
  await expect(page.getByText("Administrators cannot record verdicts.").last()).toBeVisible();
  for (const name of ["Confirm ring", "Reject ring", "Partially correct"]) {
    await expect(page.getByRole("button", { name })).toBeDisabled();
  }
});

test("NFR-D13: a note with markup is shown as text", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0");
  const note = "<script>window.__pwned = 1</script> **bold** <b>tag</b>";
  await page.getByLabel(/Note \(optional/).fill(note);
  await page.getByRole("button", { name: /Reject ring/ }).click();
  await expect(page.getByTestId("ring-verdict-row").first()).toContainText(note);
  expect(await page.evaluate(() => (window as any).__pwned)).toBeUndefined();
  await expect(page.getByTestId("ring-verdict-row").first().locator("b, strong, script")).toHaveCount(0);
});

test("NFR-D31: a failed submission keeps the entries and retries", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0");
  let fail = true;
  await page.route(/\/verdicts$/, (route) => {
    if (route.request().method() === "POST" && fail) {
      fail = false;
      return route.fulfill({ status: 500, contentType: "application/json", headers: { "X-Request-ID": "req-verdict-500" },
        body: JSON.stringify({ error: "internal", message: "database unavailable", request_id: "req-verdict-500" }) });
    }
    return route.fallback();
  });
  await page.getByRole("button", { name: "Partially correct" }).click();
  await page.getByRole("checkbox", { name: /^Keep account/ }).last().click();
  await page.getByLabel("Note (required for partial)").fill("keep me");
  await page.getByRole("button", { name: "Submit partial verdict" }).click();
  await expect(page.getByText(/database unavailable.*req-verdict-500/)).toBeVisible();
  await expect(page.getByLabel("Note (required for partial)")).toHaveValue("keep me");
  await expect(page.getByRole("checkbox", { name: /^Keep account/ }).last()).not.toBeChecked();
  await page.getByRole("button", { name: "Submit partial verdict" }).click();
  await expect(page.getByTestId("status-badge")).toHaveText("partial");
});
