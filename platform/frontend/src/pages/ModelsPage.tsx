/**
 * Models (FR-D70-73): model versions with the gate's reason, and for supervisors retraining with a
 * confirmation, the run polled every 5 s with its log tail, and refused candidates shown prominently
 * with a link to their version row (app.py::_model_versions and the _retrain functions).
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, ChevronDown, Cpu, Loader2, RefreshCw } from "lucide-react";
import { api } from "@/api/endpoints";
import type { RetrainCandidate } from "@/api/types";
import { useSession } from "@/app/session";
import { useActiveTenant } from "@/app/tenant";
import { useSessionValue } from "@/app/workspace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, ErrorState, KpiCard, Notice, PageHeader, TableSkeleton, errorText } from "@/components/shared";
import { fmtAsReceived, fmtBool, fmtTime, fmtTimeUtc } from "@/lib/formatters";
import { cn } from "@/lib/utils";

export const RETRAIN_SCOPE = "Retrains the expansion and affinity models; the typing model is fixed. "
  + "The result is promoted only if it passes the holdout gate.";

const FINISHED = new Set(["succeeded", "failed"]);

function RunStatusBadge({ status }: { status: string }) {
  const variant = status === "succeeded" ? "success" : status === "failed" ? "destructive" : "info";
  return <Badge variant={variant}>{status === "running" || status === "queued" ? <Loader2 className="animate-spin" /> : null}{status}</Badge>;
}

/** FR-D72: poll the run every 5 s until it finishes; the log tail is open while it runs. */
function RetrainStatus({ tenantId, runId, onFinished }: { tenantId: number; runId: string; onFinished: () => void }) {
  const run = useQuery({
    queryKey: ["retrain-run", tenantId, runId],
    queryFn: () => api.retrainRun(tenantId, runId),
    refetchInterval: (query) => (query.state.data && FINISHED.has(query.state.data.status) ? false : 5000),
  });
  const [open, setOpen] = useState(true);
  const finished = run.data ? FINISHED.has(run.data.status) : false;
  useEffect(() => {
    if (finished) onFinished();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);
  if (run.isPending) return <TableSkeleton rows={2} columns={3} />;
  if (run.isError) return <ErrorState compact error={run.error} onRetry={() => run.refetch()} />;
  return (
    <div className="rounded-md border">
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <span className="text-sm"><strong>Run {runId}:</strong> <RunStatusBadge status={run.data.status} /></span>
        <Button size="xs" variant="ghost" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          Log tail <ChevronDown className={cn("transition-transform", open ? "rotate-180" : "")} />
        </Button>
      </div>
      {open ? (
        run.data.log_lines.length
          ? <pre className="bg-muted/50 max-h-56 overflow-auto border-t px-3 py-2 font-mono text-xs whitespace-pre-wrap">{run.data.log_lines.join("\n")}</pre>
          : <p className="text-muted-foreground border-t px-3 py-2 text-xs">No retraining log output yet.</p>
      ) : null}
    </div>
  );
}

/** The cycles.md columns shown for R11's retrain cycle, by their names in the API. */
const R11_COLUMNS = ["retrain_status", "holdout_ring_f1", "no_retrain_control_holdout_ring_f1", "candidates",
  "promotions", "refusals", "run_id"];

/** Override 5: R11's outcome in the retrain dialog, every value as the API sends it. */
function R11Results({ tenantId }: { tenantId: number }) {
  const r11 = useQuery({ queryKey: ["r11", tenantId], queryFn: () => api.r11(tenantId) });
  if (r11.isPending) return <TableSkeleton rows={2} columns={4} />;
  if (r11.isError) return <ErrorState compact error={r11.error} onRetry={() => r11.refetch()} />;
  if (!r11.data.items.length) return <p className="text-muted-foreground text-xs">R11 did not run for this bank.</p>;
  return (
    <div className="space-y-2" data-testid="r11-results">
      <p className="text-sm font-medium">R11: gated retraining <Badge variant="warning">simulated verdicts</Badge></p>
      <p className="text-muted-foreground text-xs">{r11.data.statement}</p>
      {r11.data.items.map((lane) => (
        <div key={lane.accuracy} className="rounded-md border" data-testid="r11-lane">
          <p className="border-b px-2 py-1 text-xs">
            Verdict accuracy {fmtAsReceived(lane.accuracy)} · retrained after cycle {lane.retrain_after_cycle} of {lane.cycles}
            {" "}({lane.cycle_hours} h cycles) · {lane.components.join(", ")} · typing: {lane.typing}
          </p>
          <Table className="text-xs">
            <TableHeader>
              <TableRow><TableHead>cycle</TableHead>{R11_COLUMNS.map((column) => <TableHead key={column}>{column}</TableHead>)}</TableRow>
            </TableHeader>
            <TableBody>
              {lane.cycle_rows.filter((row) => row.retrain_status !== "not run").map((row) => (
                <TableRow key={row.cycle}>
                  <TableCell>{row.cycle}</TableCell>
                  {R11_COLUMNS.map((column) => <TableCell key={column} className="whitespace-normal">{row[column] ?? ""}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ))}
    </div>
  );
}

/** FR-D73: a refused candidate's gate reason, prominently, with a link to its version row. */
function Refusals({ runId, candidates, onFocus }: { runId: string; candidates: RetrainCandidate[]; onFocus: (id: number) => void }) {
  return (
    <>
      {candidates.filter((candidate) => !candidate.promoted).map((candidate) => (
        <div key={candidate.model_version_id} role="alert"
          className="border-destructive/40 bg-destructive/10 flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-sm">
          <AlertOctagon className="text-destructive size-4 shrink-0" />
          <span className="min-w-0 flex-1">
            Run {runId}: {candidate.component} refused by the holdout gate: {candidate.gate_reason}
          </span>
          <Button size="xs" variant="outline" onClick={() => onFocus(candidate.model_version_id)}>
            Show model version {candidate.model_version_id}
          </Button>
        </div>
      ))}
    </>
  );
}

function RetrainSection({ tenantId, onFocus }: { tenantId: number; onFocus: (id: number) => void }) {
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [runId, setRunId] = useSessionValue<string | null>(`retrain-run/${tenantId}`, null);
  const runs = useQuery({ queryKey: ["retrain-runs", tenantId], queryFn: () => api.retrainRuns(tenantId) });
  const start = useMutation({
    mutationFn: () => api.startRetrain(tenantId),
    onSuccess: (queued) => {
      setConfirming(false);
      setRunId(queued.run_id);
      queryClient.invalidateQueries({ queryKey: ["retrain-runs", tenantId] });
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><RefreshCw className="size-4 text-primary" /> Retraining</CardTitle>
        <Button size="sm" onClick={() => { start.reset(); setConfirming(true); }}><RefreshCw /> Retrain now</Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <Dialog open={confirming} onOpenChange={setConfirming}>
          <DialogContent className="sm:max-w-3xl">
            <DialogHeader>
              <DialogTitle>Retrain now?</DialogTitle>
              <DialogDescription>{RETRAIN_SCOPE}</DialogDescription>
            </DialogHeader>
            <R11Results tenantId={tenantId} />
            {start.isError ? <Notice tone="error">{errorText(start.error)}</Notice> : null}
            <DialogFooter>
              <Button variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
              <Button disabled={start.isPending} onClick={() => start.mutate()}>
                {start.isPending ? <Loader2 className="animate-spin" /> : null} Start retraining
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        {runId ? (
          <RetrainStatus tenantId={tenantId} runId={runId} onFinished={() => {
            setRunId(undefined);                                     // stop polling; the runs list shows the result
            queryClient.invalidateQueries({ queryKey: ["retrain-runs", tenantId] });
            queryClient.invalidateQueries({ queryKey: ["models", tenantId] });
          }} />
        ) : null}
        {runs.isPending ? <TableSkeleton rows={3} columns={6} /> : runs.isError ? (
          <ErrorState compact error={runs.error} onRetry={() => runs.refetch()} />
        ) : !runs.data.items.length ? (
          <p className="text-muted-foreground text-sm">No retraining runs yet.</p>
        ) : (
          <>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Run ID</TableHead><TableHead>Status</TableHead><TableHead>Started</TableHead>
                    <TableHead>Finished</TableHead><TableHead>Promoted version</TableHead><TableHead>Candidates</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.data.items.map((row) => (
                    <TableRow key={row.run_id}>
                      <TableCell className="font-mono text-xs">{row.run_id}</TableCell>
                      <TableCell><RunStatusBadge status={row.status} /></TableCell>
                      <TableCell title={fmtTimeUtc(row.started_at)}>{fmtTime(row.started_at)}</TableCell>
                      <TableCell title={fmtTimeUtc(row.finished_at)}>{fmtTime(row.finished_at)}</TableCell>
                      <TableCell>{row.model_version_id ?? "—"}</TableCell>
                      <TableCell>{row.candidates.map((c) => `${c.component} #${c.model_version_id}`).join(", ")}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {runs.data.items.map((row) => <Refusals key={row.run_id} runId={row.run_id} candidates={row.candidates} onFocus={onFocus} />)}
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function ModelsPage() {
  const session = useSession()!;
  const { tenantId, tenantName } = useActiveTenant();
  const [focus, setFocus] = useSessionValue<number | null>(`model-focus/${tenantId}`, null);
  const models = useQuery({
    queryKey: ["models", tenantId], queryFn: () => api.models(tenantId!), enabled: tenantId !== null,
  });
  const focusRow = useRef<HTMLTableRowElement>(null);
  useEffect(() => {
    focusRow.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus, models.data]);

  if (tenantId === null) return <PageHeader title="Models" />;

  return (
    <>
      <PageHeader title="Models" description={`Model versions for ${tenantName}, newest first.`} />
      {models.isError ? <ErrorState error={models.error} onRetry={() => models.refetch()} /> : null}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiCard label="Active model" value={<span className="font-mono text-lg">{models.data?.active_model_id ?? "—"}</span>} hint={models.data ? `seed ${models.data.active_seed}` : undefined} icon={<Cpu />} />
      </div>
      {session.role === "supervisor" ? <RetrainSection tenantId={tenantId} onFocus={setFocus} /> : null}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Cpu className="size-4 text-primary" /> Model versions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {models.isPending ? <TableSkeleton columns={9} /> : models.isError ? null : !models.data.items.length ? (
            <EmptyState title="No model versions are registered for this tenant." />
          ) : (
            <>
              <div className="rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Version ID</TableHead><TableHead>Component</TableHead><TableHead>Version</TableHead>
                      <TableHead>Trained at</TableHead><TableHead className="text-right">Training labels</TableHead>
                      <TableHead className="text-right">Holdout ring-F1</TableHead><TableHead>Promoted</TableHead>
                      <TableHead>Gate reason</TableHead><TableHead>Shared</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {models.data.items.map((item) => {
                      const focused = item.model_version_id === focus;
                      return (
                        <TableRow key={item.model_version_id} ref={focused ? focusRow : undefined} data-testid="model-row"
                          className={cn(focused ? "bg-warning/25 hover:bg-warning/30" : item.promoted ? "bg-success/12 hover:bg-success/18" : "")}>
                          <TableCell className="font-mono">{item.model_version_id}</TableCell>
                          <TableCell>{item.component}</TableCell>
                          <TableCell className="font-mono text-xs">{item.version_tag}</TableCell>
                          <TableCell title={fmtTimeUtc(item.trained_at)}>{fmtTime(item.trained_at)}</TableCell>
                          <TableCell className="text-right tabular-nums">{item.train_label_count}</TableCell>
                          <TableCell className="text-right tabular-nums">{fmtAsReceived(item.holdout_ring_f1)}</TableCell>
                          <TableCell>{item.promoted ? <Badge variant="success">Yes</Badge> : <span className="text-muted-foreground">No</span>}</TableCell>
                          <TableCell className="max-w-sm whitespace-normal text-xs">{item.gate_reason ?? ""}</TableCell>
                          <TableCell>{fmtBool(item.shared)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
              <p className="text-muted-foreground text-xs">Green rows are the versions currently promoted for each component; a yellow row is the one you asked to see.</p>
              {models.data.next_before_id !== null ? <p className="text-muted-foreground text-xs">More versions are available through the API cursor.</p> : null}
            </>
          )}
        </CardContent>
      </Card>
    </>
  );
}
