/**
 * Verdict history (FR-D60-62, app.py::_verdicts): GET /tenants/{id}/verdicts with filters, the
 * API's counts, cursor paging, row click to the ring and a CSV of every matching row.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronLeft, ChevronRight, Download, Filter, GitPullRequestDraft, ListChecks, Loader2, XCircle } from "lucide-react";
import { api } from "@/api/endpoints";
import type { Params, TenantVerdictItem } from "@/api/types";
import { useSession } from "@/app/session";
import { useActiveTenant } from "@/app/tenant";
import { useWorkspace, type Paging, type VerdictFilters } from "@/app/workspace";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { MultiSelect } from "@/components/MultiSelect";
import {
  EmptyState, ErrorState, KpiCard, Notice, PageHeader, ReadOnlyBanner, TableSkeleton, VerdictBadge, errorText,
} from "@/components/shared";
import { dayEndUtc, dayOf, dayStartUtc } from "@/lib/contract";
import { downloadText, toCsv } from "@/lib/csv";
import { fmtTime, fmtTimeUtc } from "@/lib/formatters";
import { withNextCursor } from "./queue-params";

/** The filter part of the query, shared by the page and the export (app.py builds it twice). */
export function verdictFilterParams(filters: VerdictFilters): Params {
  const params: Params = filters.verdict.map((value) => ["verdict", value]);
  if (filters.analyst_id !== null) params.push(["analyst_id", String(filters.analyst_id)]);
  if (filters.simulated !== null) params.push(["simulated", String(filters.simulated)]);
  if (filters.since !== null) params.push(["since", filters.since]);
  if (filters.until !== null) params.push(["until", filters.until]);
  return params;
}

function pageParams(filters: VerdictFilters, paging: Paging): Params {
  const params = verdictFilterParams(filters);
  const cursor = paging.cursors[paging.page];
  if (paging.page > 0 && cursor) params.push(["cursor", cursor]);
  params.push(["limit", "50"]);
  return params;
}

const CSV_FIELDS = ["created_at", "ring_id", "verdict", "analyst_label", "is_simulated", "note_excerpt"] as const;
const CSV_TEXT = new Set(["ring_id", "verdict", "analyst_label", "note_excerpt"]);

/** Every row matching the filters, page by page (limit 100), stopping on a repeated cursor. */
async function exportRows(tenantId: number, filters: VerdictFilters): Promise<TenantVerdictItem[]> {
  const rows: TenantVerdictItem[] = [];
  const seen = new Set<string>();
  let cursor: string | null = null;
  for (;;) {
    const params = verdictFilterParams(filters);
    if (cursor) params.push(["cursor", cursor]);
    params.push(["limit", "100"]);
    const page = await api.verdicts(tenantId, params);
    rows.push(...page.items);
    cursor = page.next_cursor;
    if (!cursor || seen.has(cursor)) break;
    seen.add(cursor);
  }
  return rows;
}

/** Python's csv writer prints booleans as True / False. */
function csvRow(item: TenantVerdictItem): Record<string, unknown> {
  return { ...item, is_simulated: item.is_simulated ? "True" : "False" };
}

