/**
 * Ring queue (FR-D10-15, app.py::_queue and _set_ring_page). The API filters, sorts and pages;
 * this screen shows what it returns and remembers the applied filters and page (FR-D14).
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Filter, Globe2, Layers, Network, RotateCcw, Search } from "lucide-react";
import { api } from "@/api/endpoints";
import type { RingSummary } from "@/api/types";
import { useSession } from "@/app/session";
import { useActiveTenant } from "@/app/tenant";
import { DEFAULT_RING_FILTERS, useWorkspace, type RingFilters } from "@/app/workspace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { MultiSelect } from "@/components/MultiSelect";
import {
  EmptyState, ErrorState, KpiCard, Notice, PageHeader, ReadOnlyBanner, StatusBadge, TableSkeleton, WeightBar,
} from "@/components/shared";
import { RING_STATUSES, TOPOLOGY_TYPES, dayEndUtc, dayOf, dayStartUtc } from "@/lib/contract";
import { fmtAmount, fmtAsReceived, fmtTime, fmtTimeUtc, fmtWeight } from "@/lib/formatters";
import { canRecordVerdicts } from "@/app/pages";
import { QuickVerdict } from "./QuickVerdict";
import { ringParams, withNextCursor } from "./queue-params";

type SortKey = RingFilters["sort"];

function FilterBar({ applied, onApply }: { applied: RingFilters; onApply: (filters: RingFilters) => void }) {
  // The controls start from the applied filters, so returning from a ring shows what is applied.
  const [draft, setDraft] = useState(applied);
  const [from, setFrom] = useState(dayOf(applied.start_after));
  const [to, setTo] = useState(dayOf(applied.start_before));
  useEffect(() => {
    setDraft(applied);
    setFrom(dayOf(applied.start_after));
    setTo(dayOf(applied.start_before));
  }, [applied]);

  const apply = () => onApply({
    ...draft,
    status: draft.status.length ? draft.status : ["open"],
    q: draft.q?.trim() || null,
    start_after: from ? dayStartUtc(from) : null,
    start_before: to ? dayEndUtc(to) : null,
  });

  return (
    <Card className="p-3">
      <form
        className="grid grid-cols-2 items-end gap-3 md:grid-cols-3 2xl:grid-cols-[1.4fr_1fr_1fr_1.2fr_1fr_1fr_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          apply();
        }}
        aria-label="Ring filters"
      >
        <div className="col-span-2 space-y-1.5 md:col-span-3 2xl:col-span-1">
          <Label htmlFor="ring-search">Search ring ID or account ID</Label>
          <div className="relative">
            <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" />
            <Input id="ring-search" className="pl-8" value={draft.q ?? ""} placeholder="e.g. full-gine_causal-1-0"
              onChange={(e) => setDraft({ ...draft, q: e.target.value })} />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label>Status</Label>
          <MultiSelect label="Status" options={RING_STATUSES} value={draft.status} emptyText="open"
            onChange={(status) => setDraft({ ...draft, status })} />
        </div>
        <div className="space-y-1.5">
          <Label>Topology</Label>
          <MultiSelect label="Topology" options={TOPOLOGY_TYPES} value={draft.topology_type}
            onChange={(topology_type) => setDraft({ ...draft, topology_type })} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="min-conf">Minimum confidence <span className="text-muted-foreground tabular-nums">{fmtWeight(draft.min_conf)}</span></Label>
          <Slider id="min-conf" className="h-9" min={0} max={1} step={0.01} value={[draft.min_conf]}
            onValueChange={([value]) => setDraft({ ...draft, min_conf: value })} aria-label="Minimum confidence" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="start-from">Start from</Label>
          <Input id="start-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="start-to">Start to</Label>
          <Input id="start-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <div className="col-span-2 flex items-center gap-3 md:col-span-1 2xl:col-span-1">
          <label className="flex h-9 items-center gap-2 text-xs font-medium whitespace-nowrap">
            <Switch checked={draft.cross_bank_only} onCheckedChange={(cross_bank_only) => setDraft({ ...draft, cross_bank_only })}
              aria-label="Cross-bank only" />
            Cross-bank only
          </label>
          <Button type="submit" size="sm"><Filter /> Apply filters</Button>
          <Button type="button" size="sm" variant="ghost" aria-label="Reset filters"
            onClick={() => onApply({ ...DEFAULT_RING_FILTERS, sort: applied.sort, order: applied.order })}>
            <RotateCcw />
          </Button>
        </div>
      </form>
    </Card>
  );
}

function SortHeader({ label, column, filters, onSort, className }: {
  label: string; column: SortKey; filters: RingFilters; onSort: (sort: SortKey) => void; className?: string;
}) {
  const active = filters.sort === column;
  const Icon = !active ? ArrowUpDown : filters.order === "desc" ? ArrowDown : ArrowUp;
  return (
    <TableHead className={className} aria-sort={active ? (filters.order === "desc" ? "descending" : "ascending") : "none"}>
      <button type="button" className="hover:text-foreground inline-flex items-center gap-1" onClick={() => onSort(column)}>
        {label}
        <Icon className={active ? "text-foreground size-3.5" : "size-3.5 opacity-50"} />
      </button>
    </TableHead>
  );
}

function RingRow({ row, onOpen, tenantId, canVerdict }: {
  row: RingSummary; onOpen: () => void; tenantId: number; canVerdict: boolean;
}) {
  return (
    <TableRow className="cursor-pointer" onClick={onOpen} onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}
      tabIndex={0} data-testid="ring-row">
      <TableCell className="font-mono text-[11px] font-medium text-primary 2xl:text-xs">{row.ring_id}</TableCell>
      <TableCell className="leading-tight">
        <div className="font-medium">{row.topology_type}</div>
        <div className="text-muted-foreground text-[10px] 2xl:text-[11px]">p = {fmtAsReceived(row.topology_prob)}</div>
      </TableCell>
      <TableCell className="text-right tabular-nums">{row.n_members} <span className="text-muted-foreground">/ {row.n_edges}</span></TableCell>
      <TableCell className="text-right tabular-nums">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="block leading-tight">
              <span className="block">{fmtAmount(row.total_amount)}</span>
              <span className="text-muted-foreground block text-[11px]">
                {row.total_currency ?? ""}{row.total_partial ? " (partial)" : ""}
              </span>
            </span>
          </TooltipTrigger>
          <TooltipContent>From the ring's explanation, in its hub currency; '(partial)' means some transactions had no exchange rate. Never converted here.</TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="block text-[11px] leading-tight 2xl:text-xs">
              <span className="block">{fmtTime(row.start_time)} →</span>
              <span className="block">{fmtTime(row.end_time)} <span className="text-muted-foreground">· {row.window_text}</span></span>
            </span>
          </TooltipTrigger>
          <TooltipContent>{fmtTimeUtc(row.start_time)} → {fmtTimeUtc(row.end_time)}</TooltipContent>
        </Tooltip>
      </TableCell>
      <TableCell>
        <span className="inline-flex items-center gap-2 tabular-nums">
          <WeightBar value={row.confidence} className="hidden 2xl:inline-block" />
          {fmtWeight(row.confidence)}
        </span>
      </TableCell>
      <TableCell>
        {row.cross_bank
          ? <Badge variant="violet"><Globe2 /> Yes</Badge>
          : <span className="text-muted-foreground text-xs">No</span>}
      </TableCell>
      <TableCell><StatusBadge status={row.status} /></TableCell>
      <TableCell>
        {row.status === "open" ? <QuickVerdict tenantId={tenantId} ringId={row.ring_id} allowed={canVerdict} /> : null}
      </TableCell>
    </TableRow>
  );
}

export function QueuePage() {
  const session = useSession()!;
  const navigate = useNavigate();
  const { tenantId, tenantName } = useActiveTenant();
  const { ringFilters, setRingFilters, ringPaging, setRingPaging } = useWorkspace();
  const params = ringParams(ringFilters, ringPaging);
  const query = useQuery({
    queryKey: ["rings", tenantId, params],
    queryFn: () => api.rings(tenantId!, params),
    enabled: tenantId !== null,
    placeholderData: keepPreviousData,
  });

  const nextCursor = query.data?.next_cursor ?? null;
  useEffect(() => {
    if (!query.isPlaceholderData) setRingPaging(withNextCursor(ringPaging, nextCursor));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nextCursor, query.isPlaceholderData]);

  const sortBy = (column: SortKey) => setRingFilters({
    ...ringFilters, sort: column, order: ringFilters.sort === column && ringFilters.order === "desc" ? "asc" : "desc",
  });

  if (tenantId === null) return <PageHeader title="Ring queue" />;
  const rows = query.data?.items ?? [];
  const crossBank = rows.filter((row) => row.cross_bank).length;       // counting, on this page

  return (
    <>
      <PageHeader title="Ring queue" description={`Suspected laundering rings for ${tenantName}. Click a row to investigate.`} />
      {session.role === "admin" ? <><ReadOnlyBanner /><Notice tone="warning">Administrators cannot record verdicts.</Notice></> : null}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiCard label="Matching filters" value={query.data ? query.data.total : "—"} hint="rings, as counted by the API" icon={<Filter />} />
        <KpiCard label="Rings for tenant" value={query.data ? query.data.tenant_total : "—"} hint="all statuses" icon={<Network />} />
        <KpiCard label="Cross-bank on this page" value={query.data ? crossBank : "—"} hint={`of ${rows.length} shown`} icon={<Globe2 />} tone="warning" />
        <KpiCard label="Page" value={ringPaging.page + 1} hint="50 rings per page" icon={<Layers />} tone="success" />
      </div>
      <FilterBar applied={ringFilters} onApply={setRingFilters} />
      <Card className="overflow-hidden p-0">
        {query.isPending ? <TableSkeleton columns={9} /> : query.isError ? (
          <div className="p-4"><ErrorState error={query.error} onRetry={() => query.refetch()} /></div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState title={query.data!.tenant_total === 0 ? "No rings have been generated for this tenant yet" : "No rings match these filters"}>
              {query.data!.tenant_total === 0 ? "Rings appear here once the platform has scored this tenant's transactions." : "Widen the filters or reset them."}
            </EmptyState>
          </div>
        ) : (
          <>
            <div className={query.isFetching ? "opacity-60 transition-opacity" : "transition-opacity"}>
              <Table className="[&_td]:px-2 [&_th]:px-2">
                <TableHeader className="sticky top-0 z-10">
                  <TableRow>
                    <TableHead>Ring ID</TableHead>
                    <TableHead>Type</TableHead>
                    <SortHeader label="Members / edges" column="members" filters={ringFilters} onSort={sortBy} className="w-20 text-right whitespace-normal" />
                    <SortHeader label="Total" column="total_amount" filters={ringFilters} onSort={sortBy} className="text-right" />
                    <SortHeader label="Window" column="start_time" filters={ringFilters} onSort={sortBy} />
                    <SortHeader label="Confidence" column="confidence" filters={ringFilters} onSort={sortBy} />
                    <TableHead>Cross-bank</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <RingRow key={row.ring_id} row={row} tenantId={tenantId} canVerdict={canRecordVerdicts(session.role)} onOpen={() => navigate(`/rings/${encodeURIComponent(row.ring_id)}`)} />
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex items-center justify-between border-t px-3 py-2 text-sm">
              <span className="text-muted-foreground" data-testid="ring-total">{query.data!.total} rings match these filters</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" disabled={ringPaging.page === 0}
                  onClick={() => setRingPaging({ ...ringPaging, page: Math.max(0, ringPaging.page - 1) })}>
                  <ChevronLeft /> Previous page
                </Button>
                <span className="text-muted-foreground tabular-nums">Page {ringPaging.page + 1}</span>
                <Button size="sm" variant="outline" disabled={!nextCursor || query.isPlaceholderData}
                  onClick={() => setRingPaging({ ...ringPaging, page: ringPaging.page + 1 })}>
                  Next page <ChevronRight />
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
