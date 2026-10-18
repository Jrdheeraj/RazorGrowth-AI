/**
 * RazorGrowth AI — backend API contract types.
 * Mirrors the FastAPI response schemas (Phase 3–6).
 */

/* ── Analytics ────────────────────────────────────────────────────────── */

export interface AnalyticsOverviewResponse {
  merchant_id: string;
  period_days: number;
  generated_at: string;
  revenue: {
    current_period: number;
    previous_period: number;
    change_percentage: number | null;
    trend: string;
  };
  orders: {
    total_orders: number;
    completed_orders: number;
    cancelled_orders: number;
    average_order_value: number;
    orders_by_status: Record<string, number>;
  };
  customers: {
    total_customers: number;
    new_customers: number;
    returning_customers: number;
    repeat_customers: number;
    at_risk_customers: number;
    churned_customers: number;
    average_ltv: number;
  };
  opportunities: Record<string, unknown>;
  recommendations: Record<string, unknown>;
  executions: Record<string, unknown>;
  agent_activity: Record<string, unknown>;
  experiments: Record<string, unknown>;
  predicted_vs_actual: unknown[];
}

export interface RevenueTimeSeriesResponse {
  merchant_id: string;
  period_days: number;
  data: Array<{ date: string; value: number | string }>;
}

export interface OrderTimeSeriesResponse {
  merchant_id: string;
  period_days: number;
  data: Array<{ date: string; value: number | string }>;
}

export interface CustomerTimeSeriesResponse {
  merchant_id: string;
  period_days: number;
  data: Array<{ date: string; value: number | string }>;
}

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
  /** Account creation timestamp (ISO) — absent on older backend payloads. */
  member_since?: string | null;
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

export interface GrowthRadarResponse {
  merchant_id: string;
  generated_at: string;
  overall_health: string;
  metrics: {
    captured_revenue: number;
    captured_transactions: number;
    successful_payments: number;
    failed_payments: number;
    total_customers: number;
    repeat_customers: number;
    total_orders: number;
    average_order_value: number;
  };
  data_sufficiency: {
    status: string;
    message: string;
    minimum_required: number;
    available: number;
  };
  signals: Array<{
    signal: string;
    title: string;
    observed_data: Record<string, unknown>;
    calculated_metric: string;
    opportunity: string;
    confidence: number;
    reason: string;
    recommended_action: string;
  }>;
}

export interface RAGContextResponse {
  merchant_id: string;
  query: string;
  status: string;
  data_sufficiency: Record<string, unknown>;
  verified_facts: Array<{ fact: string; value: number; verified: boolean; source: string }>;
  derived_metrics: Record<string, unknown>;
  retrieved_context: Array<Record<string, unknown>>;
  inference_allowed: boolean;
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
  orchestrator_run_id: string | null;
  started_at: string;
  completed_at: string | null;
  total_latency_ms: number;
  llm_latency_ms: number;
  db_latency_ms: number;
  tool_latency_ms: number;
  opportunities_created: number;
  actions_proposed: number;
  insights_generated?: number;
  signals_detected?: number;
  output_summary?: Record<string, unknown> | null;
  llm_provider: string | null;
  llm_model: string | null;
  tools_used: unknown;
  errors: string[] | null;
}

export type AgentRunRecord = AgentRunRow;

export interface AgentRunsResponse {
  runs: AgentRunRow[];
}

export interface AgentRunRequest {
  mode: "fast" | "deep" | "growth_team" | "team";
  window_days?: number;
  propose_actions?: boolean;
  merchant_id?: string;
  objective?: string;
  params?: Record<string, unknown>;
}

export interface ActionPlanItem {
  title: string;
  assigned_to: string;
  priority: string;
  expected_impact: string;
  next_steps: string;
}

export interface ActionPlan {
  objective: string;
  executive_summary: string;
  initiatives: ActionPlanItem[];
  status: string;
}