function FilterBar({ applied, analysts, onApply }: {
  applied: VerdictFilters; analysts: { analyst_id: number; analyst_label: string }[]; onApply: (filters: VerdictFilters) => void;
}) {
  const [verdict, setVerdict] = useState(applied.verdict);
  const [analyst, setAnalyst] = useState(applied.analyst_id === null ? "all" : String(applied.analyst_id));
  const [simulated, setSimulated] = useState(applied.simulated === null ? "All" : applied.simulated ? "Simulated" : "Real");
  // seeded from the stored bounds, so the range survives leaving the page
  const [from, setFrom] = useState(dayOf(applied.since));
  const [to, setTo] = useState(dayOf(applied.until));

  return (
    <Card className="p-3">
      <form
        aria-label="Verdict filters"
        className="grid grid-cols-2 items-end gap-3 md:grid-cols-3 xl:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto]"
        onSubmit={(event) => {
          event.preventDefault();
          onApply({
            verdict,
            analyst_id: analyst === "all" ? null : Number(analyst),
            simulated: simulated === "All" ? null : simulated === "Simulated",
            since: from ? dayStartUtc(from) : null,
            until: to ? dayEndUtc(to) : null,
          });
        }}
      >
        <div className="space-y-1.5">
          <Label>Verdict type</Label>
          <MultiSelect label="Verdict type" options={["confirm", "reject", "partial"]} value={verdict} onChange={setVerdict} />
        </div>
        <div className="space-y-1.5">
          <Label>Analyst</Label>
          <Select value={analyst} onValueChange={setAnalyst}>
            <SelectTrigger aria-label="Analyst"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All analysts</SelectItem>
              {analysts.map((item) => (
                <SelectItem key={item.analyst_id} value={String(item.analyst_id)}>{item.analyst_label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label>Simulated or real</Label>
          <Select value={simulated} onValueChange={setSimulated}>
            <SelectTrigger aria-label="Simulated or real"><SelectValue /></SelectTrigger>
            <SelectContent>
              {["All", "Simulated", "Real"].map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="verdict-from">From (UTC day)</Label>
          <Input id="verdict-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="verdict-to">To (UTC day)</Label>
          <Input id="verdict-to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </div>
        <Button type="submit" size="sm" className="h-9"><Filter /> Apply verdict filters</Button>
      </form>
    </Card>
  );
}

export function VerdictsPage() {
  const session = useSession()!;
  const navigate = useNavigate();
  const { tenantId, tenantName } = useActiveTenant();
  const { verdictFilters, setVerdictFilters, verdictPaging, setVerdictPaging } = useWorkspace();
  const params = pageParams(verdictFilters, verdictPaging);
  const query = useQuery({
    queryKey: ["verdicts", tenantId, params],
    queryFn: () => api.verdicts(tenantId!, params),
    enabled: tenantId !== null,
    placeholderData: keepPreviousData,
  });
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<unknown>(null);

  const nextCursor = query.data?.next_cursor ?? null;
  useEffect(() => {
    if (!query.isPlaceholderData) setVerdictPaging(withNextCursor(verdictPaging, nextCursor));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nextCursor, query.isPlaceholderData]);

  if (tenantId === null) return <PageHeader title="Verdict history" />;
  const data = query.data;

  const exportCsv = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const rows = await exportRows(tenantId, verdictFilters);
      downloadText(toCsv(rows.map(csvRow), [...CSV_FIELDS], CSV_TEXT), "verdicts.csv");
    } catch (error) {
      setExportError(error);
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Verdict history"
        description={`Verdicts recorded at ${tenantName}, newest first. Click a row to open its ring.`}
        actions={
          <Button size="sm" variant="outline" onClick={exportCsv} disabled={exporting || !data}>
            {exporting ? <Loader2 className="animate-spin" /> : <Download />} Export CSV
          </Button>
        }
      />
      {session.role === "admin" ? <ReadOnlyBanner /> : null}
      {exportError ? <Notice tone="error">{errorText(exportError)}</Notice> : null}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiCard label="Matching filters" value={data ? data.total : "—"} hint="verdicts" icon={<ListChecks />} />
        <KpiCard label="Confirmed" value={data ? data.counts.confirmed : "—"} hint="in the current filter" icon={<CheckCircle2 />} tone="danger" />
        <KpiCard label="Rejected" value={data ? data.counts.rejected : "—"} hint="in the current filter" icon={<XCircle />} />
        <KpiCard label="Partial" value={data ? data.counts.partial : "—"} hint="in the current filter" icon={<GitPullRequestDraft />} tone="warning" />
      </div>
      <FilterBar
        key={JSON.stringify(verdictFilters)}
        applied={verdictFilters}
        analysts={data?.analysts ?? []}
        onApply={setVerdictFilters}
      />
      <Card className="overflow-hidden p-0">
        {query.isPending ? <TableSkeleton columns={5} /> : query.isError ? (
          <div className="p-4"><ErrorState error={query.error} onRetry={() => query.refetch()} /></div>
        ) : !data!.items.length ? (
          <div className="p-4"><EmptyState title="No verdicts match these filters" /></div>
        ) : (
          <>
            <div className={query.isFetching ? "opacity-60 transition-opacity" : "transition-opacity"}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead><TableHead>Ring ID</TableHead><TableHead>Verdict</TableHead>
                    <TableHead>Analyst</TableHead><TableHead>Note</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data!.items.map((item) => {
                    const open = () => navigate(`/rings/${encodeURIComponent(item.ring_id)}`);
                    return (
                      <TableRow key={item.verdict_id} className="cursor-pointer" tabIndex={0} onClick={open}
                        onKeyDown={(e) => { if (e.key === "Enter") open(); }} data-testid="verdict-row">
                        <TableCell title={fmtTimeUtc(item.created_at)}>{fmtTime(item.created_at)}</TableCell>
                        <TableCell className="font-mono text-xs text-primary">{item.ring_id}</TableCell>
                        <TableCell><VerdictBadge verdict={item.verdict} simulated={item.is_simulated} /></TableCell>
                        <TableCell>{item.analyst_label}</TableCell>
                        <TableCell className="max-w-lg truncate" title={item.note_excerpt ?? ""}>{item.note_excerpt ?? ""}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            <div className="flex items-center justify-between border-t px-3 py-2 text-sm">
              <span className="text-muted-foreground">{data!.total} verdicts match these filters · CSV export includes all of them</span>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" disabled={verdictPaging.page === 0}
                  onClick={() => setVerdictPaging({ ...verdictPaging, page: Math.max(0, verdictPaging.page - 1) })}>
                  <ChevronLeft /> Previous verdict page
                </Button>
                <span className="text-muted-foreground tabular-nums">Page {verdictPaging.page + 1}</span>
                <Button size="sm" variant="outline" disabled={!nextCursor || query.isPlaceholderData}
                  onClick={() => setVerdictPaging({ ...verdictPaging, page: verdictPaging.page + 1 })}>
                  Next verdict page <ChevronRight />
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
