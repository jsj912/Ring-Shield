/** Ring detail: FR-D20-21, D30-34, D36, D40-42, D103, NFR-D32, and overrides 1-3. */
import { expect, test, type Page } from "@playwright/test";
import { FIXTURE_API, USERS, go, signIn } from "./helpers";

test.beforeEach(async ({ request }) => {
  await request.post(`${FIXTURE_API}/__reset`);
});

async function fixtureRing(request: import("@playwright/test").APIRequestContext, ringId: string) {
  const login = await request.post(`${FIXTURE_API}/auth/login`, { data: { email: USERS.analystA[0], password: USERS.analystA[1] } });
  const headers = { Authorization: `Bearer ${(await login.json()).token}` };
  const get = async (part: string) => (await request.get(`${FIXTURE_API}/tenants/1001/rings/${ringId}${part}`, { headers })).json();
  return { detail: await get(""), explanation: await get("/explanation"), subgraph: await get("/subgraph") };
}

async function openRing(page: Page, ringId: string) {
  await signIn(page, USERS.analystA);
  await go(page, `/rings/${ringId}`);
  await expect(page.getByRole("heading", { name: new RegExp(ringId) })).toBeVisible();
}

interface DrawnNode { id: string; colour: string; shape: string; w: number; size: number }
interface DrawnEdge { id: string; source: string; target: string; dash: string; width: number; later: boolean }

/** The Cytoscape instance behind the graph panel (read-only inspection). */
async function graph(page: Page): Promise<{ nodes: DrawnNode[]; edges: DrawnEdge[] }> {
  await expect(page.getByTestId("ring-graph").locator("canvas").first()).toBeVisible();
  return page.evaluate(() => {
    const element = document.querySelector('[data-testid="ring-graph"]') as HTMLElement & { _cyreg?: { cy: any } };
    const cy = element._cyreg!.cy;
    return {
      nodes: cy.nodes().map((n: any) => ({ id: n.id(), colour: n.data("colour"), shape: n.data("shape"), w: n.data("w"), size: n.renderedWidth() / cy.zoom() })),
      edges: cy.edges().map((e: any) => ({ id: e.id(), source: e.data("source"), target: e.data("target"), dash: e.style("line-style"), width: e.data("width"), later: e.hasClass("later") })),
    };
  });
}

test("FR-D20: narrative byte for byte, then the summary", async ({ page, request }) => {
  const { explanation, detail } = await fixtureRing(request, "full-gine_causal-1-0");
  await openRing(page, "full-gine_causal-1-0");
  expect(await page.getByTestId("narrative").textContent()).toBe(explanation.narrative);
  const summary = page.locator("dl");
  await expect(summary).toContainText(`${detail.topology_type} (p = ${detail.topology_prob})`);   // as received
  await expect(summary).toContainText("90,757.05 US Dollar");
  await expect(summary).toContainText("84.6%");                                                  // closure as a percentage
  await expect(summary).toContainText(detail.window_text);
  await expect(page.getByText(`Model ${detail.model_id} · aggregator ${detail.aggregator_id}`)).toBeVisible();
});

test("overrides 2 and 3: partial total flagged, never converted; closed loop not a percentage", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-4");                    // CYCLE: no source or sink, partial total
  const summary = page.locator("dl");
  await expect(summary).toContainText("148,411.83 US Dollar (partial)");
  await expect(summary.getByText("closed loop")).toBeVisible();
  await expect(summary).not.toContainText(/Conservation closure\s*[\d.]+%/);
});

test("FR-D21: status badge and the latest verdict with author and time", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-1");                    // FAN-IN, confirmed in the fixtures
  await expect(page.getByTestId("status-badge")).toHaveText("confirmed");
  await expect(page.getByTestId("latest-verdict")).toContainText(/by .+ at \d{4}-\d{2}-\d{2}/);
});

test("FR-D30-32: direction, role colour and size, edge width and line style, legend", async ({ page, request }) => {
  const { subgraph } = await fixtureRing(request, "full-gine_causal-1-5");
  await openRing(page, "full-gine_causal-1-5");                    // has an undetermined account
  const drawn = await graph(page);
  const shown = subgraph.edges.filter((e: any) => !e.is_conversion);
  expect(drawn.edges).toHaveLength(shown.length);                  // conversions hidden by default
  for (const edge of shown) {
    const mine = drawn.edges.find((e) => e.id === `e${edge.edge_id}`)!;
    expect([mine.source, mine.target]).toEqual([`n${edge.from_id}`, `n${edge.to_id}`]);   // payer -> payee
    expect(mine.dash).toBe(edge.is_seed ? "solid" : "dashed");
  }
  const undetermined = subgraph.nodes.find((n: any) => n.role === "undetermined");
  const mule = subgraph.nodes.find((n: any) => n.role === "mule");
  const colour = (id: number) => drawn.nodes.find((n) => n.id === `n${id}`)!.colour;
  expect(colour(undetermined.account_id)).not.toBe(colour(mule.account_id));
  const sizes = drawn.nodes.map((n) => n.w);
  expect(new Set(sizes).size).toBeGreaterThan(1);                  // size follows w_account
  const legend = page.getByTestId("legend-role");
  await expect(legend).toHaveText(["●source", "■sink", "◆mule", "▲holder", "○peripheral", "★undetermined"]);
  await expect(page.getByLabel("Legend")).toContainText("seed transaction");
  await expect(page.getByLabel("Legend")).toContainText("expanded transaction");
});

