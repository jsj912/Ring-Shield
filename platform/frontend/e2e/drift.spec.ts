/** Drift: FR-D80-82 and override 4 (hourly days 8-9; nothing synthetic or experimental to bank users). */
import { expect, test, type Page, type Response } from "@playwright/test";
import { FIXTURE_API, USERS, apiRequests, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

/** The Plotly traces drawn in a chart (read-only inspection). */
const traces = (page: Page, testId: string) => page.evaluate((id) => {
  const plot = document.querySelector(`[data-testid="${id}"] .js-plotly-plot`) as HTMLElement & { data?: any[] };
  return (plot?.data ?? []).map((t) => ({ name: t.name as string, x: t.x as string[], text: t.text as string[] | undefined }));
}, testId);

function bodies(page: Page): Promise<string>[] {
  const seen: Promise<string>[] = [];
  page.on("response", (response: Response) => {
    if (response.url().startsWith(FIXTURE_API)) seen.push(response.text().catch(() => ""));
  });
  return seen;
}

test("FR-D80, FR-D82: a supervisor sees the hourly days 8-9 series, the event marker and the note", async ({ page }) => {
  await signIn(page, USERS.supervisorA);
  await go(page, "/drift");
  await expect(page.getByText("This monitor detects shifts in the score distribution. It does not by itself indicate a change "
    + "in laundering behaviour and never triggers retraining automatically.")).toBeVisible();
  await expect.poll(async () => (await traces(page, "drift-chart")).length).toBe(3);
  const [mean, p99, events] = await traces(page, "drift-chart");
  expect(mean.name).toBe("Hourly mean");
  expect(p99.name).toBe("Hourly 99th percentile");
  expect(mean.x).toHaveLength(48);
  expect(mean.x[0]).toMatch(/^2022-09-09T00:00/);
  expect(mean.x[47]).toMatch(/^2022-09-10T23:00/);
  expect(events.text![0]).toMatch(/adwin_score_mean.*statistic.*threshold/s);
});

test("FR-D81: the acted-on toggle needs a note, and the flag and note persist", async ({ page }) => {
  await signIn(page, USERS.supervisorA);
  await go(page, "/drift");
  const row = page.getByTestId("drift-event-row").first();
  await row.getByRole("button", { name: "Mark reviewed" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("A note is required to change the acted-on flag.")).toBeVisible();
  await page.getByLabel("Note").fill("checked: overnight batch, no action");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(row).toContainText("Yes");
  await expect(row).toContainText("checked: overnight batch, no action");
  await go(page, "/rings");
  await go(page, "/drift");
  await expect(page.getByTestId("drift-event-row").first()).toContainText("checked: overnight batch, no action");
});

test("override 4: a supervisor never receives the R12 panel, the experiment tenant or the control", async ({ page }) => {
  const requests = apiRequests(page);
  const seen = bodies(page);
  await signIn(page, USERS.supervisorA);
  await go(page, "/drift");
  await expect(page.getByTestId("drift-event-row").first()).toBeVisible();
  await expect(page.getByTestId("r12-panel")).toHaveCount(0);
  expect(requests.filter((r) => r.url().includes("/admin/"))).toEqual([]);
  const text = (await Promise.all(seen)).join("\n");
  expect(text).not.toContain("900001");
  expect(text).not.toContain("SYNTHETIC POSITIVE CONTROL");
  expect(text).not.toContain("synthetic_control");
});

test("FR-D80, FR-D93, override 4: the admin reads drift, read-only, plus the labelled R12 experiment panel", async ({ page }) => {
  await signIn(page, USERS.admin);
  await go(page, "/drift");
  await expect(page.getByText("Read-only (administrator)")).toBeVisible();
  await expect.poll(async () => (await traces(page, "drift-chart")).length).toBe(3);
  await expect(page.getByTestId("drift-event-row").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Mark (un)?reviewed/ })).toHaveCount(0);
  const panel = page.getByTestId("r12-panel");
  await expect(panel).toContainText("R12 experiment");
  await expect(panel).toContainText("experiment / synthetic");
  await expect(panel).toContainText("SYNTHETIC POSITIVE CONTROL");
  await expect.poll(async () => (await traces(page, "r12-chart")).map((t) => t.name)).toEqual(expect.arrayContaining([
    "Real run (experiment): hourly mean", "Control (synthetic): hourly mean",
  ]));
  await expect(panel.getByRole("row", { name: /Amendment A, synthetic control/ })).toBeVisible();
});

test("FR-D05: an analyst cannot open drift and requests nothing", async ({ page }) => {
  const requests = apiRequests(page);
  await signIn(page, USERS.analystA);
  await go(page, "/drift");
  await expect(page.getByText("Not permitted")).toBeVisible();
  expect(requests.filter((r) => r.url().includes("/drift"))).toEqual([]);
});
