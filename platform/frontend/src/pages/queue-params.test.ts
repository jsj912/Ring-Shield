import { describe, expect, it } from "vitest";
import { DEFAULT_RING_FILTERS } from "@/app/workspace";
import { ringParams, withNextCursor } from "./queue-params";
import { verdictFilterParams } from "./VerdictsPage";

describe("ring queue query", () => {
  it("defaults to open rings by confidence, 50 per page", () => {
    expect(ringParams(DEFAULT_RING_FILTERS, { cursors: [null], page: 0 })).toEqual([
      ["status", "open"], ["min_conf", "0"], ["cross_bank_only", "false"], ["sort", "confidence"], ["order", "desc"], ["limit", "50"],
    ]);
  });

  it("repeats multi-select filters and sends the page's cursor", () => {
    const params = ringParams(
      { ...DEFAULT_RING_FILTERS, status: ["open", "partial"], topology_type: ["CYCLE"], q: "1001000003", cross_bank_only: true },
      { cursors: [null, "50"], page: 1 },
    );
    expect(params.filter(([key]) => key === "status").map(([, value]) => value)).toEqual(["open", "partial"]);
    expect(params).toContainEqual(["topology_type", "CYCLE"]);
    expect(params).toContainEqual(["q", "1001000003"]);
    expect(params).toContainEqual(["cross_bank_only", "true"]);
    expect(params).toContainEqual(["cursor", "50"]);
  });

  it("remembers each next cursor once", () => {
    const first = withNextCursor({ cursors: [null], page: 0 }, "50");
    expect(first.cursors).toEqual([null, "50"]);
    expect(withNextCursor(first, "50")).toBe(first);
  });
});

describe("verdict history query", () => {
  it("sends only the filters that are set", () => {
    expect(verdictFilterParams({ verdict: [], analyst_id: null, simulated: null, since: null, until: null })).toEqual([]);
    expect(verdictFilterParams({
      verdict: ["confirm", "partial"], analyst_id: 2, simulated: false, since: "2022-09-10T00:00:00+00:00", until: null,
    })).toEqual([["verdict", "confirm"], ["verdict", "partial"], ["analyst_id", "2"], ["simulated", "false"], ["since", "2022-09-10T00:00:00+00:00"]]);
  });
});
