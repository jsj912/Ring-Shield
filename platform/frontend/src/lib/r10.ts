/**
 * The registered R10 result as tables (app.py::_r10_primary_table, _r10_robustness_table). Every
 * cell is a value the API sent, formatted; per-tenant cells are a lookup, never a computation.
 */
import type { R10Interval, R10PerTenant, R10PostHoc, R10Results } from "@/api/types";
import { MISSING, fmtInterval, fmtRecall } from "./formatters";

export const R10_DEGENERATE: Record<number, string> = { 70: "degenerate: no ring edges visible" };

export function r10Interval(part: R10Interval): string {
  return fmtInterval(part.value, part.low, part.high);
}

/** (row, tenant) -> per-tenant record. */
export function r10PerTenant(results: R10Results): Map<string, R10PerTenant> {
  return new Map(results.per_tenant.map((item) => [`${item.row}/${item.tenant_id}`, item]));
}

export const PRIMARY_COLUMNS = ["Tenant", "Kind", "Rings", "Pooled", "(a) pooled scores, own edges",
  "(b) own scores, own edges", "Budget-matched", "Pooled − (b)"] as const;

export const ROBUSTNESS_COLUMNS = ["Tenant", "Kind", "Rings", "Pooled", "(b) own scores, own edges", "Note"] as const;

export type R10Row = Record<string, string>;

/** Change 6: one row per tenant (descriptive), and the CI only on the pooled-across-tenants row. */
export function r10PrimaryTable(results: R10Results): R10Row[] {
  const rows = results.rows, lookup = r10PerTenant(results);
  const table: R10Row[] = rows.primary.tenants.map((tenant) => {
    const b = lookup.get(`primary/${tenant}`);
    return {
      Tenant: String(tenant), Kind: "per tenant (descriptive)", Rings: b ? String(b.n_rings) : MISSING,
      Pooled: fmtRecall(b?.pooled_recall),
      "(a) pooled scores, own edges": fmtRecall(lookup.get(`pooled_scores/${tenant}`)?.tenant_recall),
      "(b) own scores, own edges": fmtRecall(b?.tenant_recall),
      "Budget-matched": fmtRecall(lookup.get(`budget_matched/${tenant}`)?.tenant_recall),
      "Pooled − (b)": MISSING,
    };
  });
  table.push({
    Tenant: "All five", Kind: "pooled across tenants (95% CI)",
    Rings: `${rows.primary.n_rings} rings, ${rows.primary.n_pairs} pairs`,
    Pooled: r10Interval(rows.primary.pooled),
    "(a) pooled scores, own edges": r10Interval(rows.pooled_scores.tenant),
    "(b) own scores, own edges": r10Interval(rows.primary.tenant),
    "Budget-matched": r10Interval(rows.budget_matched.tenant),
    "Pooled − (b)": r10Interval(rows.primary.difference),
  });
  return table;
}

export function r10RobustnessTable(results: R10Results): R10Row[] {
  const row = results.rows.robustness, lookup = r10PerTenant(results);
  const table: R10Row[] = row.tenants.map((tenant) => {
    const item = lookup.get(`robustness/${tenant}`);
    return {
      Tenant: String(tenant), Kind: "per tenant (descriptive)",
      Rings: item ? String(item.n_rings) : MISSING,
      Pooled: item ? fmtRecall(item.pooled_recall) : MISSING,
      "(b) own scores, own edges": item ? fmtRecall(item.tenant_recall) : MISSING,
      Note: R10_DEGENERATE[tenant] ?? "",
    };
  });
  table.push({
    Tenant: "All five", Kind: "pooled across tenants (95% CI)", Rings: `${row.n_rings} rings, ${row.n_pairs} pairs`,
    Pooled: r10Interval(row.pooled), "(b) own scores, own edges": r10Interval(row.tenant),
    Note: "degenerate set: bank 70 has no visible ring laundering edge",
  });
  return table;
}

/** The extras computed after the registered result; every table and caption carries this label. */
export const POST_HOC_LABEL = "post-hoc, descriptive";

const ROW_NAMES: Record<R10PerTenant["row"], string> = {
  primary: "(b) own scores, own edges", pooled_scores: "(a) pooled scores, own edges",
  budget_matched: "Budget-matched", robustness: "Robustness set ((b))",
};

export const COVERAGE_COLUMNS = ["Ring set", "Tenant coverage", "Pooled coverage", "Matched (tenant / pooled)"] as const;

/** Member coverage per registered row, tenant side against pooled side, with the bootstrap CI. */
export function r10CoverageTable(post: R10PostHoc): R10Row[] {
  return (Object.keys(ROW_NAMES) as R10PerTenant["row"][]).map((row) => {
    const cov = post.member_coverage[row];
    return {
      "Ring set": ROW_NAMES[row], "Tenant coverage": r10Interval(cov.tenant), "Pooled coverage": r10Interval(cov.pooled),
      "Matched (tenant / pooled)": `${cov.tenant.n} / ${cov.pooled.n}`,
    };
  });
}

export const AB_COLUMNS = ["Tenants", "Pairs", "(a) pooled scores, own edges", "(b) own scores, own edges", "(a) − (b)"] as const;

export function r10AbTable(post: R10PostHoc): R10Row[] {
  const ab = post.a_vs_b;
  return [{
    Tenants: ab.tenants.join(", "), Pairs: `${ab.n_rings} rings, ${ab.n_pairs} pairs`,
    "(a) pooled scores, own edges": r10Interval(ab.a), "(b) own scores, own edges": r10Interval(ab.b),
    "(a) − (b)": r10Interval(ab.difference),
  }];
}

export const COVERAGE_TENANT_COLUMNS = ["Ring set", "Tenant", "Tenant coverage", "Pooled coverage", "Matched (tenant / pooled)"] as const;

export function r10CoverageTenantTable(post: R10PostHoc): R10Row[] {
  return post.per_tenant.map((item) => ({
    "Ring set": ROW_NAMES[item.row], Tenant: String(item.tenant_id),
    "Tenant coverage": fmtRecall(item.member_coverage_tenant), "Pooled coverage": fmtRecall(item.member_coverage_pooled),
    "Matched (tenant / pooled)": `${item.n_matched_tenant} / ${item.n_matched_pooled}`,
  }));
}

export const VISIBLE_COLUMNS = ["Tenant", "Set", "In-scope rings with a visible laundering edge", "Tenant-ring pairs", "Note"] as const;

export function r10VisibleTable(post: R10PostHoc): R10Row[] {
  return post.visible_laundering.map((item) => ({
    Tenant: String(item.tenant_id), Set: item.sets.join(", "),
    "In-scope rings with a visible laundering edge": String(item.in_scope_rings_with_visible_laundering_edge),
    "Tenant-ring pairs": String(item.tenant_ring_pairs), Note: R10_DEGENERATE[item.tenant_id] ?? "",
  }));
}
