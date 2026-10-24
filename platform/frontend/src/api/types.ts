/**
 * Response and request shapes, field for field from platform/api/schemas.py (NFR-D51: the API's
 * names, no renaming layer). Datetimes arrive as ISO-8601 strings and stay strings.
 */

export type Role = "analyst" | "supervisor" | "admin";
export type VerdictKind = "confirm" | "reject" | "partial";
export type RingStatus = "open" | "confirmed" | "rejected" | "partial";

/** The API's error body (platform/api/errors.py). */
export interface ErrorBody {
  error_code?: string;
  message?: string;
  request_id?: string;
  details?: Record<string, unknown> | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SessionResponse {
  user_id: number;
  tenant_id: number | null;
  tenant_name: string;
  role: Role;
  token: string;
  expires_at: string;
}

export interface TenantResponse {
  tenant_id: number;
  bank_code: number;
  name: string;
  is_loaded: boolean;
  created_at: string;
  ring_count: number;
  verdict_count: number;
}

export interface RingSummary {
  ring_id: string;
  tenant_id: number;
  topology_type: string;
  topology_prob: number;
  n_members: number;
  n_edges: number;
  total_amount: number | null;
  total_currency: string | null;
  total_partial?: boolean | null;
  n_currencies?: number | null;
  start_time: string;
  end_time: string;
  window_text: string;
  confidence: number;
  cross_bank: boolean;
  counterparty_banks: string[];
  status: RingStatus | string;
}

export interface RingDetail extends RingSummary {
  member_accounts: number[];
  member_edges: number[];
  seed_edges: number[];
  expanded_edges: number[];
  conservation_closure: number | null;
  source_accounts: number[];
  sink_accounts: number[];
  mule_accounts: number[];
  model_id: string;
  aggregator_id: string;
}

export interface RingPage {
  items: RingSummary[];
  next_cursor: string | null;
  total: number;
  tenant_total: number;
}

export interface RingEvidenceNode {
  account_id: number;
  bank_code: number | null;
  bank_label: string | null;
  is_source: boolean;
  is_sink: boolean;
  is_mule: boolean;
}

export interface RingEvidenceEdge {
  edge_id: number;
  source_account: number;
  target_account: number;
  timestamp: string;
  amount_sent: number | null;
  amount_received: number | null;
  currency_sent: string | null;
  currency_received: string | null;
  payment_format: string | null;
  calibrated_score: number | null;
  is_seed: boolean | null;
  is_conversion: boolean;
}

export interface RingEvidenceGraph {
  tenant_id: number;
  ring_id: string;
  nodes: RingEvidenceNode[];
  edges: RingEvidenceEdge[];
  next_before_edge_id: number | null;
  missing_edge_ids: number[];
}

export interface SubgraphNode {
  account_id: number;
  role: string | null;
  bank_code: number | null;
  bank_label: string | null;
  inflow: number | null;
  outflow: number | null;
  hold_time_s: number | null;
  w_account: number | null;
}

export interface SubgraphEdge {
  edge_id: number;
  from_id: number;
  to_id: number;
  timestamp: string;
  amount: number | null;
  currency: string | null;
  amount_received: number | null;
  currency_received: string | null;
  payment_format: string | null;
  is_seed: boolean | null;
  is_conversion: boolean;
  w_total: number | null;
  w_score: number | null;
  w_loo: number | null;
  w_flow: number | null;
}

export interface RingSubgraph {
  tenant_id: number;
  ring_id: string;
  n_accounts: number;
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
}

/** The explanation's weight records are dict[str, Any] in the schema; these are the fields used. */
export interface EdgeWeight {
  edge_id: number;
  w_total?: number | null;
  w_score?: number | null;
  w_loo?: number | null;
  w_flow?: number | null;
}

export interface AccountWeight {
  account_id: number;
  role?: string | null;
  inflow?: number | null;
  outflow?: number | null;
  hold_time_s?: number | null;
  w_account?: number | null;
}

export interface FeatureWeight {
  feature_name: string;
  display_name?: string | null;
  mean_shap: number | null;
  top_edge_id?: number | null;
}

export interface RingExplanation {
  tenant_id: number;
  ring_id: string;
  explainer_version: string;
  revision: number;
  regenerated: boolean;
  edge_weights: EdgeWeight[];
  account_weights: AccountWeight[];
  feature_weights: FeatureWeight[];
  narrative: string;
  evidence_summary: Record<string, unknown>;
  latency_ms: number;
  provenance: Record<string, unknown>;
  created_at: string;
  regenerating?: boolean;
}

export interface VerdictRequest {
  verdict: VerdictKind;
  corrected_members?: number[];
  corrected_edges?: number[];
  note: string | null;
}

export interface RegenerationResponse {
  status: "queued" | "unavailable";
  job_id: string | null;
}

export interface VerdictResponse {
  verdict_id: number;
  ring_id: string;
  user_id: number;
  user_name: string;
  verdict: VerdictKind;
  corrected_members: number[];
  corrected_edges: number[];
  note: string | null;
  is_simulated: boolean;
  created_at: string;
  regeneration?: RegenerationResponse | null;
}

export interface ExplanationJobResponse {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  result_revision: number | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface VerdictHistoryPage {
  items: VerdictResponse[];
  next_before_id: number | null;
}

export interface TenantVerdictItem {
  verdict_id: number;
  ring_id: string;
  verdict: VerdictKind;
  analyst_id: number;
  analyst_label: string;
  is_simulated: boolean;
  note_excerpt: string | null;
  created_at: string;
}

export interface TenantVerdictPage {
  items: TenantVerdictItem[];
  next_cursor: string | null;
  total: number;
  counts: { confirmed: number; rejected: number; partial: number };
  analysts: { analyst_id: number; analyst_label: string }[];
}

export interface ModelVersionSummary {
  model_version_id: number;
  component: "expansion" | "affinity" | "typing" | "detector";
  version_tag: string;
  trained_at: string;
  train_label_count: number;
  holdout_ring_f1: number | null;
  promoted: boolean;
  shared: boolean;
  gate_reason: string | null;
  retrain_run_id: string | null;
}

export interface ModelVersionPage {
  items: ModelVersionSummary[];
  next_before_id: number | null;
  active_model_id: string;
  active_seed: number;
}

export interface DriftEventSummary {
  event_id: number;
  monitor: "adwin_score_mean" | "adwin_score_p99";
  detected_at: string;
  window_start: string;
  window_end: string;
  statistic: number;
  threshold: number;
  acted_on: boolean;
}

export interface DriftEventPage {
  items: DriftEventSummary[];
  next_before_id: number | null;
}

export interface DriftSeriesResponse {
  tenant_id: number;
  active_model_id: string;
  active_seed: number;
  items: { day: string; mean: number; p99: number }[];
}

export interface RetrainCandidate {
  model_version_id: number;
  component: string;
  holdout_ring_f1: number | null;
  promoted: boolean;
  gate_reason: string | null;
}

export interface RetrainRunSummary {
  run_id: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  model_version_id: number | null;
  candidates: RetrainCandidate[];
}

export interface RetrainRunPage {
  items: RetrainRunSummary[];
}

export interface RetrainRunStatusResponse {
  run_id: string;
  status: string;
  model_version_id: number | null;
  log_lines: string[];
  candidates: RetrainCandidate[];
}

/** The registered R10 result (jobs/experiment_worker.py::r10_registered_results). */
export interface R10Interval {
  value: number;
  low: number;
  high: number;
}

export interface R10Row {
  tenants: number[];
  n_pairs: number;
  n_rings: number;
  tenant: R10Interval;
  pooled: R10Interval;
  difference: R10Interval;
}

export interface R10PerTenant {
  row: "primary" | "pooled_scores" | "budget_matched" | "robustness";
  tenant_id: number;
  n_rings: number;
  tenant_recall: number | null;
  pooled_recall: number | null;
}

export interface R10Results {
  created_utc: string;
  seeds: number[];
  window_days: number[];
  scope: string;
  jaccard: number;
  n_boot: number;
  n_in_scope_rings: number;
  cross_bank_rings: number;
  cross_bank_fraction: number;
  mean_banks_per_ring: number;
  rows: { primary: R10Row; pooled_scores: R10Row; budget_matched: R10Row; robustness: R10Row };
  per_tenant: R10PerTenant[];
}

export interface R10Result {
  results: R10Results;
}

export interface ExperimentJobResponse {
  job_id: string;
  status: string;
  message: string | null;
  results: R10Results | null;
}

/** Query parameters as ordered pairs, so repeated keys (status=open&status=partial) survive. */
export type Params = [string, string][];
