/** The R10 tables over the real fixture, with the values test_dashboard_admin_r10_fixture.py expects. */
import { describe, expect, it } from "vitest";
import fixture from "../../../dashboard/fixtures/r10_result.json";
import type { R10Results } from "@/api/types";
import { PRIMARY_COLUMNS, r10PrimaryTable, r10RobustnessTable } from "./r10";

const results = fixture as unknown as R10Results;

describe("R10 primary table", () => {
  const table = r10PrimaryTable(results);

  it("has one row per tenant and the pooled row last", () => {
    expect(Object.keys(table[0])).toEqual([...PRIMARY_COLUMNS]);
    expect(table.map((row) => row.Tenant)).toEqual(["1", "20", "11", "118", "12", "All five"]);
    expect(new Set(table.slice(0, 5).map((row) => row.Kind))).toEqual(new Set(["per tenant (descriptive)"]));
  });

  it("puts the confidence intervals on the pooled row only", () => {
    const pooled = table[5];
    expect(pooled.Kind).toBe("pooled across tenants (95% CI)");
    expect(pooled["(b) own scores, own edges"]).toBe("0.088 [0.031, 0.161]");
    expect(pooled.Pooled).toBe("0.359 [0.239, 0.500]");
    expect(pooled["Pooled − (b)"]).toBe("0.271 [0.154, 0.407]");
    const bank1 = table[0];
    expect([bank1["(b) own scores, own edges"], bank1["(a) pooled scores, own edges"], bank1["Budget-matched"], bank1.Pooled])
      .toEqual(["0.035", "0.071", "0.035", "0.365"]);
    expect(bank1["(b) own scores, own edges"]).not.toContain("[");
  });
});

describe("R10 robustness table", () => {
  it("marks bank 70 degenerate and keeps its own pooled row", () => {
    const table = r10RobustnessTable(results);
    expect(table.map((row) => row.Tenant)).toEqual(["70", "12", "11", "1", "10", "All five"]);
    expect(table[0].Note).toBe("degenerate: no ring edges visible");
    expect(table[0]["(b) own scores, own edges"]).toBe("—");
    expect(table[5].Pooled).toBe("0.425 [0.284, 0.589]");
  });
});
