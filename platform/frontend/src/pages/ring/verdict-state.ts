/**
 * Recording a verdict (app.py::_record_verdict) and the regeneration state it starts. The state
 * is per ring and lives for the session, as Streamlit kept it in session_state["ring_regeneration"].
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import type { VerdictKind, VerdictResponse } from "@/api/types";
import { useSessionValue } from "@/app/workspace";
import { newPollDeadline } from "@/lib/polling";
import { ringKeys } from "./queries";

export interface RegenerationState {
  verdict_id: number;
  job_id: string | null;
  status: "queued" | "running" | "succeeded" | "failed" | "unavailable" | "timed_out";
  deadline: number | null;
  error: string | null;
}

export function useRegenerationState(tenantId: number, ringId: string) {
  return useSessionValue<RegenerationState | null>(`regeneration/${tenantId}/${ringId}`, null);
}

/** Set once a verdict for this ring has been recorded: the buttons stay disabled (FR-D53). */
export function useSubmitted(tenantId: number, ringId: string) {
  return useSessionValue<boolean>(`verdict-submitted/${tenantId}/${ringId}`, false);
}

export interface VerdictInput {
  verdict: VerdictKind;
  note: string | null;
  corrected_members?: number[];
  corrected_edges?: number[];
}

export function useRecordVerdict(tenantId: number, ringId: string) {
  const queryClient = useQueryClient();
  const [, setRegeneration] = useRegenerationState(tenantId, ringId);
  const [, setSubmitted] = useSubmitted(tenantId, ringId);
  return useMutation({
    mutationFn: (input: VerdictInput) => api.recordVerdict(tenantId, ringId, {
      verdict: input.verdict, note: input.note,
      ...(input.verdict === "partial"
        ? { corrected_members: input.corrected_members ?? [], corrected_edges: input.corrected_edges ?? [] }
        : {}),
    }),
    onSuccess: (result: VerdictResponse, input) => {
      setSubmitted(true);
      if (input.verdict === "partial") {
        const regeneration = result.regeneration;
        setRegeneration(regeneration && regeneration.status === "queued" && regeneration.job_id
          ? { verdict_id: result.verdict_id, job_id: regeneration.job_id, status: "queued", deadline: newPollDeadline(), error: null }
          : { verdict_id: result.verdict_id, job_id: null, status: "unavailable", deadline: null, error: null });
      }
      // The status badge, the ring's verdict list, the queue and the history all change (FR-D52).
      queryClient.invalidateQueries({ queryKey: ringKeys.detail(tenantId, ringId) });
      queryClient.invalidateQueries({ queryKey: ringKeys.verdicts(tenantId, ringId) });
      queryClient.invalidateQueries({ queryKey: ["rings", tenantId] });
      queryClient.invalidateQueries({ queryKey: ["verdicts", tenantId] });
    },
  });
}
