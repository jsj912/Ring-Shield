/** Ring queue: FR-D10-15, and a ring of another bank by URL (demonstration checklist, line 2). */
import { expect, test, type Page } from "@playwright/test";
import { FIXTURE_API, USERS, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

const total = (page: Page) => page.getByTestId("ring-total");
const rows = (page: Page) => page.getByTestId("ring-row");
const firstRingId = async (page: Page) => (await rows(page).first().locator("td").first().textContent())?.trim();

async function applyFilters(page: Page) {
  await page.getByRole("button", { name: "Apply filters" }).click();
}

async function allStatuses(page: Page) {
  await page.getByRole("button", { name: "Status" }).click();
  for (const status of ["confirmed", "rejected", "partial"]) {
    await page.getByRole("menuitemcheckbox", { name: status }).click();
  }
  await page.keyboard.press("Escape");
  await applyFilters(page);
}

test("FR-D10: every column is present with values", async ({ page }) => {
  await signIn(page, USERS.analystA);
  for (const header of ["Ring ID", "Type", "Members / edges", "Total", "Window", "Confidence", "Cross-bank", "Status"]) {
    await expect(page.getByRole("columnheader", { name: header })).toBeVisible();
  }
  const first = rows(page).first();
  await expect(first).toContainText("p = ");                        // topology_prob as the API returns it
  await expect(first).toContainText(/over [\d.]+ (h|d|min)/);           // window_text
  await expect(first.getByText(/^(open|confirmed|rejected|partial)$/)).toBeVisible();
});

test("FR-D11: confidence descending by default; headers re-sort", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await expect(page.getByRole("columnheader", { name: "Confidence" })).toHaveAttribute("aria-sort", "descending");
  const top = await firstRingId(page);
  await page.getByRole("button", { name: "Confidence" }).click();
  await expect(page.getByRole("columnheader", { name: "Confidence" })).toHaveAttribute("aria-sort", "ascending");
  await expect.poll(() => firstRingId(page)).not.toBe(top);
  for (const header of ["Total", "Window", "Members / edges"]) {
    const before = await firstRingId(page);
    await page.getByRole("button", { name: header }).click();
    await expect(page.getByRole("columnheader", { name: header })).toHaveAttribute("aria-sort", "descending");
    await expect.poll(() => firstRingId(page)).not.toBe(before);
  }
});

test("FR-D12: each filter narrows the list and filters combine", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await expect(total(page)).toHaveText("104 rings match these filters");      // default: open only
  await allStatuses(page);
  await expect(total(page)).toHaveText("200 rings match these filters");

  await page.getByRole("button", { name: "Topology" }).click();
  await page.getByRole("menuitemcheckbox", { name: "CYCLE" }).click();
  await page.keyboard.press("Escape");
  await applyFilters(page);
  const cycles = Number((await total(page).textContent())!.split(" ")[0]);
  expect(cycles).toBeLessThan(200);

  await page.getByLabel("Cross-bank only").click();
  await applyFilters(page);
  await expect(page.getByText("No rings match these filters")).toBeVisible();   // the cross-bank ring is SCATTER-GATHER

  await page.getByLabel("Reset filters").click();
  await page.getByLabel("Cross-bank only").click();
  await applyFilters(page);
  await expect(total(page)).toHaveText("1 rings match these filters");
  await expect(rows(page).first()).toContainText("Yes");

  await page.getByLabel("Reset filters").click();
  await page.getByLabel("Start from").fill("2030-01-01");
  await applyFilters(page);
  await expect(page.getByText("No rings match these filters")).toBeVisible();

  await page.getByLabel("Reset filters").click();
  const slider = page.getByRole("slider").first();                    // Radix puts the role on the thumb
  await slider.focus();
  await page.keyboard.press("End");                                    // 1.00
  await applyFilters(page);
  await expect(page.getByText("No rings match these filters")).toBeVisible();
});

test("FR-D13: pages of 50 through the API cursor, with the total", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await allStatuses(page);
  await expect(total(page)).toHaveText("200 rings match these filters");
  const next = page.getByRole("button", { name: "Next page" });
  const seen = new Set<string>();
  for (let index = 1; index <= 4; index += 1) {
    await expect(page.getByText(`Page ${index}`, { exact: true })).toBeVisible();
    await expect(rows(page)).toHaveCount(50);
    seen.add((await firstRingId(page))!);
    if (index < 4) await next.click();
  }
  expect(seen.size).toBe(4);
  await expect(next).toBeDisabled();
});

test("FR-D14: returning from a ring restores filters and page", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await allStatuses(page);
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
  const ring = await firstRingId(page);
  await rows(page).first().click();
  await expect(page).toHaveURL(new RegExp(`/rings/${ring}$`));
  await page.getByRole("link", { name: "Back to queue" }).click();
  await expect(page.getByText("Page 2", { exact: true })).toBeVisible();
  await expect(total(page)).toHaveText("200 rings match these filters");
  expect(await firstRingId(page)).toBe(ring);
});

test("FR-D15: the two empty states", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await page.getByLabel("Search ring ID or account ID").fill("no-such-ring");
  await applyFilters(page);
  await expect(page.getByText("No rings match these filters")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, ["analyst@bank-c.fixture", "fixture-only-c1"]);
  await expect(page.getByText("No rings have been generated for this tenant yet")).toBeVisible();
});

test("another bank's ring by URL says 'Not permitted' and shows nothing of it", async ({ page }) => {
  await signIn(page, USERS.analystB);
  await expect(rows(page)).not.toHaveCount(0);
  await go(page, "/rings/full-gine_causal-1-0");                      // a Bank A ring
  await expect(page.getByText("Not permitted")).toBeVisible();
  await expect(page.getByTestId("narrative")).toHaveCount(0);
});
