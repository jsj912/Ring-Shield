/** One typed function per API route the dashboard calls (platform/api/routers/*). */
import { request } from "./client";
import type {
  DriftEventPage, DriftEventSummary, DriftSeriesResponse, ExperimentJobResponse, ExplanationJobResponse,
  LoginRequest, ModelVersionPage, Params, R10Result, RetrainRunPage, RetrainRunStatusResponse, RingDetail,
  RingEvidenceGraph, RingExplanation, RingPage, RingSubgraph, SessionResponse, TenantResponse,
  TenantVerdictPage, VerdictHistoryPage, VerdictRequest, VerdictResponse,
} from "./types";

const ring = (tenantId: number, ringId: string) =>
  `/tenants/${tenantId}/rings/${encodeURIComponent(ringId)}`;

export const api = {
  // auth.py
  login: (body: LoginRequest) => request<SessionResponse>("POST", "/auth/login", { body }),

  // admin.py
  tenants: () => request<TenantResponse[]>("GET", "/admin/tenants"),
  r10Latest: () => request<R10Result | null>("GET", "/admin/experiments/tenant-vs-pooled/latest", { quietNotFound: true }),
  r10Start: () => request<ExperimentJobResponse>("POST", "/admin/experiments/tenant-vs-pooled"),
  r10Job: (jobId: string) =>
    request<ExperimentJobResponse>("GET", `/admin/experiments/tenant-vs-pooled/${encodeURIComponent(jobId)}`),

  // rings.py
  rings: (tenantId: number, params: Params) => request<RingPage>("GET", `/tenants/${tenantId}/rings`, { params }),
  ring: (tenantId: number, ringId: string) => request<RingDetail>("GET", ring(tenantId, ringId)),
  subgraph: (tenantId: number, ringId: string) => request<RingSubgraph>("GET", `${ring(tenantId, ringId)}/subgraph`),
  evidence: (tenantId: number, ringId: string) =>
    request<RingEvidenceGraph>("GET", `${ring(tenantId, ringId)}/evidence`, { params: [["limit", "500"]] }),
  explanation: (tenantId: number, ringId: string) =>
    request<RingExplanation | null>("GET", `${ring(tenantId, ringId)}/explanation`, { quietNotFound: true }),
  regenerate: (tenantId: number, ringId: string, verdictId: number) =>
    request<ExplanationJobResponse>("POST", `${ring(tenantId, ringId)}/explanation/regenerate`,
      { body: { verdict_id: verdictId } }),
  regenerationJob: (tenantId: number, ringId: string, jobId: string) =>
    request<ExplanationJobResponse>("GET", `${ring(tenantId, ringId)}/explanation/jobs/${encodeURIComponent(jobId)}`),

  // verdicts.py
  ringVerdicts: (tenantId: number, ringId: string) =>
    request<VerdictHistoryPage>("GET", `${ring(tenantId, ringId)}/verdicts`, { params: [["limit", "25"]] }),
  recordVerdict: (tenantId: number, ringId: string, body: VerdictRequest) =>
    request<VerdictResponse>("POST", `${ring(tenantId, ringId)}/verdicts`, { body }),
  verdicts: (tenantId: number, params: Params) =>
    request<TenantVerdictPage>("GET", `/tenants/${tenantId}/verdicts`, { params }),

  // operations.py
  models: (tenantId: number) =>
    request<ModelVersionPage>("GET", `/tenants/${tenantId}/models`, { params: [["limit", "100"]] }),
  retrainRuns: (tenantId: number) =>
    request<RetrainRunPage>("GET", `/tenants/${tenantId}/retrain`, { params: [["limit", "50"]] }),
  startRetrain: (tenantId: number) => request<{ run_id: string }>("POST", `/tenants/${tenantId}/retrain`),
  retrainRun: (tenantId: number, runId: string) =>
    request<RetrainRunStatusResponse>("GET", `/tenants/${tenantId}/retrain/${encodeURIComponent(runId)}`),
  driftSeries: (tenantId: number) => request<DriftSeriesResponse>("GET", `/tenants/${tenantId}/drift/series`),
  driftEvents: (tenantId: number, params: Params) =>
    request<DriftEventPage>("GET", `/tenants/${tenantId}/drift`, { params }),
  setDriftActedOn: (tenantId: number, eventId: number, actedOn: boolean) =>
    request<DriftEventSummary>("PATCH", `/tenants/${tenantId}/drift/${eventId}`, { body: { acted_on: actedOn } }),
};