test("override 2: the currency-conversion toggles on the graph and the transactions tab", async ({ page, request }) => {
  const { subgraph } = await fixtureRing(request, "full-gine_causal-1-5");
  await openRing(page, "full-gine_causal-1-5");
  const before = (await graph(page)).edges.length;
  const rows = await page.getByTestId("transaction-row").count();
  await page.getByLabel("Show currency conversions", { exact: true }).click();
  await expect.poll(async () => (await graph(page)).edges.length).toBe(subgraph.edges.length);
  expect(subgraph.edges.length).toBeGreaterThan(before);
  await page.getByLabel("Show currency conversions in evidence").click();
  await expect(page.getByTestId("transaction-row")).toHaveCount(rows + 1);
  await expect(page.getByTestId("transaction-row").filter({ hasText: "conversion" })).toHaveCount(1);
});

test("FR-D33: hover on a node and an edge shows every listed field", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-0");
  await graph(page);
  const hover = async (selector: string) => page.evaluate((sel) => {
    const element = document.querySelector('[data-testid="ring-graph"]') as HTMLElement & { _cyreg?: { cy: any } };
    element._cyreg!.cy.$(sel).first().emit("mouseover");
  }, selector);
  await hover("node");
  const tip = page.getByRole("tooltip");
  for (const field of ["Account", "Bank:", "Role:", "Inflow:", "Outflow:", "Hold time:"]) await expect(tip).toContainText(field);
  await hover("edge");
  for (const field of ["Amount:", "Time:", "Payment format:", "w_total", "w_score", "w_loo", "w_flow"]) await expect(tip).toContainText(field);
});

test("FR-D34: slider at the midpoint greys later edges; play runs to the end", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-8");
  await graph(page);
  expect((await graph(page)).edges.some((e) => e.later)).toBe(false);          // starts at the end
  const thumb = page.getByRole("slider").last();
  await thumb.focus();
  await page.keyboard.press("Home");
  for (let i = 0; i < 9; i += 1) await page.keyboard.press("ArrowRight");     // stop 10 of 20
  const middle = await graph(page);
  expect(middle.edges.some((e) => e.later)).toBe(true);
  expect(middle.edges.some((e) => !e.later)).toBe(true);
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible({ timeout: 8000 });
  expect((await graph(page)).edges.some((e) => e.later)).toBe(false);
});

test("FR-D36: a 120-account ring shows 60 with a banner and a load-all button", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-8");
  await expect(page.getByTestId("node-cap-banner")).toHaveText("Showing 60 of 120 accounts");
  expect((await graph(page)).nodes).toHaveLength(60);
  await page.getByRole("button", { name: "Load all accounts" }).click();
  await expect.poll(async () => (await graph(page)).nodes.length).toBe(120);
  await expect(page.getByTestId("node-cap-banner")).toHaveCount(0);
});

test("FR-D40-42: the three evidence tabs", async ({ page, request }) => {
  const { explanation } = await fixtureRing(request, "full-gine_causal-1-0");
  await openRing(page, "full-gine_causal-1-0");
  for (const header of ["From", "To", "Amount", "Time", "Payment format", "Kind", "w_total", "w_score", "w_loo", "w_flow"]) {
    await expect(page.getByRole("columnheader", { name: header, exact: true })).toBeVisible();
  }
  const wTotals = await page.getByTestId("transaction-row").evaluateAll((rows) => rows.map((r) => Number(r.children[6].textContent)));
  expect(wTotals).toEqual([...wTotals].sort((a, b) => b - a));

  await page.getByRole("tab", { name: "Accounts" }).click();
  for (const header of ["Account", "Bank", "Role", "Inflow", "Outflow", "Hold time", "w_account"]) {
    await expect(page.getByRole("columnheader", { name: header, exact: true })).toBeVisible();
  }
  const wAccounts = await page.getByTestId("account-row").evaluateAll((rows) => rows.map((r) => Number(r.children[6].textContent)));
  expect(wAccounts).toEqual([...wAccounts].sort((a, b) => b - a));

  await page.getByRole("tab", { name: "Detector signals" }).click();
  await expect(page.getByText("Signals from the transaction-level detector on the ring's seed transactions")).toBeVisible();
  const expected = explanation.feature_weights.slice(0, 10).map((f: any) => f.display_name);
  const ticks = page.locator('[data-testid="signals-chart"] .ytick text');
  await expect(ticks).toHaveCount(expected.length);                    // the chart loads lazily
  const labels = await ticks.allTextContents();
  expect(new Set(labels)).toEqual(new Set(expected));
  expect(labels).toHaveLength(Math.min(10, explanation.feature_weights.length));
});

test("FR-D103: a cross-bank ring names the counter-party banks and nothing else about them", async ({ page }) => {
  await openRing(page, "full-gine_causal-1-9");
  await expect(page.locator("dl")).toContainText("Bank 9101, Bank 9103, Bank 9105");
  await expect(page.getByText(/Cross-bank: Bank 9101/)).toBeVisible();
});

test("NFR-D32: a failing subgraph leaves the narrative and evidence up", async ({ page }) => {
  await page.route(/\/subgraph$/, (route) => route.fulfill({
    status: 500, contentType: "application/json", headers: { "X-Request-ID": "req-graph-500" },
    body: JSON.stringify({ error: "internal", message: "subgraph too large", request_id: "req-graph-500" }),
  }));
  await openRing(page, "full-gine_causal-1-0");
  await expect(page.getByText(/subgraph too large/)).toBeVisible();
  await expect(page.getByText(/req-graph-500/)).toBeVisible();
  await expect(page.getByTestId("narrative")).toBeVisible();
  await expect(page.getByTestId("transaction-row").first()).toBeVisible();
});
