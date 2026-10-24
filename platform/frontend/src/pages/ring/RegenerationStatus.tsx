/**
 * After a partial verdict: poll the regeneration job every 2 s until it finishes or the 120 s
 * deadline passes, then refresh all three panels (app.py::_poll_regeneration, _retry_regeneration,
 * _show_regeneration_state).
 */
import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCw } from "lucide-react";
import { api } from "@/api/endpoints";
import type { RingExplanation } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Notice, errorText } from "@/components/shared";
import { deadlineExpired, newPollDeadline } from "@/lib/polling";
import { ringKeys } from "./queries";
import { useRegenerationState } from "./verdict-state";

export function RegenerationStatus({ tenantId, ringId, explanation }: {
  tenantId: number; ringId: string; explanation: RingExplanation | null | undefined;
}) {
  const queryClient = useQueryClient();
  const [state, setState] = useRegenerationState(tenantId, ringId);
  const polling = Boolean(state && (state.status === "queued" || state.status === "running") && state.job_id);

  const job = useQuery({
    queryKey: ["regeneration", tenantId, ringId, state?.job_id],
    queryFn: () => api.regenerationJob(tenantId, ringId, state!.job_id!),
    enabled: polling,
    refetchInterval: 2000,
    gcTime: 0,
  });

  useEffect(() => {
    if (!state || !polling) return;
    if (deadlineExpired(state.deadline)) {
      setState({ ...state, status: "timed_out" });
      return;
    }
    const data = job.data;
    if (!data || data.job_id !== state.job_id || data.status === state.status) return;
    setState({ ...state, status: data.status, error: data.error });
    if (data.status === "succeeded") {
      // the new revision changes the narrative, the graph and the evidence (FR-D52)
      for (const key of [ringKeys.explanation, ringKeys.subgraph, ringKeys.evidence, ringKeys.detail]) {
        queryClient.invalidateQueries({ queryKey: key(tenantId, ringId) });
      }
    }
  });

  const retry = useMutation({
    mutationFn: () => api.regenerate(tenantId, ringId, state!.verdict_id),
    onSuccess: (result) => setState({
      ...state!, job_id: result.job_id, status: result.status, error: result.error, deadline: newPollDeadline(),
    }),
  });

  if (!state) {
    return explanation?.regenerating ? <Notice tone="info">Regenerating explanation...</Notice> : null;
  }
  if (polling) {
    return (
      <div className="space-y-2">
        <Notice tone="info" className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" /> Regenerating explanation...</Notice>
        {job.isError ? <Notice tone="error">{errorText(job.error)}</Notice> : null}
      </div>
    );
  }
  if (state.status === "failed") {
    return (
      <div className="flex items-start gap-2">
        <Notice tone="error" className="flex-1">{state.error || "Explanation regeneration failed"}</Notice>
        <Button size="sm" variant="outline" disabled={retry.isPending} onClick={() => retry.mutate()}><RotateCw /> Retry</Button>
        {retry.isError ? <Notice tone="error">{errorText(retry.error)}</Notice> : null}
      </div>
    );
  }
  if (state.status === "unavailable") return <Notice tone="info">The verdict was recorded, but the explanation could not be regenerated.</Notice>;
  if (state.status === "timed_out") return <Notice tone="info">Still working, refresh later.</Notice>;
  if (state.status === "succeeded") return <Notice tone="success">Explanation regenerated for the corrected ring.</Notice>;
  return null;
}
