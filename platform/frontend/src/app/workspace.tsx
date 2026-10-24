/**
 * Per-session UI state that must survive navigation: the admin's selected tenant, and the ring
 * queue's applied filters, cursors and page (FR-D14: returning from a ring restores them). It is
 * in memory and is dropped on sign out with the rest of the session.
 */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { SessionResponse } from "@/api/types";

export interface RingFilters {
  status: string[];
  topology_type: string[];
  q: string | null;
  min_conf: number;
  cross_bank_only: boolean;
  sort: "confidence" | "total_amount" | "start_time" | "members";
  order: "desc" | "asc";
  start_after: string | null;
  start_before: string | null;
}

export const DEFAULT_RING_FILTERS: RingFilters = {
  status: ["open"], topology_type: [], q: null, min_conf: 0, cross_bank_only: false,
  sort: "confidence", order: "desc", start_after: null, start_before: null,
};

export interface Paging {
  cursors: (string | null)[];
  page: number;
}

export interface VerdictFilters {
  verdict: string[];
  analyst_id: number | null;
  simulated: boolean | null;
  since: string | null;
  until: string | null;
}

export const DEFAULT_VERDICT_FILTERS: VerdictFilters = {
  verdict: [], analyst_id: null, simulated: null, since: null, until: null,
};

interface Workspace {
  selectedTenant: number | null;
  setSelectedTenant: (tenantId: number | null) => void;
  ringFilters: RingFilters;
  setRingFilters: (filters: RingFilters) => void;
  ringPaging: Paging;
  setRingPaging: (paging: Paging) => void;
  verdictFilters: VerdictFilters;
  setVerdictFilters: (filters: VerdictFilters) => void;
  verdictPaging: Paging;
  setVerdictPaging: (paging: Paging) => void;
}

const WorkspaceContext = createContext<Workspace | null>(null);
const FIRST_PAGE: Paging = { cursors: [null], page: 0 };

export function WorkspaceProvider({ session, children }: { session: SessionResponse | null; children: ReactNode }) {
  const [selectedTenant, setSelectedTenant] = useState<number | null>(null);
  const [ringFilters, setRingFiltersState] = useState<RingFilters>(DEFAULT_RING_FILTERS);
  const [ringPaging, setRingPaging] = useState<Paging>(FIRST_PAGE);
  const [verdictFilters, setVerdictFiltersState] = useState<VerdictFilters>(DEFAULT_VERDICT_FILTERS);
  const [verdictPaging, setVerdictPaging] = useState<Paging>(FIRST_PAGE);

  const token = session?.token ?? null;
  useEffect(() => {                                               // a new session starts clean
    setSelectedTenant(null);
    setRingFiltersState(DEFAULT_RING_FILTERS);
    setRingPaging(FIRST_PAGE);
    setVerdictFiltersState(DEFAULT_VERDICT_FILTERS);
    setVerdictPaging(FIRST_PAGE);
  }, [token]);

  const value = useMemo<Workspace>(() => ({
    selectedTenant,
    setSelectedTenant: (tenantId) => {
      setSelectedTenant(tenantId);
      setRingPaging(FIRST_PAGE);                                   // another tenant's cursors mean nothing
      setVerdictPaging(FIRST_PAGE);
    },
    ringFilters,
    // Paging resets only when the filters really changed, so a repeated apply keeps the page.
    setRingFilters: (filters) => {
      if (JSON.stringify(filters) === JSON.stringify(ringFilters)) return;
      setRingFiltersState(filters);
      setRingPaging(FIRST_PAGE);
    },
    ringPaging, setRingPaging,
    verdictFilters,
    setVerdictFilters: (filters) => {
      setVerdictFiltersState(filters);
      setVerdictPaging(FIRST_PAGE);
    },
    verdictPaging, setVerdictPaging,
  }), [selectedTenant, ringFilters, ringPaging, verdictFilters, verdictPaging]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Workspace {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace outside WorkspaceProvider");
  return value;
}
