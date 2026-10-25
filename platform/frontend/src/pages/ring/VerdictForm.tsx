/** FR-D50-55: confirm, reject or partially correct; one request per click (app.py::_verdict_form). */
import { useRef, useState } from "react";
import { CheckCircle2, GitPullRequestDraft, Loader2, Lock, XCircle } from "lucide-react";
import type { RingDetail } from "@/api/types";
import { canRecordVerdicts } from "@/app/pages";
import { useSession } from "@/app/session";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Notice, errorText } from "@/components/shared";
import { useRecordVerdict, useSubmitted, type VerdictInput } from "./verdict-state";

export function VerdictForm({ tenantId, ringId, ring }: { tenantId: number; ringId: string; ring: RingDetail }) {
  const session = useSession()!;
  const record = useRecordVerdict(tenantId, ringId);
  const [submitted] = useSubmitted(tenantId, ringId);
  const inFlight = useRef(false);
  const [note, setNote] = useState("");
  const [partialOpen, setPartialOpen] = useState(false);
  const [keepMembers, setKeepMembers] = useState<Record<number, boolean>>({});
  const [keepEdges, setKeepEdges] = useState<Record<number, boolean>>({});
  const [partialNote, setPartialNote] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [recorded, setRecorded] = useState(false);

  const header = (
    <CardHeader>
      <CardTitle className="flex items-center gap-2"><CheckCircle2 className="size-4 text-primary" /> Record a verdict</CardTitle>
    </CardHeader>
  );

  if (!canRecordVerdicts(session.role)) {
    return (
      <Card>
        {header}
        <CardContent className="space-y-3">
          <Notice tone="warning" className="flex items-center gap-2">
            <Lock className="size-4" />
            {session.role === "admin" ? "Administrators cannot record verdicts." : "Read-only: your role cannot record verdicts."}
          </Notice>
          <Input disabled placeholder="Note" aria-label="Note" />
          <div className="flex flex-wrap gap-2">
            <Button disabled>Confirm ring</Button>
            <Button disabled variant="outline">Reject ring</Button>
            <Button disabled variant="outline">Partially correct</Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (ring.status !== "open") {
    return (
      <Card>
        {header}
        <CardContent className="space-y-2">
          {recorded ? <Notice tone="success">Verdict recorded</Notice> : null}
          <Notice tone="info">This ring is no longer open for verdicts.</Notice>
        </CardContent>
      </Card>
    );
  }

  const disabled = record.isPending || submitted;
  const send = (input: VerdictInput) => {
    if (inFlight.current || submitted) return;        // a double click sends one request (FR-D53)
    inFlight.current = true;
    record.mutate(input, {
      onSuccess: () => {
        setRecorded(true);
        setPartialOpen(false);
      },
      onSettled: () => {
        inFlight.current = false;
      },
    });
  };

  const openPartial = () => {
    setKeepMembers(Object.fromEntries(ring.member_accounts.map((id) => [id, true])));
    setKeepEdges(Object.fromEntries(ring.member_edges.map((id) => [id, true])));
    setProblem(null);
    setPartialOpen(true);
  };

  const submitPartial = () => {
    const members = ring.member_accounts.filter((id) => keepMembers[id]);
    const edges = ring.member_edges.filter((id) => keepEdges[id]);
    if (!members.length) return setProblem("Keep at least one account for a partial correction.");
    if (members.length === ring.member_accounts.length && edges.length === ring.member_edges.length) {
      return setProblem("Remove at least one account or transaction; otherwise confirm the ring.");
    }
    if (!partialNote.trim()) return setProblem("A note is required for a partial verdict.");
    setProblem(null);
    send({ verdict: "partial", note: partialNote, corrected_members: members, corrected_edges: edges });
  };

  return (
    <Card>
      {header}
      <CardContent className="space-y-3">
        {partialOpen ? (
          <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); submitPartial(); }} aria-label="Partial correction">
            <p className="text-sm"><strong>Partially correct:</strong> untick the accounts and transactions that are not part of the ring.</p>
            <div className="grid gap-3 lg:grid-cols-2">
              <fieldset className="rounded-md border p-3">
                <legend className="px-1 text-xs font-medium">Accounts</legend>
                <div className="grid max-h-56 grid-cols-1 gap-1.5 overflow-auto sm:grid-cols-2">
                  {ring.member_accounts.map((id) => (
                    <label key={id} className="flex items-center gap-2 font-mono text-xs">
                      <Checkbox checked={keepMembers[id] ?? true} aria-label={`Keep account ${id}`}
                        onCheckedChange={(value) => setKeepMembers({ ...keepMembers, [id]: value === true })} />
                      Keep account {id}
                    </label>
                  ))}
                </div>
              </fieldset>
              <fieldset className="rounded-md border p-3">
                <legend className="px-1 text-xs font-medium">Transactions</legend>
                <div className="grid max-h-56 grid-cols-1 gap-1.5 overflow-auto sm:grid-cols-2">
                  {ring.member_edges.map((id) => (
                    <label key={id} className="flex items-center gap-2 font-mono text-xs">
                      <Checkbox checked={keepEdges[id] ?? true} aria-label={`Keep transaction ${id}`}
                        onCheckedChange={(value) => setKeepEdges({ ...keepEdges, [id]: value === true })} />
                      Keep transaction {id}
                    </label>
                  ))}
                </div>
              </fieldset>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="partial-note">Note (required for partial)</Label>
              <Textarea id="partial-note" value={partialNote} onChange={(e) => setPartialNote(e.target.value)} />
            </div>
            {problem ? <Notice tone="error">{problem}</Notice> : null}
            <div className="flex flex-wrap gap-2">
              <Button type="submit" variant="default" disabled={disabled}>
                {record.isPending ? <Loader2 className="animate-spin" /> : <GitPullRequestDraft />} Submit partial verdict
              </Button>
              <Button type="button" variant="ghost" onClick={() => setPartialOpen(false)}>Cancel partial correction</Button>
            </div>
          </form>
        ) : (
          <>
            <div className="space-y-1.5">
              <Label htmlFor="verdict-note">Note (optional for confirm or reject)</Label>
              <Input id="verdict-note" value={note} onChange={(e) => setNote(e.target.value)} />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="destructive" disabled={disabled} onClick={() => send({ verdict: "confirm", note: note || null })}>
                {record.isPending && record.variables?.verdict === "confirm" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Confirm ring
              </Button>
              <Button variant="outline" disabled={disabled} onClick={() => send({ verdict: "reject", note: note || null })}>
                {record.isPending && record.variables?.verdict === "reject" ? <Loader2 className="animate-spin" /> : <XCircle />} Reject ring
              </Button>
              <Button variant="outline" disabled={disabled} onClick={openPartial}>
                <GitPullRequestDraft /> Partially correct
              </Button>
            </div>
          </>
        )}
        {record.isError ? (
          <div className="space-y-1">
            <Notice tone="error">{errorText(record.error)}</Notice>
            <p className="text-muted-foreground text-xs">The verdict was not recorded. Your entries are kept: submit again to retry.</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
