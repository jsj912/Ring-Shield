/**
 * Admin (FR-D90-93, app.py::_admin_page and the _r10 functions): the tenant registry, and the
 * registered tenant-vs-pooled (R10) result, either the latest one or a run started here and polled.
 */
import { useEffect } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Building2, FlaskConical, Loader2, Play, RotateCw, Users } from "lucide-react";
import { api } from "@/api/endpoints";
import type { ExperimentJobResponse, R10Results } from "@/api/types";
import { useTenantsQuery } from "@/app/tenant";
import { useSessionValue } from "@/app/workspace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorState, KpiCard, Notice, PageHeader, TableSkeleton, errorText } from "@/components/shared";
import { Plot } from "@/components/Plot";
import { fmtAsReceived, fmtPercent, fmtRecall, pyFixed } from "@/lib/formatters";
import { deadlineExpired, newPollDeadline } from "@/lib/polling";
import { PRIMARY_COLUMNS, ROBUSTNESS_COLUMNS, r10PerTenant, r10PrimaryTable, r10RobustnessTable, type R10Row } from "@/lib/r10";
import { cn } from "@/lib/utils";

type R10Job = ExperimentJobResponse & { deadline: number };

const count = { format: (value: number) => pyFixed(value, 0, true) };            // Python ":,"

