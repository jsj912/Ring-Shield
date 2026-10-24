/**
 * Score drift (FR-D80-82, app.py::_drift_events): the daily mean and p99 series with detected
 * events marked, the events with a supervisor's reviewed toggle, and the permanent note.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Info } from "lucide-react";
import { api } from "@/api/endpoints";
import type { Params } from "@/api/types";
import { useSession } from "@/app/session";
import { useActiveTenant } from "@/app/tenant";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, Notice, PageHeader, TableSkeleton, errorText } from "@/components/shared";
import { Plot } from "@/components/Plot";
import { fmtAsReceived, fmtTime, fmtTimeUtc, pyFixed } from "@/lib/formatters";

export const DRIFT_NOTE = "This monitor detects shifts in the score distribution. It does not by itself indicate a change "
  + "in laundering behaviour and never triggers retraining automatically.";

const MONITORS = ["All", "adwin_score_mean", "adwin_score_p99"];
const statistic = { format: (value: number) => pyFixed(value, 4, false) };       // Python ":.4f"

export function DriftPage() {
  const session = useSession()!;
  const { tenantId, tenantName } = useActiveTenant();
  const queryClient = useQueryClient();
  const [monitor, setMonitor] = useState("All");
  const enabled = tenantId !== null && session.role === "supervisor";
  const series = useQuery({ queryKey: ["drift-series", tenantId], queryFn: () => api.driftSeries(tenantId!), enabled });
  const params: Params = [["limit", "100"], ...(monitor !== "All" ? [["monitor", monitor] as [string, string]] : [])];
  const events = useQuery({ queryKey: ["drift", tenantId, params], queryFn: () => api.driftEvents(tenantId!, params), enabled });
  const toggle = useMutation({
    mutationFn: ({ eventId, actedOn }: { eventId: number; actedOn: boolean }) => api.setDriftActedOn(tenantId!, eventId, actedOn),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["drift", tenantId] }),
  });

  const note = <Notice tone="info" className="flex items-start gap-2"><Info className="mt-0.5 size-4 shrink-0" />{DRIFT_NOTE}</Notice>;
  if (tenantId === null) return <PageHeader title="Score drift" />;
  if (session.role !== "supervisor") {
    return (
      <>
        <PageHeader title="Score drift" />
        <Notice tone="info">Drift review is available to tenant supervisors.</Notice>
        {note}
      </>
    );
  }

  const items = events.data?.items ?? [];
  const markers = (id: string, label: string, symbol: "diamond" | "diamond-open") => {
    const detected = items.filter((item) => item.monitor === id);
    return detected.length ? [{
      type: "scatter" as const, mode: "markers" as const, name: label,
      x: detected.map((item) => item.window_end), y: detected.map((item) => item.statistic),
      marker: { symbol, size: 11 },
      text: detected.map((item) => `${item.monitor}<br>statistic ${statistic.format(item.statistic)}<br>delta ${fmtAsReceived(item.threshold)}`),
      hoverinfo: "text" as const,
    }] : [];
  };

  return (
    <>
      <PageHeader
        title="Score drift"
        description={`Distribution of daily scores for ${tenantName}.`}
        actions={
          <Select value={monitor} onValueChange={setMonitor}>
            <SelectTrigger className="w-52" aria-label="Monitor"><SelectValue /></SelectTrigger>
            <SelectContent>{MONITORS.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
          </Select>
        }
      />
      {note}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="size-4 text-primary" /> Daily mean and 99th percentile</CardTitle></CardHeader>
        <CardContent>
          {series.isPending || events.isPending ? <Skeleton className="h-80 w-full" /> : series.isError ? (
            <ErrorState compact error={series.error} onRetry={() => series.refetch()} />
          ) : !series.data.items.length ? (
            <Notice tone="info">No daily score statistics are available for this tenant.</Notice>
          ) : (
            <Plot
              testId="drift-chart"
              height={360}
              data={[
                { type: "scatter", mode: "lines", name: "Daily mean", x: series.data.items.map((p) => p.day), y: series.data.items.map((p) => p.mean) },
                { type: "scatter", mode: "lines", name: "Daily 99th percentile", x: series.data.items.map((p) => p.day), y: series.data.items.map((p) => p.p99) },
                ...markers("adwin_score_mean", "Mean drift detected", "diamond"),
                ...markers("adwin_score_p99", "P99 drift detected", "diamond-open"),
              ]}
              layout={{
                legend: { orientation: "h", y: -0.2 },
                // events as vertical lines too (FR-D80); the x positions are the events' own times
                shapes: items.map((item) => ({
                  type: "line", xref: "x", yref: "paper", x0: item.window_end, x1: item.window_end, y0: 0, y1: 1,
                  line: { dash: "dot", width: 1, color: "#d62728" },
                })),
              }}
            />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Drift events</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {toggle.isError ? <Notice tone="error">{errorText(toggle.error)}</Notice> : null}
          {events.isPending ? <TableSkeleton columns={6} /> : events.isError ? (
            <ErrorState compact error={events.error} onRetry={() => events.refetch()} />
          ) : !items.length ? (
            <EmptyState title="No drift events have been recorded for this tenant." />
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Detected at</TableHead><TableHead>Monitor</TableHead><TableHead>Window</TableHead>
                    <TableHead className="text-right">Statistic</TableHead><TableHead className="text-right">Threshold (delta)</TableHead>
                    <TableHead>Reviewed</TableHead><TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.event_id}>
                      <TableCell title={fmtTimeUtc(item.detected_at)}>{fmtTime(item.detected_at)}</TableCell>
                      <TableCell className="font-mono text-xs">{item.monitor}</TableCell>
                      <TableCell className="text-xs">{fmtTime(item.window_start)} → {fmtTime(item.window_end)}</TableCell>
                      <TableCell className="text-right tabular-nums">{statistic.format(item.statistic)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtAsReceived(item.threshold)}</TableCell>
                      <TableCell>{item.acted_on ? <Badge variant="success">Yes</Badge> : <Badge variant="secondary">No</Badge>}</TableCell>
                      <TableCell>
                        <Button size="xs" variant="outline" disabled={toggle.isPending}
                          onClick={() => toggle.mutate({ eventId: item.event_id, actedOn: !item.acted_on })}>
                          {item.acted_on ? "Mark unreviewed" : "Mark reviewed"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {events.data?.next_before_id != null ? <p className="text-muted-foreground text-xs">More drift events are available through the API cursor.</p> : null}
        </CardContent>
      </Card>
    </>
  );
}
