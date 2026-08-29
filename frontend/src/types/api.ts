/**
 * RazorGrowth AI — backend API contract types.
 * Mirrors the FastAPI response schemas (Phase 3–6).
 */

/* ── Auth ─────────────────────────────────────────────────────────────── */

export interface UserOut {
  id: string;
  email: string;
  full_name: string | null;
  status: string;
}

export interface MembershipOut {
  id: string;
  merchant_id: string;
  role: "owner" | "admin" | "operator" | "analyst";
  status: "active" | "disabled";
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
}

export interface MeResponse extends UserOut {
  memberships: MembershipOut[];
}

export interface MerchantSummary {
  id: string;
  name: string;
  slug: string;
  role: MembershipOut["role"];
}

export interface AccessibleMerchantsResponse {
  merchants: MerchantSummary[];
}

/* ── Growth radar ─────────────────────────────────────────────────────── */

export interface RadarSignal {
  id: string;
  signal_type: string;
  title: string;
  metric: string;
  current_value: number;
  comparison_value: number;
  change_percentage: number | null;
  window_days: number;
  confidence: number;
  evidence: unknown;
  detected_at: string;
}

export interface RadarResponse {
  merchant_id: string;
  signals: RadarSignal[];
}

/* ── Opportunities ────────────────────────────────────────────────────── */

export interface ScoreBreakdown {
  revenue_potential: number;
  confidence_score: number;
  urgency_score: number;
  evidence_strength: number;
  risk_score: number;
  implementation_cost_adjustment?: number;
  opportunity_score?: number;
  formula?: string;
  [key: string]: unknown;
}

export interface RankedOpportunity {
  rank: number;
  opportunity_id: string;
  title: string;
  type: string;
  status: string;
  opportunity_score: number;
  expected_revenue: number;
  confidence: number;
  score_breakdown: ScoreBreakdown;
}

export interface RankedOpportunitiesResponse {
  merchant_id: string;
  opportunities: RankedOpportunity[];
}

/** Legacy Phase-1 contract preserved by GET /api/opportunities. */
export interface LegacyOpportunityList {
  items: Array<{
    id: string;
    type: string;
    title: string;
    target_product: string;
    target_customers: number;
    confidence: number;
    expected_revenue: number;
    reasoning: string[];
    status: string;
  }>;
}

/* ── Agents ───────────────────────────────────────────────────────────── */

export interface AgentCapabilityInfo {
  name: string;
  display_name?: string;
  role?: string;
  description?: string;
  permissions?: string[];
  [key: string]: unknown;
}

export interface AgentsObservability {
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  actions_approved?: number;
  actions_rejected?: number;
  measured_revenue_total?: number;
  latency?: {
    total_latency_ms: number;
    llm_latency_ms: number;
    db_latency_ms: number;
    tool_latency_ms: number;
  };
  [key: string]: unknown;
}

export interface AgentsListResponse {
  agents: AgentCapabilityInfo[];
  observability: AgentsObservability;
}

export interface AgentRunRow {
  id: string;
  merchant_id: string | null;
  agent_name: string;
  status: string;
  mode: string;
  started_at: string;
  completed_at: string | null;
  total_latency_ms: number;
  llm_latency_ms: number;
  db_latency_ms: number;
  tool_latency_ms: number;
  opportunities_created: number;
  actions_proposed: number;
  llm_provider: string | null;
  llm_model: string | null;
  tools_used: unknown;
  errors: string[] | null;
}

export interface AgentRunsResponse {
  runs: AgentRunRow[];
}

export interface AgentRunRequest {
  mode: "fast" | "deep";
  window_days?: number;
  propose_actions?: boolean;
  merchant_id?: string;
}

export interface OrchestratorRunResponse {
  orchestrator_run_id: string;
  merchant_id: string;
  mode: string;
  [key: string]: unknown;
}

/* ── Customer intelligence ────────────────────────────────────────────── */

export interface CustomerInsight {
  customer_id: string;
  primary_segment: string;
  segments: string[];
  order_count: number;
  lifetime_value: number;
  avg_order_value: number;
  recency_days: number | null;
  payment_success_rate: number;
  failed_payment_count: number;
  churn_risk_score: number;
  churn_risk_level: string;
  churn_reasons: string[];
  strategy_note: string | null;
}

