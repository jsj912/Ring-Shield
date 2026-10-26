/** The ring's verdicts (app.py::_ring_verdicts); notes are plain text (NFR-D13). */
import { History } from "lucide-react";
import type { VerdictHistoryPage } from "@/api/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ErrorState, TableSkeleton, VerdictBadge } from "@/components/shared";
import { fmtTime, fmtTimeUtc } from "@/lib/formatters";

export function RingVerdicts({ history, state }: {
  history: VerdictHistoryPage | undefined;
  state: { isPending: boolean; error: unknown; retry: () => void };
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><History className="size-4 text-primary" /> Verdicts on this ring</CardTitle>
      </CardHeader>
      <CardContent>
        {state.isPending ? <TableSkeleton rows={2} columns={4} /> : state.error ? (
          <ErrorState compact error={state.error} onRetry={state.retry} />
        ) : !history?.items.length ? (
          <p className="text-muted-foreground text-sm">No verdicts have been recorded for this ring.</p>
        ) : (
          <>
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead><TableHead>Investigator</TableHead><TableHead>Verdict</TableHead><TableHead>Note</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.items.map((item) => (
                    <TableRow key={item.verdict_id} data-testid="ring-verdict-row">
                      <TableCell title={fmtTimeUtc(item.created_at)}>{fmtTime(item.created_at)}</TableCell>
                      <TableCell>{item.user_name}</TableCell>
                      <TableCell><VerdictBadge verdict={item.verdict} simulated={item.is_simulated} /></TableCell>
                      <TableCell className="max-w-md whitespace-pre-wrap">{item.note ?? ""}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {history.next_before_id ? (
              <p className="text-muted-foreground mt-2 text-xs">Older verdicts are listed on the Verdict history page.</p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
