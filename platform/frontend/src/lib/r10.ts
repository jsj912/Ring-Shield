/**
 * The registered R10 result as tables (app.py::_r10_primary_table, _r10_robustness_table). Every
 * cell is a value the API sent, formatted; per-tenant cells are a lookup, never a computation.
 */
import type { R10Interval, R10PerTenant, R10Results } from "@/api/types";
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
