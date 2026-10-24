/**
 * Ring-detail queries. Detail, explanation, subgraph and evidence stay cached for the session
 * (NFR-D05), so returning to a ring does not refetch until a verdict invalidates them.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/endpoints";

export const ringKeys = {
  all: (tenantId: number, ringId: string) => ["ring", tenantId, ringId] as const,
  detail: (tenantId: number, ringId: string) => ["ring", tenantId, ringId, "detail"] as const,
  explanation: (tenantId: number, ringId: string) => ["ring", tenantId, ringId, "explanation"] as const,
  subgraph: (tenantId: number, ringId: string) => ["ring", tenantId, ringId, "subgraph"] as const,
  evidence: (tenantId: number, ringId: string) => ["ring", tenantId, ringId, "evidence"] as const,
  verdicts: (tenantId: number, ringId: string) => ["ring", tenantId, ringId, "verdicts"] as const,
};

const SESSION = { staleTime: Infinity } as const;

export function useRing(tenantId: number, ringId: string) {
  return useQuery({ queryKey: ringKeys.detail(tenantId, ringId), queryFn: () => api.ring(tenantId, ringId), ...SESSION });
}

export function useExplanation(tenantId: number, ringId: string) {
  return useQuery({ queryKey: ringKeys.explanation(tenantId, ringId), queryFn: () => api.explanation(tenantId, ringId), ...SESSION });
}

export function useSubgraph(tenantId: number, ringId: string) {
  return useQuery({ queryKey: ringKeys.subgraph(tenantId, ringId), queryFn: () => api.subgraph(tenantId, ringId), ...SESSION });
}

export function useEvidence(tenantId: number, ringId: string) {
  return useQuery({ queryKey: ringKeys.evidence(tenantId, ringId), queryFn: () => api.evidence(tenantId, ringId), ...SESSION });
}

export function useRingVerdicts(tenantId: number, ringId: string) {
  return useQuery({ queryKey: ringKeys.verdicts(tenantId, ringId), queryFn: () => api.ringVerdicts(tenantId, ringId) });
}
