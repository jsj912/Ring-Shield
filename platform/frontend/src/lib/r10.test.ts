/** The R10 tables over the real fixture, with the values test_dashboard_admin_r10_fixture.py expects. */
import { describe, expect, it } from "vitest";
import fixture from "../../../dashboard/fixtures/r10_result.json";
import type { R10Results } from "@/api/types";
import {
  AB_COLUMNS, COVERAGE_COLUMNS, POST_HOC_LABEL, PRIMARY_COLUMNS, R10_DEGENERATE, VISIBLE_COLUMNS, r10AbTable, r10CoverageTable,
  r10CoverageTenantTable, r10PrimaryTable, r10RobustnessTable, r10VisibleTable,
} from "./r10";

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

describe("R10 post-hoc extras", () => {
  const post = results.post_hoc!;

  it("are labelled post-hoc and descriptive, and reuse the registered ring sets", () => {
    expect(post.label).toBe(POST_HOC_LABEL);
    expect(POST_HOC_LABEL).toBe("post-hoc, descriptive");
    expect(post.registered_commit).toBe("3156d75");
    expect(post.registered_reproduced).toBe(true);
    expect(post.ring_sets_reused).toBe(90);
  });

  it("shows member coverage per ring set as sent, with its interval", () => {
    const table = r10CoverageTable(post);
    expect(Object.keys(table[0])).toEqual([...COVERAGE_COLUMNS]);
    expect(table.map((row) => row["Ring set"])).toEqual(
      ["(b) own scores, own edges", "(a) pooled scores, own edges", "Budget-matched", "Robustness set ((b))"]);
    expect(table[0]["Tenant coverage"]).toBe("0.874 [0.781, 0.944]");
    expect(table[0]["Pooled coverage"]).toBe("0.933 [0.886, 0.969]");
    expect(table[0]["Matched (tenant / pooled)"]).toBe("30 / 122");
  });

  it("shows (a) against (b) with the difference the API sent", () => {
    const [row] = r10AbTable(post);
    expect(Object.keys(row)).toEqual([...AB_COLUMNS]);
    expect(row["(a) pooled scores, own edges"]).toBe("0.121 [0.053, 0.200]");
    expect(row["(b) own scores, own edges"]).toBe("0.088 [0.030, 0.159]");
    expect(row["(a) − (b)"]).toBe("0.032 [-0.012, 0.088]");
  });

  it("counts in-scope rings with a visible laundering edge, bank 70 flagged", () => {
    const table = r10VisibleTable(post);
    expect(Object.keys(table[0])).toEqual([...VISIBLE_COLUMNS]);
    const bank70 = table.find((row) => row.Tenant === "70")!;
    expect(bank70["In-scope rings with a visible laundering edge"]).toBe("0");
    expect(bank70.Note).toBe(R10_DEGENERATE[70]);
    expect(table.find((row) => row.Tenant === "1")!["In-scope rings with a visible laundering edge"]).toBe("17");
  });

  it("shows a dash for a tenant with no matched ring", () => {
    const rows = r10CoverageTenantTable({ ...post, per_tenant: [{ ...post.per_tenant[0], member_coverage_tenant: null, n_matched_tenant: 0 }] });
    expect(rows[0]["Tenant coverage"]).toBe("—");
  });
});