export interface CustomerInsightsResponse {
  merchant_id: string;
  count: number;
  insights: CustomerInsight[];
}

/* ── Commerce entities (Phase 2/3 reads) ──────────────────────────────── */

export interface ProductRow {
  id: string;
  merchant_id: string;
  sku: string | null;
  name: string;
  category: string | null;
  price: number;
  active: boolean;
}

export interface CustomerRow {
  id: string;
  merchant_id: string;
  name: string;
  email: string;
  segment: string;
  total_orders: number;
  total_spend: number;
}

export interface OrderItemRow {
  product_id: string;
  quantity: number;
  unit_price: number;
}

export interface OrderRow {
  id: string;
  merchant_id: string;
  customer_id: string;
  status: string;
  items: OrderItemRow[];
  total_amount: number;
  created_at: string;
}

export interface PaymentRow {
  id: string;
  merchant_id: string;
  order_id: string;
  provider: string;
  status: string;
  amount: number;
  created_at: string;
}

/* ── Actions / approval workflow ──────────────────────────────────────── */

export type ActionStatus =
  | "requested"
  | "approved"
  | "rejected"
  | "executing"
  | "completed"
  | "failed";

export interface AgentAction {
  id: string;
  merchant_id: string;
  action_type: string;
  status: ActionStatus;
  requested_by: string | null;
  approved_by: string | null;
  input_payload: Record<string, unknown> | null;
  output_payload: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface ActionListResponse {
  actions: AgentAction[];
}

export interface ActionTransitionResponse {
  id: string;
  action_type: string;
  status: ActionStatus;
  requested_by: string | null;
  approved_by: string | null;
  rejected_by: string | null;
  merchant_id: string;
  created_at: string;
}

export interface ExecutionResponse {
  action_id: string;
  action_type: string;
  status: ActionStatus;
  result: Record<string, unknown>;
  message: string;
}

export interface AuditEventRow {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditEventListResponse {
  audit_events: AuditEventRow[];
}

/* ── Simulations & experiments ────────────────────────────────────────── */

export interface SimulationRequest {
  scenario_type: "discount" | "campaign" | "payment_recovery";
  discount_percentage?: number;
  target_customers?: number;
  expected_conversion?: number;
  avg_order_value?: number;
  cost_per_target?: number;
  failed_payment_value?: number;
  recovery_rate?: number;
  opportunity_id?: string;
  merchant_id?: string;
}

export interface SimulationResult {
  id: string;
  scenario_type: string;
  estimated_revenue: number;
  estimated_cost: number;
  estimated_profit: number;
  expected_conversion: number;
  expected_roi: number | null;
  confidence_low: number | null;
  confidence_high: number | null;
  assumptions: string[];
  is_estimate: boolean;
  created_by_agent: string;
  created_at: string;
}

export interface SimulationsResponse {
  merchant_id: string;
  simulations: SimulationResult[];
}

export interface ExperimentRow {
  id: string;
  name: string;
  status: string;
  hypothesis: string;
  control_group: string;
  treatment_group: string;
  target_population_size: number;
  latest_result: {
    statistical_status: string;
    uplift_percentage: number | null;
    control_size: number;
    treatment_size: number;
  } | null;
}

export interface ExperimentsResponse {
  merchant_id: string;
  experiments: ExperimentRow[];
}

/* ── Memory & brief ───────────────────────────────────────────────────── */

export interface MemoryEntry {
  id: string;
  memory_type: string;
  content: string;
  importance: number;
  outcome_variance_pct: number | null;
  created_at: string;
}

export interface GrowthMemoryResponse {
  merchant_id: string;
  memories: MemoryEntry[];
}

export interface GrowthBrief {
  window_days: number;
  revenue: {
    current_period: number;
    previous_period?: number | null;
    change_percentage?: number | null;
    is_estimate?: boolean;
  };
  top_opportunity: {
    title: string;
    confidence: number;
    expected_revenue?: number;
    [key: string]: unknown;
  } | null;
  top_risk: { type: string; detail: string } | null;
  [key: string]: unknown;
}
