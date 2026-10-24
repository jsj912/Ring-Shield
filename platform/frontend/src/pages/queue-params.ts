import type { Params } from "@/api/types";
import type { Paging, RingFilters } from "@/app/workspace";

/** The query for GET /tenants/{id}/rings, built as app.py::_queue builds it. */
export function ringParams(filters: RingFilters, paging: Paging): Params {
  const params: Params = (filters.status.length ? filters.status : ["open"]).map((value) => ["status", value]);
  filters.topology_type.forEach((value) => params.push(["topology_type", value]));
  const scalars: [string, string | number | boolean | null][] = [
    ["min_conf", filters.min_conf], ["cross_bank_only", filters.cross_bank_only], ["sort", filters.sort],
    ["order", filters.order], ["start_after", filters.start_after], ["start_before", filters.start_before],
    ["q", filters.q],
  ];
  for (const [key, value] of scalars) {
    if (value !== null && value !== undefined) params.push([key, typeof value === "boolean" ? String(value) : String(value)]);
  }
  const cursor = paging.cursors[paging.page];
  if (paging.page > 0 && cursor) params.push(["cursor", cursor]);
  params.push(["limit", "50"]);
  return params;
}

/** Remember the next page's cursor the first time it is seen. */
export function withNextCursor(paging: Paging, nextCursor: string | null): Paging {
  if (!nextCursor || paging.cursors.length > paging.page + 1) return paging;
  return { ...paging, cursors: [...paging.cursors, nextCursor] };
}
