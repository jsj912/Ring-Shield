/**
 * Shared display pieces (NFR-D52): status and verdict badges, the error state every screen uses
 * (FR-D100: the API message, its request id and a retry button), empty and loading states.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, CircleDot, Inbox, Lock, RotateCw, ShieldAlert, XCircle, GitPullRequestDraft } from "lucide-react";
import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<string, { variant: "info" | "success" | "destructive" | "warning" | "secondary"; icon: ReactNode }> = {
  open: { variant: "info", icon: <CircleDot /> },
  confirmed: { variant: "destructive", icon: <ShieldAlert /> },
  rejected: { variant: "secondary", icon: <XCircle /> },
  partial: { variant: "warning", icon: <GitPullRequestDraft /> },
};

/** Ring status: colour plus icon plus the status text itself (NFR-D22). */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const style = STATUS_STYLE[status] ?? { variant: "secondary" as const, icon: <CircleDot /> };
  return (
    <Badge variant={style.variant} className={className} data-testid="status-badge">
      {style.icon}
      {status}
    </Badge>
  );
}

const VERDICT_STYLE: Record<string, "destructive" | "secondary" | "warning"> = {
  confirm: "destructive", reject: "secondary", partial: "warning",
};

export function VerdictBadge({ verdict, simulated }: { verdict: string; simulated?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      <Badge variant={VERDICT_STYLE[verdict] ?? "secondary"}>
        {verdict === "confirm" ? <CheckCircle2 /> : verdict === "reject" ? <XCircle /> : <GitPullRequestDraft />}
        {verdict}
      </Badge>
      {simulated ? <Badge variant="violet">Simulated</Badge> : null}
    </span>
  );
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.display;
  return error instanceof Error ? error.message : "Request failed";
}

/** FR-D100 / NFR-D30: never a blank page; the message, the request id and a way to retry. */
export function ErrorState({ error, onRetry, compact, className }: {
  error: unknown; onRetry?: () => void; compact?: boolean; className?: string;
}) {
  const forbidden = error instanceof ApiError && error.kind === "forbidden";
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-lg border p-3 text-sm",
        forbidden ? "border-warning/40 bg-warning/10" : "border-destructive/40 bg-destructive/10",
        compact ? "" : "p-4",
        className,
      )}
    >
      {forbidden ? <Lock className="mt-0.5 size-4 shrink-0 text-amber-600" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />}
      <div className="min-w-0 flex-1 break-words">{errorText(error)}</div>
      {onRetry && !forbidden ? (
        <Button size="xs" variant="outline" onClick={onRetry}>
          <RotateCw /> Retry
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center">
      <div className="text-muted-foreground [&_svg]:size-8">{icon ?? <Inbox />}</div>
      <p className="text-sm font-medium">{title}</p>
      {children ? <div className="text-muted-foreground max-w-md text-xs">{children}</div> : null}
    </div>
  );
}

export function Notice({ tone = "info", children, className }: {
  tone?: "info" | "warning" | "success" | "error"; children: ReactNode; className?: string;
}) {
  const tones = {
    info: "border-sky-500/30 bg-sky-500/10 text-sky-900 dark:text-sky-200",
    warning: "border-warning/40 bg-warning/10 text-amber-900 dark:text-amber-200",
    success: "border-success/40 bg-success/10 text-emerald-900 dark:text-emerald-200",
    error: "border-destructive/40 bg-destructive/10 text-red-900 dark:text-red-200",
  };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn("rounded-lg border px-3 py-2 text-sm", tones[tone], className)}>
      {children}
    </div>
  );
}

export function TableSkeleton({ rows = 8, columns = 6 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-2 p-3" aria-busy="true" aria-label="Loading">
      <Skeleton className="h-8 w-full" />
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="flex gap-3">
          {Array.from({ length: columns }, (_, column) => (
            <Skeleton key={column} className="h-6 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}

export function KpiCard({ label, value, hint, icon, tone }: {
  label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode; tone?: "default" | "warning" | "danger" | "success";
}) {
  const accent = {
    default: "text-primary bg-primary/10", warning: "text-amber-600 bg-warning/15",
    danger: "text-destructive bg-destructive/10", success: "text-success bg-success/10",
  }[tone ?? "default"];
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 pt-4">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">{label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
          {hint ? <p className="text-muted-foreground mt-0.5 truncate text-xs">{hint}</p> : null}
        </div>
        {icon ? <div className={cn("rounded-md p-2 [&_svg]:size-4", accent)}>{icon}</div> : null}
      </CardContent>
    </Card>
  );
}

export function PageHeader({ title, description, actions, children }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}
        {children}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

/** FR-D93: every admin view of a tenant's rings and verdicts is read-only and says so. */
export function ReadOnlyBanner() {
  return (
    <Notice tone="info" className="flex items-center gap-2">
      <Lock className="size-4" /> Read-only (administrator)
    </Notice>
  );
}

/** A value in [0, 1] drawn as a bar. CSS does the scaling, so the code computes nothing (FR-D102). */
export function WeightBar({ value, className }: { value: number | null | undefined; className?: string }) {
  if (value === null || value === undefined) return null;
  return (
    <span className={cn("bg-muted relative inline-block h-1.5 w-14 overflow-hidden rounded-full align-middle", className)} aria-hidden>
      <span className="bg-primary absolute inset-y-0 left-0 w-full origin-left rounded-full" style={{ transform: `scaleX(${value})` }} />
    </span>
  );
}
