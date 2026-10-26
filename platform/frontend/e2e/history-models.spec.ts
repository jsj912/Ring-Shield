/** Verdict history (FR-D60) and models (FR-D70-73, override 5). */
import { expect, test, type Page } from "@playwright/test";
import { FIXTURE_API, USERS, apiRequests, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

const historyRows = (page: Page) => page.getByTestId("verdict-row");
const matching = async (page: Page) => Number((await page.getByText(/verdicts match these filters/).textContent())!.split(" ")[0]);

async function chooseSelect(page: Page, label: string, option: string) {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}

test("FR-D60: columns, newest first, each filter narrows, the link opens the ring", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await go(page, "/verdicts");
  for (const header of ["When", "Ring ID", "Verdict", "Analyst", "Note"]) {
    await expect(page.getByRole("columnheader", { name: header })).toBeVisible();
  }
  await expect(historyRows(page).first()).toBeVisible();
  const times = await historyRows(page).evaluateAll((rows) => rows.map((r) => r.children[0].getAttribute("title") ?? ""));
  expect(times).toEqual([...times].sort().reverse());                    // ISO UTC on hover: newest first
  await expect(historyRows(page).filter({ hasText: "Simulated" }).first()).toBeVisible();
  const all = await matching(page);

  const apply = () => page.getByRole("button", { name: "Apply verdict filters" }).click();
  await page.getByRole("button", { name: "Verdict type" }).click();
  await page.getByRole("menuitemcheckbox", { name: "reject" }).click();
  await page.keyboard.press("Escape");
  await apply();
  await expect.poll(() => matching(page)).toBeLessThan(all);
  for (const row of await historyRows(page).all()) await expect(row).toContainText(/reject/i);
  const rejected = await matching(page);

  await chooseSelect(page, "Simulated or real", "Real");
  await apply();
  await expect.poll(() => matching(page)).toBeLessThanOrEqual(rejected);
  await expect(historyRows(page).filter({ hasText: "Simulated" })).toHaveCount(0);

  await page.getByLabel("From (UTC day)").fill("2030-01-01");
  await apply();
  await expect(page.getByText("No verdicts match these filters")).toBeVisible();

  await page.getByLabel("From (UTC day)").fill("");
  await chooseSelect(page, "Simulated or real", "All");
  await page.getByRole("combobox", { name: "Analyst" }).click();
  const analysts = page.getByRole("option");
  const label = (await analysts.nth(1).textContent())!;
  await analysts.nth(1).click();
  await apply();
  for (const row of await historyRows(page).all()) await expect(row).toContainText(label);

  const ring = (await historyRows(page).first().locator("td").nth(1).textContent())!.trim();
  await historyRows(page).first().click();
  await expect(page).toHaveURL(new RegExp(`/rings/${ring}\\?bank=\\d+$`));
  await expect(page.getByRole("heading", { name: new RegExp(ring) })).toBeVisible();
});

test("FR-D70: versions newest first, promoted highlighted, a refused version shows its reason", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await go(page, "/models");
  const rows = page.getByTestId("model-row");
  await expect(rows.first()).toBeVisible();
  for (const header of ["Component", "Version", "Trained at", "Training labels", "Holdout ring-F1", "Promoted", "Gate reason"]) {
    await expect(page.getByRole("columnheader", { name: header, exact: true })).toBeVisible();
  }
  const trained = await rows.evaluateAll((all) => all.map((r) => r.children[3].getAttribute("title") ?? ""));
  expect(trained).toEqual([...trained].sort().reverse());
  const refused = rows.filter({ hasText: "No" }).filter({ hasText: /holdout|ring_f1|gate/i });
  await expect(refused.first()).toBeVisible();
  await expect(rows.filter({ hasText: "Yes" }).first()).toHaveClass(/bg-success/);
});

test("FR-D71: analysts have no retrain button", async ({ page }) => {
  await signIn(page, USERS.analystA);
  await go(page, "/models");
  await expect(page.getByTestId("model-row").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Retrain now" })).toHaveCount(0);
});

test("FR-D71, override 5: the confirmation states the scope and the gate, and shows R11", async ({ page }) => {
  await signIn(page, USERS.supervisorA);
  await go(page, "/models");
  await page.getByRole("button", { name: "Retrain now" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Retrains the expansion and affinity models; the typing model is fixed. "
    + "The result is promoted only if it passes the holdout gate.");
  await expect(dialog.getByTestId("r11-lane")).toHaveCount(2);
  await expect(dialog).toContainText("simulated verdicts");
  await expect(dialog).toContainText("affinity 0.6556 refused; expansion 0.6612 refused");
  await expect(dialog).toContainText("Every verdict in R11 is simulated");
});

test("FR-D72, FR-D73: the run is polled every 5 s to the end; refusals show the reason and link to the row", async ({ page }) => {
  await signIn(page, USERS.supervisorA);
  await go(page, "/models");
  const requests = apiRequests(page);
  await page.getByRole("button", { name: "Retrain now" }).click();
  await page.getByRole("button", { name: "Start retraining" }).click();
  const started = page.getByText(/^Run fixture-run-\d+:$/);
  await expect(started).toBeVisible();
  const runId = (await started.textContent())!.replace(/^Run |:$/g, "");
  const pollsOf = () => requests.filter((r) => r.url().endsWith(`/retrain/${runId}`));
  await expect(page.getByText("running").first()).toBeVisible();
  await expect(page.getByText("labels: 7 verdicts")).toBeVisible();                   // log tail open
  const refusal = page.getByRole("alert").filter({ hasText: "refused by the holdout gate" });
  await expect(refusal.first()).toBeVisible({ timeout: 20_000 });
  await expect(refusal.filter({ hasText: runId }).first()).toContainText("holdout ring_f1 0.6601 < current 0.6883 - 0.005");
  const polls = pollsOf().length;
  expect(polls).toBeGreaterThanOrEqual(2);
  await page.waitForTimeout(6000);
  expect(pollsOf().length).toBe(polls);                                             // polling stopped when finished

  const show = refusal.first().getByRole("button", { name: /Show model version/ });
  const id = (await show.textContent())!.match(/\d+/)![0];
  await show.click();
  const row = page.getByTestId("model-row").filter({ has: page.getByRole("cell", { name: id, exact: true }) });
  await expect(row).toHaveClass(/bg-warning/);
});
