/** FR-D20-22: the narrative exactly as received, then the ring summary and the latest verdict. */
import { useState, type ReactNode } from "react";
import { Check, Copy, FileText } from "lucide-react";
import type { RingDetail, RingExplanation, VerdictHistoryPage } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState, Notice, VerdictBadge } from "@/components/shared";
import { fmtAmount, fmtAsReceived, fmtClosure, fmtTime, fmtTimeUtc } from "@/lib/formatters";
import { latestCorrection } from "./verdict-state";

export function NarrativePanel({ ring, explanation, explanationState, history }: {
  ring: RingDetail;
  explanation: RingExplanation | null | undefined;
  explanationState: { isPending: boolean; error: unknown; retry: () => void };
  history: VerdictHistoryPage | undefined;
}) {
  const [copied, setCopied] = useState(false);
  const correction = latestCorrection(ring, history);
  const rows: [string, ReactNode][] = [
    ["Type", `${ring.topology_type} (p = ${fmtAsReceived(ring.topology_prob)})`],
    ["Members", correction ? `${ring.n_members} detected, ${correction.members} after the partial verdict` : String(ring.n_members)],
    ["Edges", String(ring.n_edges)],
    ["Total amount", fmtAmount(ring.total_amount, ring.total_currency, ring.total_partial)],
    ["Window", <span title={`${fmtTimeUtc(ring.start_time)} → ${fmtTimeUtc(ring.end_time)}`}>
      {fmtTime(ring.start_time)} → {fmtTime(ring.end_time)}, {ring.window_text}</span>],
    ["Window (UTC)", `${fmtTimeUtc(ring.start_time)} → ${fmtTimeUtc(ring.end_time)}`],
    ["Conservation closure", fmtClosure(ring.conservation_closure)],
    ["Cross-bank banks", ring.counterparty_banks.join(", ") || "None"],
  ];
  const latest = history?.items[0];

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><FileText className="size-4 text-primary" /> Narrative</CardTitle>
        {explanation ? (
          <Button size="xs" variant="ghost" onClick={async () => {
            await navigator.clipboard?.writeText(explanation.narrative);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }}>
            {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy narrative"}
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {explanationState.isPending ? (
          <div className="space-y-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-4/5" /></div>
        ) : explanationState.error ? (
          <ErrorState compact error={explanationState.error} onRetry={explanationState.retry} />
        ) : explanation ? (
          // byte for byte, as text: never markdown or HTML (FR-D20, NFR-D13)
          <p className="bg-muted/40 rounded-md border-l-2 border-primary px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap" data-testid="narrative">
            {explanation.narrative}
          </p>
        ) : (
          <Notice tone="info">No verified explanation has been loaded for this ring yet.</Notice>
        )}
        <dl className="divide-y rounded-md border text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="grid grid-cols-[9.5rem_1fr] gap-2 px-3 py-1.5">
              <dt className="text-muted-foreground text-xs leading-5">{label}</dt>
              <dd className="min-w-0 break-words tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-muted-foreground text-[11px]">Model {ring.model_id} · aggregator {ring.aggregator_id}</p>
        {latest ? (
          <div className="flex flex-wrap items-center gap-1.5 text-xs" data-testid="latest-verdict">
            <span className="text-muted-foreground">Latest verdict:</span>
            <VerdictBadge verdict={latest.verdict} simulated={latest.is_simulated} />
            <span>by {latest.user_name} at {fmtTime(latest.created_at)}</span>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
