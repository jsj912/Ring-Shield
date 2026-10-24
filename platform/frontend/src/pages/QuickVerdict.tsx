/** FR-D17: confirm or reject from the queue, after a confirmation prompt (app.py::_queue). */
import { useState, type MouseEvent } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import type { VerdictKind } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Notice, errorText } from "@/components/shared";
import { useRecordVerdict, useSubmitted } from "./ring/verdict-state";

export function QuickVerdict({ tenantId, ringId, allowed }: { tenantId: number; ringId: string; allowed: boolean }) {
  const [pending, setPending] = useState<VerdictKind | null>(null);
  const record = useRecordVerdict(tenantId, ringId);
  const [submitted] = useSubmitted(tenantId, ringId);
  const disabled = !allowed || submitted || record.isPending;
  const stop = (event: MouseEvent) => event.stopPropagation();       // not a row click

  return (
    <div className="flex gap-1" onClick={stop}>
      <Button size="xs" variant="outline" disabled={disabled} aria-label="Confirm" title="Confirm" onClick={() => { record.reset(); setPending("confirm"); }}>
        <CheckCircle2 /><span className="hidden 2xl:inline">Confirm</span>
      </Button>
      <Button size="xs" variant="outline" disabled={disabled} aria-label="Reject" title="Reject" onClick={() => { record.reset(); setPending("reject"); }}>
        <XCircle /><span className="hidden 2xl:inline">Reject</span>
      </Button>
      <Dialog open={pending !== null} onOpenChange={(open) => { if (!open) setPending(null); }}>
        <DialogContent onClick={stop}>
          <DialogHeader>
            <DialogTitle>{pending === "confirm" ? "Confirm" : "Reject"} ring {ringId}?</DialogTitle>
            <DialogDescription>
              The verdict is recorded with no note. Open the ring to add a note or to correct it partially.
            </DialogDescription>
          </DialogHeader>
          {record.isError ? <Notice tone="error">{errorText(record.error)}</Notice> : null}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPending(null)}>Cancel confirmation</Button>
            <Button
              variant={pending === "confirm" ? "destructive" : "default"}
              disabled={record.isPending}
              onClick={() => record.mutate({ verdict: pending!, note: null }, { onSuccess: () => setPending(null) })}
            >
              {record.isPending ? <Loader2 className="animate-spin" /> : null}
              {pending === "confirm" ? "Confirm verdict" : "Reject verdict"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