export interface OrchestrationAgentOutput {
  agent: string;
  status: string;
  opportunities_created: number;
  actions_proposed: number;
  insights_generated: number;
  signals_detected: number;
  experiments_proposed: number;
  errors: string[];
  latency_ms?: {
    total: number;
    llm?: number;
    db?: number;
    tool?: number;
  };
  output?: {
    summary?: string;
    recommendations?: string[];
    action_plan?: ActionPlan;
    [key: string]: unknown;
  };
}

export interface OrchestratorRunResponse {
  orchestrator_run_id: string;
  merchant_id: string;
  mode: string;
  status?: string;
  debate_id?: string | null;
  action_plan?: ActionPlan | null;
  agents?: OrchestrationAgentOutput[];
  totals?: {
    opportunities_created: number;
    actions_proposed: number;
    signals_detected: number;
    insights_generated: number;
    experiments_proposed: number;
    failed_agents: number;
  };
  ranked_opportunities?: Array<{
    id?: string;
    title: string;
    type?: string;
    expected_revenue?: number;
    confidence?: number;
    [key: string]: unknown;
  }>;
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

/** Full product as returned by GET /api/products (AI-readable catalog). */
export interface ProductResponse {
  id: string;
  merchant_id: string;
  name: string;
  description: string | null;
  category: string;
  price: number;
  sku: string | null;
  stock_quantity: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProductListResponse {
  products: ProductResponse[];
  total: number;
}

/* ── Catalog orders (GET /api/orders — tenant-isolated) ─────────────────── */

export interface CatalogOrderItem {
  id: string;
  product_id: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

export interface CatalogOrder {
  id: string;
  merchant_id: string;
  customer_id: string;
  order_number: string;
  status: string;
  subtotal: number;
  discount: number;
  tax: number;
  total: number;
  currency: string;
  items: CatalogOrderItem[];
  created_at: string;
  updated_at: string;
}

/** NOTE: `total` mirrors the backend's limited listing, not a warehouse count. */
export interface CatalogOrderListResponse {
  orders: CatalogOrder[];
  total: number;
}

/* ── Product Agent (real backend, GET /api/product-agi/*) ───────────────────
 * Every field below is produced by the Product Agent backend from measured
 * data. `null` always means "not computable from the available data" — it
 * is never a placeholder zero and never a frontend substitute.
 */

export interface ProductAgentInsight {
  id: string;
  icon: "chart" | "alert" | "doc" | "search-check" | "git-branch" | "target" | "box" | "branch";
  value: string;
  detail: string;
}

export interface ProductAgentRecommendationEvidence {
  source: string;
  source_kind: string;
  statement: string;
  tool: string | null;
}

export interface ProductAgentRecommendation {
  id: string;
  run_id: string;
  type: string;
  title: string;
  problem: string;
  recommendation: string;
  why_now: string;
  confidence: number;
  evidence: ProductAgentRecommendationEvidence[];
  /** `status: "unavailable"` means the impact genuinely could not be computed. */
  expected_impact: { status: "available" | "unavailable"; text: string; basis?: string } | null;
  risk: string | null;
  affected_products: string[];
  basis: string | null;
  action_required: boolean;
  approval_required: boolean;
  status: string;
  /** Canonical agent_actions state: REQUIRED | APPROVED | EXECUTING | ... */
  approval_state: string | null;
  executed: boolean;
  action_id: string | null;
  data: Record<string, unknown> | null;
  created_at: string | null;
}

export interface ProductAgentFinding {
  id: string;
  run_id: string;
  type: string;
  title: string;
  description: string;
  severity: "info" | "low" | "medium" | "high";
  confidence: number | null;
  evidence: ProductAgentRecommendationEvidence[];
  product_ids: string[];
  data: Record<string, unknown> | null;
  created_at: string | null;
}

export interface ProductAgentWorkItem {
  id: string;
  title: string;
  state: string;
  meta: string;
}

export interface ProductAgentActivityItem {
  id: string;
  title: string;
  time: string | null;
  state: "active" | "completed" | "failed";
  stage: string;
  event_type: string;
  seq: number;
}

export interface ProductAgentPlatform {
  key: string;
  name: string;
  status: "connected" | "not_connected";
  blurb: string;
  meta: string;
  /** False means this platform has no integration in the codebase at all. */
  integration_implemented: boolean;
}

export interface ProductAgentWorkflowStep {
  top: string;
  bottom: string;
}

export interface ProductAgentProductRow {
  product_id: string;
  name: string;
  sku: string | null;
  category: string;
  price_inr: number;
  stock_quantity: number;
  units_sold: number;
  revenue_inr: number;
  orders: number;
  /** Recent vs prior half-window unit change, or null when no baseline exists. */
  trend_pct: number | null;
  revenue_share_pct: number | null;
  status: string;
  low_stock: boolean;
}

export interface ProductAgentCatalogSummary {
  window_days: number;
  generated_at: string | null;
  product_count: number;
  total_units: number;
  in_stock_count: number;
  out_of_stock_count: number;
  category_count: number;
  categories: string[];
  catalog_value_inr: number;
  low_stock_threshold: number;
  low_stock_count: number;
  total_units_sold: number;
  total_revenue_inr: number;
  settled_orders: number;
  average_order_value_inr: number | null;
  never_sold_count: number;
  multi_item_order_count: number;
  data_completeness: "full" | "no_data";
}

export interface ProductAgentCatalog {
  window_days: number;
  generated_at: string | null;
  summary: ProductAgentCatalogSummary;
  catalog_health: {
    status: string;
    score: number | null;
    grade: string;
    components?: Record<string, number>;
    reason?: string;
  };
  products: ProductAgentProductRow[];
  segments: Record<string, ProductAgentProductRow[]>;
  segment_status: Record<string, string | undefined>;
}

export interface ProductAgentStatusResponse {
  has_run: boolean;
  run_id: string | null;
  /** Shared AI Team analysis cycle the displayed run belongs to. */
  analysis_cycle_id?: string | null;
  /** Always true: the Product Agent is dispatched by the AI Team cycle,
   *  never by this dashboard. */
  managed_by_ai_team?: boolean;
  status: string | null;
  stage: string | null;
  /** 0-based index into workflow_steps, or -1 before the first run. */
  step_index: number;
  status_label: string;
  needs_approval: boolean;
  approval_status?: string | null;
  headline: string;
  support: string;
  llm?: { provider: string | null; model: string | null; degraded: boolean };
  insights: ProductAgentInsight[];
  recommendations: ProductAgentRecommendation[];
  work: ProductAgentWorkItem[];
  activity: ProductAgentActivityItem[];
  learning_insight: string;
  platforms: ProductAgentPlatform[];
  metrics: Record<string, number | null>;
  catalog: ProductAgentCatalog;
  workflow_steps: ProductAgentWorkflowStep[];
  verification?: Record<string, unknown> | null;
  knowledge_gaps?: string[];
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  result?: Record<string, unknown> | null;
  errors?: string[];
}

export interface ProductAgentCatalogResponse extends ProductAgentCatalog {}

export interface ProductAgentStartResponse {
  run_id: string;
  status: string;
  stage: string;
  objective: string;
  /** True when the request joined an already in-flight run rather than
   *  creating a second one. */
  already_running?: boolean;
  analysis_cycle_id?: string | null;
  llm_configured: boolean;
  llm_provider: string | null;
  llm_model: string | null;
}

export interface ProductAgentRun {
  id: string;
  merchant_id: string;
  objective: string;
  status: string;
  stage: string;
  /** Shared AI Team analysis cycle this run belongs to, when dispatched
   *  by Start Analysis. Null for a run with no cycle link. */
  analysis_cycle_id?: string | null;
  approval_status: string | null;
  summary: string | null;
  metrics: Record<string, number | null>;
  products_analyzed: number;
  opportunities_found: number;
  recommendations_created: number;
  llm_provider: string | null;
  llm_model: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  state: Record<string, unknown>;
  result: Record<string, unknown> | null;
  errors: string[];
}

export interface ProductAgentRunListResponse {
  runs: ProductAgentRun[];
}

export interface ProductAgentFindingListResponse {
  run_id: string;
  findings: ProductAgentFinding[];
}

export interface ProductAgentRecommendationListResponse {
  run_id: string;
  recommendations: ProductAgentRecommendation[];
}

export interface ProductAgentActivityResponse {
  run_id: string;
  status: string;
  stage: string;
  events: {
    id: string;
    run_id: string;
    seq: number;
    stage: string;
    event_type: string;
    message: string;
    data: Record<string, unknown>;
    created_at: string;
  }[];
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

export interface ActionDeleteResponse {
  deleted: boolean;
  action_id: string;
  message?: string;
}

export interface ActionBulkDeleteDetail {
  action_id: string;
  status: string;
  result?: string;
  reason?: string;
  error?: string;
}

export interface ActionBulkDeleteResponse {
  eligible: number;
  deleted: number;
  skipped: number;
  failed: number;
  message: string;
  details: ActionBulkDeleteDetail[];
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

/* ── Checkout / Razorpay TEST ───────────────────────────────────────────── */

export interface CheckoutSessionRequest {
  amount: number;
  currency?: string;
  description?: string;
  customer_email?: string;
  customer_contact?: string;
  receipt?: string;
  notes?: Record<string, string>;
  callback_url?: string;
}

export interface CheckoutSessionResponse {
  source: string;
  razorpay_order_id: string;
  razorpay_payment_link_id: string | null;
  short_url: string | null;
  amount: number;
  currency: string;
  key_id: string;
}

export interface PaymentVerificationRequest {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
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

/* ── Checkout / Razorpay TEST ───────────────────────────────────────────── */

export interface CheckoutSessionRequest {
  amount: number;
  currency?: string;
  description?: string;
  customer_email?: string;
  customer_contact?: string;
  receipt?: string;
  notes?: Record<string, string>;
  callback_url?: string;
}

export interface CheckoutSessionResponse {
  source: string;
  razorpay_order_id: string;
  razorpay_payment_link_id: string | null;
  short_url: string | null;
  amount: number;
  currency: string;
  key_id: string;
}

export interface PaymentVerificationRequest {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export interface PaymentVerificationResponse {
  verified: boolean;
  payment_id: string | null;
}

/* ── Agent Debate Dashboard ────────────────────────────────────────────── */

export interface AgentDebateListItem {
  id: string;
  merchant_id?: string;
  objective: string;
  status: string;
  manager_agent_id?: string | null;
  context?: Record<string, unknown> | null;
  final_synthesis?: string | null;
  recommendation_id?: string | null;
  created_at: string;
  updated_at: string;
  current_round?: number;
}

export interface AgentDebateListResponse {
  debates: AgentDebateListItem[];
}

export interface AgentDebateCreateRequest {
  objective: string;
  context?: Record<string, unknown> | null;
}

export type AgentDebateResponse = AgentDebateListItem;

export interface RazorpayIngestResponse {
  source: string;
  customers: Record<string, number>;
  orders: Record<string, number>;
  payments: Record<string, number>;
  errors: string[];
}

export interface AgentFinding {
  id: string;
  agent_specialty: string;
  finding_type: "supporting" | "opposing" | "neutral" | "uncertainty";
  title: string;
  description: string | null;
  evidence: Array<Record<string, unknown>> | null;
  confidence: number;
  uncertainty_notes: string | null;
  supports_recommendation: boolean | null;
}

export interface AgentFindingListResponse {
  findings: AgentFinding[];
}

export interface AgentMessage {
  id: string;
  from_agent: string;
  to_agent: string | null;
  message_type: string;
  content: string;
  references: unknown[] | null;
  created_at: string;
}

export interface AgentMessageListResponse {
  messages: AgentMessage[];
}

export interface AgentDebateRoundStatus {
  debate_id: string;
  current_round: number;
  status: string;
  objective: string;
  tasks: Array<{ id: string; assigned_to: string; title: string; status: string }>;
  findings_summary: {
    total: number;
    by_type: { supporting: number; opposing: number; neutral: number; uncertainty: number };
    by_agent: Record<string, number>;
  };
  rounds: Record<string, Array<{ from: string; to: string | null; type: string; content: string }>>;
}

export interface AgentDashboardAgent {
  specialty: string;
  name: string;
  description: string;
  status: string;
  task_id: string | null;
  findings_count: number;
  supporting_findings: number;
  opposing_findings: number;
  uncertainty_findings: number;
  confidence_avg: number | null;
  evidence_summary: { sources: string[] } | null;
  output_summary: Record<string, unknown> | null;
}

export interface AgentDashboardResponse {
  debate_id: string;
  objective: string;
  debate_status: string;
  rag_context: {
    status: string;
    data_sufficiency: Record<string, unknown>;
    verified_facts: Array<{ fact: string; value: number; verified: boolean; source: string }>;
    derived_metrics: Record<string, unknown>;
    retrieved_context: Array<Record<string, unknown>>;
    inference_allowed: boolean;
  } | null;
  agents: AgentDashboardAgent[];
  total_findings: number;
  findings_by_type: {
    supporting: number;
    opposing: number;
    neutral: number;
    uncertainty: number;
  };
  final_synthesis: string | null;
  recommendation: string | null;
}


/* -- Marketing Agent — autonomous marketing employee ---------------------- */

export interface MarketingStackEntry {
  key: string;
  label: string;
  status: string;
  description: string;
  tools: string[];
  capabilities: string[];
  provider?: string | null;
  account_id?: string | null;
  account_name?: string | null;
  last_verified_at?: string | null;
  connection?: MarketingIntegrationConnection | null;
}

export interface MarketingIntegrationConnection {
  provider: string;
  integration_type: string;
  label: string;
  status: string;
  account_id: string | null;
  account_name: string | null;
  metadata: Record<string, unknown>;
  capabilities: string[];
  read_actions: string[];
  write_actions: string[];
  writes_require_approval: boolean;
  last_verified_at: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MarketingIntegrationTestResult {
  ok: boolean;
  provider: string;
  error_code: string | null;
  message: string | null;
  account: Record<string, unknown>;
  verified_at: string | null;
}

export interface MarketingIntegrationAuditEvent {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id: string | null;
  entity_id: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface MarketingAGIStatus {
  agent: string;
  llm_configured: boolean;
  llm_provider: string | null;
  llm_model: string | null;
  integration_status: Record<string, string>;
  marketing_stack?: MarketingStackEntry[];
  tools_available: number;
  workflows_available: number;
  /** MCP tool-connectivity layer summary (counts + servers only). */
  mcp?: {
    enabled?: boolean;
    tools?: number;
    read_tools?: number;
    write_tools?: number;
    approval_required_tools?: number;
    internal_tools?: number;
    external_tools?: number;
    servers?: string[];
  };
}

/** One MCP tool invocation, as the backend recorded it for this run. */
export interface MarketingAGIMCPToolCall {
  tool: string;
  server: string;
  provider: string;
  status: "success" | "error" | "denied" | string;
  read_only: boolean;
  requires_approval: boolean;
  risk_level: string;
  duration_ms?: number;
  error_code?: string | null;
  error_message?: string | null;
  cached?: boolean;
  retries?: number;
  summary?: string;
  args?: Record<string, unknown>;
  ts?: string | null;
}

export interface MarketingAGIRunEvent {
  id: string;
  run_id: string;
  /** Logical action this lifecycle event belongs to (null for run details). */
  action_id?: string | null;
  seq: number;
  phase: string;
  event_type: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface MarketingAGIStateSummary {
  objective: string | null;
  observations: string[];
  hypotheses: Array<{
    statement: string;
    confidence: number;
    status: string;
    supporting_evidence: string[];
    opposing_evidence: string[];
    next_investigation: string | null;
  }>;
  knowledge_gaps: string[];
  evidence: Array<{ source: string; source_kind: string; statement: string }>;
  retrieval_log: Array<{
    question: string;
    rounds: number;
    strategy: string;
    sufficient: boolean;
    gaps: string[];
    retrievals: Array<{ query: string; tool: string; item_count: number; statements: string[] }>;
  }>;
  tool_calls: Array<{ tool: string; params: Record<string, unknown>; ok: boolean; latency_ms?: number; ts?: string; summary?: string }>;
  /** MCP tool calls for this run. Safe metadata only. */
  mcp_calls?: MarketingAGIMCPToolCall[];
  workflow: string | null;
  plan: Array<{ step: string; tool: string; status: string }>;
  campaign_draft: Record<string, unknown> | null;
  verification: {
    passed: boolean;
    checks: Array<{ name: string; passed: boolean; detail: string }>;
    failed: string[];
  } | null;
  prepared_action: { action_id: string; status: string; approval_state: string } | null;
  iterations: number;
  tool_call_count: number;
  duplicate_tool_calls: number;
  errors: string[];
  llm_calls: number;
  llm_decisions: Array<{
    decision_type: string;
    provider: string | null;
    model: string | null;
    latency_ms?: number;
    success: boolean;
    tool?: string;
    error?: string;
  }>;
  reasoning_status: string;
  current_decision: string | null;
  reasoning_summary: string | null;
  llm_degraded: boolean;
}

export interface MarketingAGIRun {
  id: string;
  merchant_id: string;
  objective: string;
  status: string;
  phase: string;
  iterations: number;
  tool_call_count: number;
  analysis_cycle_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  /** Canonical persisted action instants — Recent Work MUST render these. */
  action_created_at?: string | null;
  action_updated_at?: string | null;
  action_completed_at?: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  state: MarketingAGIStateSummary;
  result: Record<string, unknown> | null;
  errors: string[];
}

export interface MarketingAGIRunListResponse {
  runs: MarketingAGIRun[];
}

export interface MarketingAGIEventsResponse {
  run_id: string;
  events: MarketingAGIRunEvent[];
}

export interface MarketingAGICampaign {
  id: string;
  run_id: string | null;
  campaign_key: string;
  workflow: string;
  name: string;
  objective: string;
  channel: string;
  integration_status: string;
  lifecycle: string;
  audience_count: number;
  audience: Record<string, unknown> | null;
  content: {
    message?: string;
    subject_variants?: string[];
    cta?: string;
    timing?: string;
    variants?: string[];
  } | null;
  expected_impact: {
    rationale?: string;
    estimated_revenue_inr?: number;
    risks?: string[];
  } | null;
  estimated_revenue_inr: number | null;
  success_metric: string | null;
  evidence_refs: string[];
  verification: Record<string, unknown> | null;
  action_id: string | null;
  action_status: string | null;
  created_at: string;
}

export interface MarketingAGICampaignListResponse {
  campaigns: MarketingAGICampaign[];
}

export interface MarketingAGILearning {
  id: string;
  campaign_id: string | null;
  action_id: string | null;
  status: string;
  expected: Record<string, unknown> | null;
  actual: Record<string, unknown> | null;
  verdict: string | null;
  insights: string | null;
  created_at: string;
}

export interface MarketingAGILearningListResponse {
  learnings: MarketingAGILearning[];
}

export interface MarketingAGIHandoff {
  id: string;
  run_id: string | null;
  specialist: string;
  status: string;
  request: Record<string, unknown> | null;
  response: Record<string, unknown> | null;
  responded_at: string | null;
  created_at: string;
}

export interface MarketingAGIHandoffListResponse {
  handoffs: MarketingAGIHandoff[];
}

export interface MarketingAGIToolCatalogResponse {
  tools: Array<{
    name: string;
    category: string;
    description: string;
    capabilities: string[];
    integration_status: string;
  }>;
  /** Normalized MCP catalog with each tool's guardrail declaration. */
  mcp_tools?: Array<{
    name: string;
    description: string;
    provider: string;
    phase: string;
    read_only: boolean;
    requires_approval: boolean;
    requires_integration: string | null;
    risk_level: string;
    input_schema: Record<string, unknown>;
    integration_status?: string;
  }>;
  mcp_policies?: Array<{
    name: string;
    provider: string;
    read_only: boolean;
    external_write: boolean;
    requires_approval: boolean;
    requires_execution_enabled: boolean;
    requires_integration: string | null;
    risk_level: string;
    tenant_scoped: boolean;
    phase: string;
  }>;
  mcp_allowlists?: {
    read?: string[];
    write?: string[];
    approval_required?: string[];
    internal?: string[];
    external?: string[];
  };
}

/* -- Designer Agent workspace (/api/designer/*) ---------------------------
 *
 * These mirror the backend's Designer contracts. Three distinctions matter and
 * are deliberately preserved here rather than collapsed:
 *
 *   DesignAssetKind      brief | specification | variant | rendered_image.
 *                        A structured brief is NOT a rendered image, and the
 *                        dashboard must never present one as the other.
 *   image_generation     the REAL provider state. `unavailable` means no
 *                        provider is configured; it never carries an asset
 *                        reference, so a placeholder cannot masquerade as a
 *                        generated creative.
 *   review_status        a HUMAN decision. The agent may move work INTO
 *                        `pending_review`; it can never move it out.
 */

export type DesignProjectStatus = "active" | "archived";

export type DesignAssetKind =
  | "brief"
  | "specification"
  | "variant"
  | "rendered_image";

export type DesignAssetStatus = "draft" | "ready_for_review" | "archived";

export type DesignReviewStatus =
  | "draft"
  | "pending_review"
  | "in_review"
  | "approved"
  | "changes_requested"
  | "rejected";

export type ImageGenerationState =
  | "unavailable"
  | "pending"
  | "running"
  | "completed"
  | "failed";

export interface DesignerImageGeneration {
  /** `available` means configured and ready; `completed` means a REAL,
   * validated, durably stored image exists. Never conflated. */
  status: ImageGenerationState | "available";
  provider: string | null;
  reason: string | null;
  asset_reference: string | null;
  /** Provider model label, e.g. cloudflare-flux-1-schnell. */
  model?: string;
  /** Present only on a real success. */
  rendered_asset_id?: string;
  content_type?: string;
  byte_size?: number;
  width?: number;
  height?: number;
  sha256?: string;
  version_id?: string;
  steps?: number | null;
  /** Stable failure code, e.g. PROVIDER_TIMEOUT. Never contains provider text. */
  code?: string;
  detail?: string;
}

/** Metadata for one stored image. Never carries the bytes themselves. */
export interface RenderedAsset {
  id: string;
  asset_id: string;
  version_id: string;
  content_type: string;
  byte_size: number;
  sha256: string;
  width: number;
  height: number;
  provider: string;
  model: string;
  steps: number | null;
  created_at: string | null;
}

export interface RenderedAssetList {
  assets: RenderedAsset[];
  total: number;
  usage_today: { images: number; bytes: number };
}

export interface DesignProject {
  id: string;
  merchant_id: string;
  title: string;
  objective: string;
  project_type: string;
  status: DesignProjectStatus;
  analysis_cycle_id: string | null;
  debate_id: string | null;
  source_signal_type: string | null;
  source_signal_id: string | null;
  source_opportunity_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DesignProjectList {
  projects: DesignProject[];
  total: number;
}

/** One provenance-tagged claim. `basis` is what separates fact from guess. */
export interface DesignerEvidence {
  statement: string;
  basis: "observed" | "derived" | "hypothesis" | "unknown";
  source?: string | null;
  value?: number | null;
}

export interface DesignerVariant {
  variant_key: string;
  title: string;
  objective: string;
  differences: string[];
  intended_audience?: string | null;
  channel?: string | null;
  rationale: string;
  trade_offs: string[];
  evaluation_method: string;
  confidence?: number | null;
  evidence_refs: number[];
}

export interface CreativeBrief {
  id: string;
  project_id: string;
  version: number;
  is_current: number;
  title: string;
  objective: string;
  audience: string | null;
  channel: string | null;
  format_spec: string | null;
  brand_constraints: string[] | null;
  content_requirements: string[] | null;
  layout_direction: string | null;
  color_guidance: string | null;
  typography_guidance: string | null;
  accessibility_considerations: string[] | null;
  dependencies: string[] | null;
  open_questions: string[] | null;
  assumptions: string[] | null;
  evidence: DesignerEvidence[] | null;
  radar_references: Array<Record<string, unknown>> | null;
  variants: DesignerVariant[] | null;
  review_status: DesignReviewStatus;
  review_notes: string | null;
  confidence: number | null;
  validation: Record<string, unknown> | null;
  llm_provider: string | null;
  llm_model: string | null;
  analysis_cycle_id: string | null;
  agent_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreativeBriefList {
  briefs: CreativeBrief[];
  total: number;
}

export interface DesignAsset {
  id: string;
  merchant_id: string;
  project_id: string;
  brief_id: string | null;
  kind: DesignAssetKind;
  title: string;
  variant_key: string | null;
  status: DesignAssetStatus;
  review_status: DesignReviewStatus;
  current_version_id: string | null;
  version_count: number;
  image_generation: DesignerImageGeneration | null;
  created_at: string;
  updated_at: string;
}

export interface DesignAssetList {
  assets: DesignAsset[];
  total: number;
}

export interface DesignAssetVersion {
  id: string;
  asset_id: string;
  version: number;
  content: Record<string, unknown>;
  rationale: string | null;
  change_summary: string | null;
  evidence: unknown[] | null;
  created_by: string | null;
  created_at: string;
}

export interface DesignAssetVersionList {
  asset: DesignAsset;
  versions: DesignAssetVersion[];
}

/**
 * External provider state. A provider is `connected` ONLY when the backend
 * found a real IntegrationConnection row for this workspace; a card existing
 * is never evidence of a connection.
 */
export interface DesignerIntegration {
  provider: string;
  label: string;
  purpose: string;
  status: "connected" | "setup_required" | "unsupported";
  supported: boolean;
  detail: string;
}

export interface DesignerCapability {
  key: string;
  label: string;
  status: string;
  detail: string;
}

export interface DesignerStatusMetric {
  key: string;
  label: string;
  value: number;
  hint: string;
}

export interface DesignerStatus {
  agent_registered: boolean;
  agent_description: string | null;
  capabilities: DesignerCapability[];
  integrations: DesignerIntegration[];
  image_generation: DesignerImageGeneration;
  latest_project: DesignProject | null;
  latest_brief: CreativeBrief | null;
  metrics: DesignerStatusMetric[];
  counts: Record<string, number>;
  last_updated: string;
}

export interface DesignerActivityEntry {
  id: string;
  kind: "project" | "brief" | "asset" | "run" | "review";
  title: string;
  detail: string | null;
  status: string | null;
  at: string | null;
}

export interface DesignerActivityList {
  items: DesignerActivityEntry[];
}

export interface DesignerUxFinding {
  title: string;
  observed_issue: string;
  affected_experience: string;
  user_impact_hypothesis: string;
  proposed_improvement: string;
  expected_impact_direction: "helps" | "hurts" | "neutral";
  expected_impact_magnitude: "low" | "medium" | "high";
  confidence: number | null;
  evidence_refs: number[];
  validation_recommendation: string | null;
  product_handoff: string | null;
}

export interface DesignerUxAuditResult {
  findings: DesignerUxFinding[];
  evidence: DesignerEvidence[];
  radar_references: Array<Record<string, unknown>>;
  /** True only when real authorized observations backed the findings. */
  sufficient_context: boolean;
  /** Why an audit could not run, when it could not. Null = it ran. */
  unavailable_reason: string | null;
  data_sufficiency: Record<string, unknown> | null;
}

export interface DesignerHandoff {
  handoff_id: string;
  target: string;
  status: string;
  brief_id: string;
  created_at: string;
  /** Present only when the handoff proposed an existing action type. The
   *  action still faces the full human approval + EXECUTION_ENABLED gate. */
  action_id: string | null;
}

/* ── Personalization ─────────────────────────────────────────────────── */

export interface PersonalizationDecisionRow {
  decision_id: string;
  customer_id: string;
  recommended_action: string;
  cohort: string;
  score: number;
  rationale: Record<string, unknown>;
  recommended_product_ids: string[];
  status: string;
  observed_revenue: number | null;
  created_at: string;
}