function ResultTable({ columns, rows, testId }: { columns: readonly string[]; rows: R10Row[]; testId: string }) {
  return (
    <div className="overflow-x-auto rounded-md border" data-testid={testId}>
      <Table className="[&_td]:px-2 [&_th]:px-2">
        <TableHeader>
          <TableRow>{columns.map((column) => <TableHead key={column} className="whitespace-normal">{column}</TableHead>)}</TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => {
            const pooledRow = row.Tenant === "All five";
            return (
              <TableRow key={index} className={cn(pooledRow ? "bg-primary/5 font-medium" : "")}>
                {columns.map((column) => (
                  <TableCell key={column} className={cn(column === "Kind" || column === "Note" ? "text-muted-foreground text-xs whitespace-normal" : "tabular-nums")}>
                    {row[column]}
                  </TableCell>
                ))}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/** FR-D91-92 with change 6. */
export function R10ResultView({ results }: { results: R10Results }) {
  const lookup = r10PerTenant(results);
  const tenants = results.rows.primary.tenants;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <KpiCard label="Cross-bank rings" value={`${results.cross_bank_rings} of ${results.n_in_scope_rings}`} hint={fmtPercent(results.cross_bank_fraction)} icon={<Building2 />} tone="warning" />
        <KpiCard label="Mean banks per ring" value={fmtAsReceived(results.mean_banks_per_ring)} icon={<Building2 />} />
        <KpiCard label="Pooled recall (primary)" value={fmtRecall(results.rows.primary.pooled.value)} hint="all five, with 95% CI below" icon={<FlaskConical />} tone="success" />
        <KpiCard label="Own model (b) recall" value={fmtRecall(results.rows.primary.tenant.value)} hint="all five, with 95% CI below" icon={<FlaskConical />} tone="danger" />
      </div>
      <p className="text-sm" data-testid="r10-summary">
        <strong>Cross-bank rings:</strong> {results.cross_bank_rings} of {results.n_in_scope_rings} ({fmtPercent(results.cross_bank_fraction)})
        {" · "}<strong>mean banks per ring</strong> {fmtAsReceived(results.mean_banks_per_ring)}
      </p>
      <p className="text-muted-foreground text-xs">
        Days {results.window_days.join(", ")}, {results.scope}, Jaccard {results.jaccard}, seeds {results.seeds.join(", ")},
        bootstrap over rings ({count.format(results.n_boot)} resamples). Computed {results.created_utc}.
      </p>
      <h3 className="text-sm font-semibold">Primary set (banks {tenants.join(", ")})</h3>
      <ResultTable columns={PRIMARY_COLUMNS} rows={r10PrimaryTable(results)} testId="r10-primary" />
      <p className="text-muted-foreground text-xs">
        (a): the pooled model's scores, restricted to the bank's own edges. (b): the bank's own model on its own edges.
        Budget-matched: (b) with the pooled seed count. Ring recall only; member coverage was not part of R10 as registered.
      </p>
      <h3 className="text-sm font-semibold">Robustness set (banks {results.rows.robustness.tenants.join(", ")})</h3>
      <ResultTable columns={ROBUSTNESS_COLUMNS} rows={r10RobustnessTable(results)} testId="r10-robustness" />
      <Plot
        testId="r10-chart"
        height={320}
        data={(["tenant_recall", "pooled_recall"] as const).map((field) => ({
          type: "bar" as const,
          name: field === "tenant_recall" ? "(b) own scores, own edges" : "Pooled",
          x: tenants.map(String),
          y: tenants.map((tenant) => lookup.get(`primary/${tenant}`)?.[field] ?? null),
        }))}
        layout={{ barmode: "group", xaxis: { title: { text: "Bank (primary set)" }, type: "category" }, yaxis: { title: { text: "Ring recall" } }, legend: { orientation: "h", y: -0.25 } }}
      />
      <p className="text-muted-foreground text-xs">Per-bank bars are descriptive; the claim is the pooled-across-tenants row.</p>
    </div>
  );
}

function R10Section() {
  const [job, setJob] = useSessionValue<R10Job | null>("admin-r10-job", null);
  const polling = Boolean(job && (job.status === "queued" || job.status === "running"));
  const start = useMutation({
    mutationFn: api.r10Start,
    onSuccess: (started) => setJob({ ...started, deadline: newPollDeadline() }),
  });
  const status = useQuery({
    queryKey: ["r10-job", job?.job_id],
    queryFn: () => api.r10Job(job!.job_id),
    enabled: polling,
    refetchInterval: 5000,                                       // NFR-D04
    gcTime: 0,
  });
  useEffect(() => {
    if (!job || !polling || !status.data || status.data.job_id !== job.job_id) return;
    if (status.data.status !== job.status) setJob({ ...job, ...status.data });
  });
  const expired = polling && job ? deadlineExpired(job.deadline) : false;
  const succeeded = job?.status === "succeeded" && job.results;
  const latest = useQuery({ queryKey: ["r10-latest"], queryFn: api.r10Latest, enabled: !succeeded });

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2"><FlaskConical className="size-4 text-primary" /> R10 tenant vs pooled</CardTitle>
          <CardDescription className="mt-1">Ring recall of each bank's own model against the pooled model, as registered.</CardDescription>
        </div>
        <Button size="sm" disabled={start.isPending || (polling && !expired)} onClick={() => start.mutate()}>
          {start.isPending || (polling && !expired) ? <Loader2 className="animate-spin" /> : <Play />} Run
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {start.isError ? <Notice tone="error">{errorText(start.error)}</Notice> : null}
        {job ? (
          <p className="text-muted-foreground text-xs" data-testid="r10-status">Status: {job.status}</p>
        ) : null}
        {expired ? <Notice tone="info">Still working, refresh later.</Notice> : null}
        {status.isError ? <ErrorState compact error={status.error} onRetry={() => status.refetch()} /> : null}
        {job?.status === "failed" ? (
          <div className="flex items-start gap-2">
            <Notice tone="error" className="flex-1">{job.message || "The R10 experiment failed."}</Notice>
            <Button size="sm" variant="outline" onClick={() => start.mutate()}><RotateCw /> Retry</Button>
          </div>
        ) : null}
        {succeeded ? (
          <>
            <R10ResultView results={job!.results!} />
            {job!.message ? <p className="text-muted-foreground text-xs">{job!.message}</p> : null}
          </>
        ) : latest.isPending ? <Skeleton className="h-64 w-full" /> : latest.isError ? (
          <ErrorState error={latest.error} onRetry={() => latest.refetch()} />
        ) : latest.data === null ? (
          <Notice tone="info">No R10 result has been computed yet. Press Run to compute it.</Notice>
        ) : (
          <>
            <Badge variant="outline">Latest registered result</Badge>
            <R10ResultView results={latest.data.results} />
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function AdminPage() {
  const tenants = useTenantsQuery(true);
  return (
    <>
      <PageHeader title="Admin" description="Tenant registry and the cross-tenant experiment." />
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Building2 className="size-4 text-primary" /> Tenants</CardTitle></CardHeader>
        <CardContent>
          {tenants.isPending ? <TableSkeleton rows={3} columns={6} /> : tenants.isError ? (
            <ErrorState error={tenants.error} onRetry={() => tenants.refetch()} />
          ) : (
            <div className="rounded-md border" data-testid="tenant-registry">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tenant ID</TableHead><TableHead>Bank code</TableHead><TableHead>Name</TableHead>
                    <TableHead>Loaded</TableHead><TableHead className="text-right">Rings</TableHead><TableHead className="text-right">Verdicts</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tenants.data.map((tenant) => (
                    <TableRow key={tenant.tenant_id}>
                      <TableCell className="font-mono">{tenant.tenant_id}</TableCell>
                      <TableCell className="font-mono">{tenant.bank_code}</TableCell>
                      <TableCell>{tenant.name}</TableCell>
                      <TableCell>{tenant.is_loaded ? <Badge variant="success">Yes</Badge> : <Badge variant="secondary">No</Badge>}</TableCell>
                      <TableCell className="text-right tabular-nums">{tenant.ring_count ?? 0}</TableCell>
                      <TableCell className="text-right tabular-nums">{tenant.verdict_count ?? 0}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Users className="size-4 text-primary" /> Users</CardTitle></CardHeader>
        <CardContent>
          <Notice tone="info">Tenant user listings are unavailable because the API has no user-list endpoint.</Notice>
        </CardContent>
      </Card>
      <R10Section />
    </>
  );
}
