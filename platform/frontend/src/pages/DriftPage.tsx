/**
 * Score drift (FR-D80-82, override 4): the bank's own real hourly mean and p99 for days 8-9 with
 * drift events marked, the events with the supervisor's acted-on toggle and its note, and the
 * permanent note. Supervisor and administrator; the administrator reads only, and additionally
 * sees the "R12 experiment" panel (experiment tenant and synthetic control), which bank users
 * never receive from the API.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, FlaskConical, Info } from "lucide-react";
import { api } from "@/api/endpoints";
import type { DriftEventSummary, Params, R12Stream } from "@/api/types";
import { useSession } from "@/app/session";
import { useActiveTenant } from "@/app/tenant";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, Notice, PageHeader, ReadOnlyBanner, TableSkeleton, errorText } from "@/components/shared";
import { Plot } from "@/components/Plot";
import { fmtAsReceived, fmtTime, fmtTimeUtc, pyFixed } from "@/lib/formatters";

export const DRIFT_NOTE = "This monitor detects shifts in the score distribution. It does not by itself indicate a change "
  + "in laundering behaviour and never triggers retraining automatically.";
export const EXPERIMENT_LABEL = "experiment / synthetic";

const MONITORS = ["All", "adwin_score_mean", "adwin_score_p99"];
const statistic = { format: (value: number) => pyFixed(value, 4, false) };       // Python ":.4f"

/** The acted-on toggle, made with a note (FR-D81). */
function ActedOnDialog({ event, onClose, onSave, saving, error }: {
  event: DriftEventSummary | null; onClose: () => void; onSave: (note: string) => void; saving: boolean; error: unknown;
}) {
  const [note, setNote] = useState("");
  const [missing, setMissing] = useState(false);
  if (!event) return null;
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{event.acted_on ? "Mark event unreviewed" : "Mark event reviewed"}</DialogTitle>
          <DialogDescription>Event {event.event_id}, {event.monitor}. A note is required.</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="acted-on-note">Note</Label>
          <Textarea id="acted-on-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </div>
        {missing ? <Notice tone="error">A note is required to change the acted-on flag.</Notice> : null}
        {error ? <Notice tone="error">{errorText(error)}</Notice> : null}
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={saving} onClick={() => {
            if (!note.trim()) return setMissing(true);
            setMissing(false);
            onSave(note);
          }}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function streamTraces(stream: R12Stream, name: string) {
  const fired = stream.rows.filter((row) => row.adwin_mean_drift || row.adwin_p99_drift);
  return [
    { type: "scatter" as const, mode: "lines" as const, name: `${name}: hourly mean`,
      x: stream.rows.map((row) => row.hour), y: stream.rows.map((row) => row.mean ?? null) },
    { type: "scatter" as const, mode: "markers" as const, name: `${name}: ADWIN fired`, marker: { symbol: "x" as const, size: 10 },
      x: fired.map((row) => row.hour), y: fired.map((row) => row.mean ?? null) },
  ];
}

function StreamSummary({ label, stream }: { label: string; stream: R12Stream }) {
  return (
    <TableRow>
      <TableCell>{label}</TableCell>
      <TableCell>{stream.detected ? "yes" : "no"}</TableCell>
      <TableCell>{stream.first_detection_step ?? "—"}</TableCell>
      <TableCell>{stream.delay_hours === null ? "not detected" : fmtAsReceived(stream.delay_hours)}</TableCell>
    </TableRow>
  );
}

/** Administrator only: R12's real run on the experiment tenant and the synthetic control. */
function R12ExperimentPanel() {
  const panel = useQuery({ queryKey: ["r12-panel"], queryFn: api.r12Panel });
  const amended = panel.data?.results.amendment_a_hourly;
  const original = panel.data?.results.original_registered_run;
  return (
    <Card data-testid="r12-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="size-4 text-primary" /> R12 experiment <Badge variant="warning">{EXPERIMENT_LABEL}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {panel.isPending ? <Skeleton className="h-64 w-full" /> : panel.isError ? (
          <ErrorState compact error={panel.error} onRetry={() => panel.refetch()} />
        ) : !panel.data ? (
          <Notice tone="info">No R12 panel is available yet.</Notice>
        ) : (
          <>
            <Notice tone="warning">
              {EXPERIMENT_LABEL}: the R12 experiment tenant, not a bank. {panel.data.results.statement}. {panel.data.results.synthetic_control}
            </Notice>
            {amended ? (
              <Plot
                testId="r12-chart"
                height={320}
                data={[...streamTraces(amended.real, "Real run (experiment)"), ...streamTraces(amended.control, "Control (synthetic)")]}
                layout={{
                  legend: { orientation: "h", y: -0.25 },
                  shapes: [panel.data.results.real_onset, panel.data.results.control_onset].filter(Boolean).map((x) => ({
                    type: "line", xref: "x", yref: "paper", x0: x, x1: x, y0: 0, y1: 1, line: { dash: "dot", width: 1, color: "#7f7f7f" },
                  })),
                }}
              />
            ) : null}
            <div className="rounded-md border">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow><TableHead>Stream ({EXPERIMENT_LABEL})</TableHead><TableHead>detected</TableHead>
                    <TableHead>first_detection_step</TableHead><TableHead>delay_hours</TableHead></TableRow>
                </TableHeader>
                <TableBody>
                  {amended ? <><StreamSummary label="Amendment A, real run" stream={amended.real} />
                    <StreamSummary label="Amendment A, synthetic control" stream={amended.control} /></> : null}
                  {original ? <><StreamSummary label="As registered, real run" stream={original.real} />
                    <StreamSummary label="As registered, synthetic control" stream={original.control} /></> : null}
                </TableBody>
              </Table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function DriftPage() {
  const session = useSession()!;
  const { tenantId, tenantName } = useActiveTenant();
  const queryClient = useQueryClient();
  const [monitor, setMonitor] = useState("All");
  const [editing, setEditing] = useState<DriftEventSummary | null>(null);
  const isAdmin = session.role === "admin";
  const enabled = tenantId !== null && (session.role === "supervisor" || isAdmin);
  const series = useQuery({ queryKey: ["drift-hourly", tenantId], queryFn: () => api.driftHourly(tenantId!), enabled });
  const params: Params = [["limit", "100"], ...(monitor !== "All" ? [["monitor", monitor] as [string, string]] : [])];
  const events = useQuery({ queryKey: ["drift", tenantId, params], queryFn: () => api.driftEvents(tenantId!, params), enabled });
  const toggle = useMutation({
    mutationFn: ({ event, note }: { event: DriftEventSummary; note: string }) =>
      api.setDriftActedOn(tenantId!, event.event_id, !event.acted_on, note),
    onSuccess: () => {
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["drift", tenantId] });
    },
  });

  const note = <Notice tone="info" className="flex items-start gap-2"><Info className="mt-0.5 size-4 shrink-0" />{DRIFT_NOTE}</Notice>;
  if (tenantId === null) return <><PageHeader title="Score drift" />{isAdmin ? <R12ExperimentPanel /> : null}</>;

  const items = events.data?.items ?? [];
  const hourly = series.data;
  const eventMarkers = items.length ? [{
    type: "scatter" as const, mode: "markers" as const, name: "Drift event",
    x: items.map((item) => item.window_end), y: items.map(() => 1), yaxis: "y3",
    marker: { symbol: "triangle-down" as const, size: 12, color: "#d62728" },
    text: items.map((item) => `${item.monitor}<br>statistic ${statistic.format(item.statistic)}<br>threshold ${fmtAsReceived(item.threshold)}`),
    hoverinfo: "text" as const,
  }] : [];

  return (
    <>
      <PageHeader
        title="Score drift"
        description={`Hourly scores for ${tenantName}, days 8-9.`}
        actions={
          <Select value={monitor} onValueChange={setMonitor}>
            <SelectTrigger className="w-52" aria-label="Monitor"><SelectValue /></SelectTrigger>
            <SelectContent>{MONITORS.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
          </Select>
        }
      />
      {isAdmin ? <ReadOnlyBanner /> : null}
      {note}
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="size-4 text-primary" /> Hourly mean and 99th percentile, days 8-9</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {series.isPending || events.isPending ? <Skeleton className="h-80 w-full" /> : series.isError ? (
            <ErrorState compact error={series.error} onRetry={() => series.refetch()} />
          ) : !hourly || !hourly.items.length ? (
            <Notice tone="info">No hourly score series is available for this tenant yet.</Notice>
          ) : (
            <>
              <p className="text-muted-foreground text-xs" data-testid="drift-statement">{hourly.statement}</p>
              <Plot
                testId="drift-chart"
                height={380}
                data={[
                  { type: "scatter", mode: "lines+markers", name: "Hourly mean", x: hourly.items.map((p) => p.day), y: hourly.items.map((p) => p.mean) },
                  { type: "scatter", mode: "lines+markers", name: "Hourly 99th percentile", yaxis: "y2",
                    x: hourly.items.map((p) => p.day), y: hourly.items.map((p) => p.p99) },
                  ...eventMarkers,
                ]}
                layout={{
                  legend: { orientation: "h", y: -0.2 },
                  yaxis: { title: { text: "mean" } },
                  yaxis2: { title: { text: "p99" }, overlaying: "y", side: "right" },
                  yaxis3: { overlaying: "y", range: [0, 1.05], visible: false },
                  // events as vertical lines (FR-D80) at the events' own times; hover is on the markers
                  shapes: items.map((item) => ({
                    type: "line", xref: "x", yref: "paper", x0: item.window_end, x1: item.window_end, y0: 0, y1: 1,
                    line: { dash: "dot", width: 1, color: "#d62728" },
                  })),
                }}
              />
            </>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Drift events</CardTitle></CardHeader>
        <CardContent className="space-y-2">
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
                    <TableHead>Acted on</TableHead><TableHead>Note</TableHead><TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.event_id} data-testid="drift-event-row">
                      <TableCell title={fmtTimeUtc(item.detected_at)}>{fmtTime(item.detected_at)}</TableCell>
                      <TableCell className="font-mono text-xs">{item.monitor}</TableCell>
                      <TableCell className="text-xs">{fmtTime(item.window_start)} → {fmtTime(item.window_end)}</TableCell>
                      <TableCell className="text-right tabular-nums">{statistic.format(item.statistic)}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtAsReceived(item.threshold)}</TableCell>
                      <TableCell>{item.acted_on ? <Badge variant="success">Yes</Badge> : <Badge variant="secondary">No</Badge>}</TableCell>
                      <TableCell className="max-w-xs text-xs whitespace-normal">{item.acted_on_note ?? ""}</TableCell>
                      <TableCell>
                        {isAdmin ? null : (
                          <Button size="xs" variant="outline" onClick={() => { toggle.reset(); setEditing(item); }}>
                            {item.acted_on ? "Mark unreviewed" : "Mark reviewed"}
                          </Button>
                        )}
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
      {isAdmin ? <R12ExperimentPanel /> : null}
      <ActedOnDialog key={editing?.event_id ?? "none"} event={editing} onClose={() => setEditing(null)}
        saving={toggle.isPending} error={toggle.error}
        onSave={(text) => editing && toggle.mutate({ event: editing, note: text })} />
    </>
  );
}
