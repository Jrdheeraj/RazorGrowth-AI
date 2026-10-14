/**
 * Typed API client for the RazorGrowth AI FastAPI backend.
 *
 * - Base URL comes from VITE_API_BASE_URL (empty ⇒ same-origin; the Vite dev
 *   server proxies /api to 127.0.0.1:8000).
 * - Bearer token is attached automatically when present (lib/auth.ts).
 * - A 401 clears the stored session so protected routes can react.
 */

import { getToken, clearToken } from "./auth";
import type {
  ActionListResponse,
  ActionTransitionResponse,
  AgentRunRequest,
  AgentRunsResponse,
  AgentsListResponse,
  AuditEventListResponse,
  AccessibleMerchantsResponse,
  ExecutionResponse,
  ExperimentsResponse,
  GrowthBrief,
  GrowthMemoryResponse,
  CustomerInsightsResponse,
  MeResponse,
  OrchestratorRunResponse,
  RadarResponse,
  RankedOpportunitiesResponse,
  SimulationRequest,
  SimulationResult,
  SimulationsResponse,
  TokenResponse,
  CheckoutSessionRequest,
  CheckoutSessionResponse,
  PaymentVerificationRequest,
  PaymentVerificationResponse,
  GrowthRadarResponse,
  RAGContextResponse,
  AgentDashboardResponse,
  AgentDashboardAgent,
  ProductResponse,
  ProductListResponse,
  CatalogOrderListResponse,
  ProductAgentStatusResponse,
  ProductAgentCatalogResponse,
  ProductAgentPlatform,
  ProductAgentStartResponse,
  ProductAgentRun,
  ProductAgentRunListResponse,
  ProductAgentFindingListResponse,
  ProductAgentRecommendationListResponse,
  ProductAgentActivityResponse,
  AnalyticsOverviewResponse,
  RevenueTimeSeriesResponse,
  OrderTimeSeriesResponse,
  CustomerTimeSeriesResponse,
} from "../types/api";

export type {
  ActionListResponse,
  ActionTransitionResponse,
  AgentRunRequest,
  AgentRunsResponse,
  AgentsListResponse,
  AuditEventListResponse,
  AccessibleMerchantsResponse,
  ExecutionResponse,
  ExperimentsResponse,
  GrowthBrief,
  GrowthMemoryResponse,
  CustomerInsightsResponse,
  MeResponse,
  OrchestratorRunResponse,
  RadarResponse,
  RankedOpportunitiesResponse,
  SimulationRequest,
  SimulationResult,
  SimulationsResponse,
  TokenResponse,
  CheckoutSessionRequest,
  CheckoutSessionResponse,
  PaymentVerificationRequest,
  PaymentVerificationResponse,
  GrowthRadarResponse,
  RAGContextResponse,
  AgentDashboardResponse,
  AgentDashboardAgent,
  ProductResponse,
  ProductListResponse,
  CatalogOrderListResponse,
  ProductAgentStatusResponse,
  ProductAgentCatalogResponse,
  ProductAgentPlatform,
  ProductAgentStartResponse,
  ProductAgentRun,
  ProductAgentRunListResponse,
  ProductAgentFindingListResponse,
  ProductAgentRecommendationListResponse,
  ProductAgentActivityResponse,
  AnalyticsOverviewResponse,
  RevenueTimeSeriesResponse,
  OrderTimeSeriesResponse,
  CustomerTimeSeriesResponse,
};
export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: opts.method ?? "GET",
      credentials: "same-origin",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_ERROR: backend unreachable");
  }

  if (res.status === 401) {
    // Session no longer valid — drop it so route guards react on next tick.
    clearToken();
  }

  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const d: unknown = detail?.detail;
    const message =
      typeof d === "string"
        ? d
        : d && typeof d === "object" && "message" in (d as Record<string, unknown>)
          ? String((d as Record<string, unknown>).message)
          : d && typeof d === "object" && "error" in (d as Record<string, unknown>)
            ? String((d as Record<string, unknown>).error)
            : `API error ${res.status}`;
    const code =
      d && typeof d === "object" && "code" in (d as Record<string, unknown>)
        ? String((d as Record<string, unknown>).code)
        : undefined;
    throw new ApiError(res.status, message, code);
  }

  return (await res.json()) as T;
}

/**
 * Binary variant of `request<T>()`, sharing its auth header, base URL, 401
 * token-drop and error normalisation verbatim.
 *
 * Needed because this app authenticates with a Bearer token in localStorage,
 * sent as a request HEADER. A plain `<img src="/api/...">` cannot set headers,
 * so an image endpoint is unreachable from an image tag — the bytes must be
 * fetched as a Blob and shown through an object URL instead.
 *
 * Kept next to `request()` deliberately: a second, divergent copy of the
 * auth or error handling is exactly how the two drift apart.
 */
async function requestBlob(path: string, signal?: AbortSignal): Promise<Blob> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: "GET",
      credentials: "same-origin",
      headers,
      signal,
    });
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK_ERROR: backend unreachable");
  }

  if (res.status === 401) clearToken();

  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const d: unknown = detail?.detail;
    const message =
      typeof d === "string"
        ? d
        : d && typeof d === "object" && "message" in (d as Record<string, unknown>)
          ? String((d as Record<string, unknown>).message)
          : `API error ${res.status}`;
    throw new ApiError(res.status, message);
  }

  return await res.blob();
}

/* ── Auth ─────────────────────────────────────────────────────────────── */

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function register(
  email: string,
  password: string,
  full_name?: string,
): Promise<import("../types/api").UserOut> {
  return request("/api/auth/register", {
    method: "POST",
    body: { email, password, full_name },
  });
}

export function fetchMe(): Promise<MeResponse> {
  return request<MeResponse>("/api/auth/me");
}

export function fetchAccessibleMerchants(): Promise<AccessibleMerchantsResponse> {
  return request<AccessibleMerchantsResponse>("/api/auth/merchants");
}

/* ── Growth radar & opportunities ─────────────────────────────────────── */

export function fetchRadar(): Promise<RadarResponse> {
  return request<RadarResponse>("/api/radar");
}

export function fetchGrowthRadar(windowDays = 30): Promise<GrowthRadarResponse> {
  return request<GrowthRadarResponse>(`/api/growth/radar?window_days=${windowDays}`);
}

export function buildRAGContext(
  query: string,
  windowDays = 30,
): Promise<RAGContextResponse> {
  return request<RAGContextResponse>("/api/ai/rag/context", {
    method: "POST",
    body: { query, window_days: windowDays },
  });
}

export function fetchRankedOpportunities(): Promise<RankedOpportunitiesResponse> {
  return request<RankedOpportunitiesResponse>("/api/opportunities/ranked");
}

/* ── Analytics (for Growth Radar charts) ────────────────────────────────── */

export function fetchAnalyticsOverview(periodDays = 30): Promise<AnalyticsOverviewResponse> {
  return request<AnalyticsOverviewResponse>(`/api/analytics/overview?period_days=${periodDays}`);
}

export function fetchRevenueSeries(periodDays = 30, granularity: "day" | "week" | "month" = "day"): Promise<RevenueTimeSeriesResponse> {
  return request<RevenueTimeSeriesResponse>(`/api/analytics/revenue?period_days=${periodDays}&granularity=${granularity}`);
}

export function fetchOrdersTrend(periodDays = 30, granularity: "day" | "week" | "month" = "day"): Promise<OrderTimeSeriesResponse> {
  return request<OrderTimeSeriesResponse>(`/api/analytics/orders/trend?period_days=${periodDays}&granularity=${granularity}`);
}

export function fetchCustomersTrend(periodDays = 30, granularity: "day" | "week" | "month" = "day"): Promise<CustomerTimeSeriesResponse> {
  return request<CustomerTimeSeriesResponse>(`/api/analytics/customers/trend?period_days=${periodDays}&granularity=${granularity}`);
}

/* ── Agents / Investigation ───────────────────────────────────────────── */

export function fetchAgentsMeta(): Promise<AgentsListResponse> {
  return request<AgentsListResponse>("/api/agents");
}

export function fetchAgentRuns(limit = 50, orchestratorRunId?: string): Promise<AgentRunsResponse> {
  const qs = orchestratorRunId
    ? `/api/agents/runs?limit=${limit}&orchestrator_run_id=${encodeURIComponent(orchestratorRunId)}`
    : `/api/agents/runs?limit=${limit}`;
  return request<AgentRunsResponse>(qs);
}

/** Internal API — wrapped as a merchant-facing business action. */
export function runAgents(
  body: AgentRunRequest,
): Promise<OrchestratorRunResponse> {
  return request<OrchestratorRunResponse>("/api/agents/run", {
    method: "POST",
    body,
  });
}

/**
 * Start AI Team Work on merchant's real commerce data.
 * Executes all 13 specialized agents in the collaborative AI Team workspace pipeline.
 */
export function startAiTeamWork(
  objective = "Comprehensive commerce analysis and growth optimization",
  options?: { merchantId?: string; windowDays?: number },
): Promise<OrchestratorRunResponse> {
  return request<OrchestratorRunResponse>("/api/agents/run", {
    method: "POST",
    body: {
      mode: "team",
      objective,
      merchant_id: options?.merchantId,
      window_days: options?.windowDays ?? 30,
      propose_actions: true,
    },
  });
}

/**
 * Start an Agent Debate session for multi-agent cross-examination.
 * Merchants see this as a business action — the underlying mode is hidden.
 */
export function startInvestigation(
  objective: string,
  options?: { merchantId?: string; windowDays?: number },
): Promise<OrchestratorRunResponse> {
  return request<OrchestratorRunResponse>("/api/agents/run", {
    method: "POST",
    body: {
      mode: "growth_team",
      objective,
      merchant_id: options?.merchantId,
      window_days: options?.windowDays ?? 30,
      propose_actions: true,
    },
  });
}

/* ── Customer intelligence ────────────────────────────────────────────── */

export function fetchCustomerInsights(): Promise<CustomerInsightsResponse> {
  return request<CustomerInsightsResponse>("/api/customer-insights");
}

/* ── Actions / approval workflow ──────────────────────────────────────── */

export function fetchActions(): Promise<ActionListResponse> {
  return request<ActionListResponse>("/api/actions");
}

export function approveAction(actionId: string): Promise<ActionTransitionResponse> {
  return request<ActionTransitionResponse>(
    `/api/actions/${actionId}/approve`,
    { method: "POST" },
  );
}

export function rejectAction(actionId: string): Promise<ActionTransitionResponse> {
  return request<ActionTransitionResponse>(
    `/api/actions/${actionId}/reject`,
    { method: "POST" },
  );
}

export function executeAction(actionId: string): Promise<ExecutionResponse> {
  return request<ExecutionResponse>(`/api/actions/${actionId}/execute`, {
    method: "POST",
  });
}

export function fetchActionAudit(actionId: string): Promise<AuditEventListResponse> {
  return request<AuditEventListResponse>(`/api/actions/${actionId}/audit`);
}

/* ── Simulations & experiments ────────────────────────────────────────── */

export function createSimulation(
  body: SimulationRequest,
): Promise<SimulationResult> {
  return request<SimulationResult>("/api/simulations", {
    method: "POST",
    body,
  });
}

export function fetchSimulations(): Promise<SimulationsResponse> {
  return request<SimulationsResponse>("/api/simulations");
}

export function fetchExperiments(): Promise<ExperimentsResponse> {
  return request<ExperimentsResponse>("/api/experiments");
}

/* ── Memory & brief ───────────────────────────────────────────────────── */

export function fetchGrowthMemory(): Promise<GrowthMemoryResponse> {
  return request<GrowthMemoryResponse>("/api/growth-memory");
}

export function fetchGrowthBrief(): Promise<GrowthBrief> {
  return request<GrowthBrief>("/api/growth-brief");
}

/* ── Checkout / Razorpay TEST ───────────────────────────────────────────── */

export function createCheckoutSession(
  body: CheckoutSessionRequest,
): Promise<CheckoutSessionResponse> {
  return request<CheckoutSessionResponse>("/api/payments/checkout", {
    method: "POST",
    body,
  });
}

export function verifyPayment(
  body: PaymentVerificationRequest,
): Promise<PaymentVerificationResponse> {
  return request<PaymentVerificationResponse>("/api/payments/verify", {
    method: "POST",
    body,
  });
}

/* ── Products (AI-readable catalog) ────────────────────────────────────── */

export function fetchProducts(): Promise<ProductListResponse> {
  return request<ProductListResponse>("/api/products");
}

/** Orders for the caller's merchant (tenant-isolated). `limit` caps the page. */
export function fetchOrders(limit = 100, offset = 0): Promise<CatalogOrderListResponse> {
  return request<CatalogOrderListResponse>(`/api/orders?limit=${limit}&offset=${offset}`);
}

/**
 * Product Agent — the autonomous product-growth employee's control surface.
 *
 * NOTE: `startProductAgentRun` is retained for the API contract but is NOT
 * the Product Agent dashboard's trigger. The Product Agent joins the shared
 * AI Team analysis cycle started from the AI Team page's Start Analysis.
 *
 * `fetchProductAgentStatus` returns the complete dashboard read model
 * (header, business snapshot, progress stage, findings, recommendations,
 * real activity, honest platform states) in ONE request, so the page never
 * has to stitch several endpoints together or invent a value in between.
 */
export function fetchProductAgentStatus(
  windowDays?: number,
): Promise<ProductAgentStatusResponse> {
  const qs = windowDays ? `?window_days=${windowDays}` : "";
  return request<ProductAgentStatusResponse>(`/api/product-agi/status${qs}`);
}

export function fetchProductAgentCatalog(
  windowDays = 365,
): Promise<ProductAgentCatalogResponse> {
  return request<ProductAgentCatalogResponse>(
    `/api/product-agi/catalog?window_days=${windowDays}`,
  );
}

export function fetchProductAgentPlatforms(): Promise<{
  platforms: ProductAgentPlatform[];
}> {
  return request("/api/product-agi/platforms");
}

export function startProductAgentRun(
  windowDays = 365,
  objective?: string,
): Promise<ProductAgentStartResponse> {
  const qs = new URLSearchParams({ window_days: String(windowDays) });
  if (objective) qs.set("objective", objective);
  return request<ProductAgentStartResponse>(`/api/product-agi/runs?${qs}`, {
    method: "POST",
  });
}

export function fetchProductAgentRuns(
  analysisCycleId?: string,
): Promise<ProductAgentRunListResponse> {
  const qs = analysisCycleId
    ? `/api/product-agi/runs?limit=20&analysis_cycle_id=${encodeURIComponent(analysisCycleId)}`
    : "/api/product-agi/runs?limit=20";
  return request<ProductAgentRunListResponse>(qs);
}

export function fetchProductAgentRun(
  runId: string,
): Promise<ProductAgentRun> {
  return request<ProductAgentRun>(`/api/product-agi/runs/${runId}`);
}

export function fetchProductAgentFindings(
  runId: string,
): Promise<ProductAgentFindingListResponse> {
  return request<ProductAgentFindingListResponse>(
    `/api/product-agi/runs/${runId}/findings`,
  );
}

export function fetchProductAgentRecommendations(
  runId: string,
): Promise<ProductAgentRecommendationListResponse> {
  return request<ProductAgentRecommendationListResponse>(
    `/api/product-agi/runs/${runId}/recommendations`,
  );
}

export function fetchProductAgentActivity(
  runId: string,
  afterSeq = 0,
): Promise<ProductAgentActivityResponse> {
  return request<ProductAgentActivityResponse>(
    `/api/product-agi/runs/${runId}/activity?after_seq=${afterSeq}&limit=300`,
  );
}

export function cancelProductAgentRun(runId: string): Promise<ProductAgentRun> {
  return request<ProductAgentRun>(`/api/product-agi/runs/${runId}/cancel`, {
    method: "POST",
  });
}

/* ── Agent Debate Dashboard ────────────────────────────────────────────── */

export function fetchAgentDashboard(debateId: string): Promise<AgentDashboardResponse> {
  return request<AgentDashboardResponse>(`/api/agent-debates/${debateId}/dashboard`);
}

export function fetchDebateList(): Promise<import("../types/api").AgentDebateListResponse> {
  return request(`/api/agent-debates`);
}

export function fetchDebateFindings(debateId: string): Promise<import("../types/api").AgentFindingListResponse> {
  return request(`/api/agent-debates/${debateId}/findings`);
}

export function fetchDebateMessages(debateId: string): Promise<import("../types/api").AgentMessageListResponse> {
  return request(`/api/agent-debates/${debateId}/messages`);
}

export function fetchDebateRoundStatus(debateId: string): Promise<import("../types/api").AgentDebateRoundStatus> {
  return request(`/api/agent-debates/${debateId}/rounds`);
}

export function startAgentDebate(): Promise<import("../types/api").AgentDebateResponse> {
  return request("/api/agent-debates/start", { method: "POST" });
}

export function askAgentDebate(debateId: string, question: string): Promise<import("../types/api").AgentMessage> {
  return request(`/api/agent-debates/${debateId}/chat`, {
    method: "POST",
    body: { question },
  });
}


/* -- Marketing Agent — autonomous marketing employee ----------------------- */

export function fetchMarketingAGIStatus(): Promise<import("../types/api").MarketingAGIStatus> {
  return request("/api/marketing-agi/status");
}

export function startMarketingAGIRun(
  objective = "Find and prepare the highest-impact marketing work for this business",
): Promise<{ run_id: string; status: string; objective: string }> {
  return request("/api/marketing-agi/runs", {
    method: "POST",
    body: { objective },
  });
}

export function fetchMarketingAGIRuns(
  analysisCycleId?: string,
): Promise<import("../types/api").MarketingAGIRunListResponse> {
  const qs = analysisCycleId
    ? `/api/marketing-agi/runs?limit=20&analysis_cycle_id=${encodeURIComponent(analysisCycleId)}`
    : "/api/marketing-agi/runs?limit=20";
  return request(qs);
}

export function fetchMarketingAGIRun(runId: string): Promise<import("../types/api").MarketingAGIRun> {
  return request(`/api/marketing-agi/runs/${runId}`);
}

export function fetchMarketingAGIEvents(
  runId: string,
  afterSeq = 0,
): Promise<import("../types/api").MarketingAGIEventsResponse> {
  return request(`/api/marketing-agi/runs/${runId}/events?after_seq=${afterSeq}`);
}

export function cancelMarketingAGIRun(runId: string): Promise<import("../types/api").MarketingAGIRun> {
  return request(`/api/marketing-agi/runs/${runId}/cancel`, { method: "POST" });
}

export function fetchMarketingAGICampaigns(): Promise<import("../types/api").MarketingAGICampaignListResponse> {
  return request("/api/marketing-agi/campaigns");
}

export function fetchMarketingAGILearnings(): Promise<import("../types/api").MarketingAGILearningListResponse> {
  return request("/api/marketing-agi/learnings");
}

export function fetchMarketingAGIHandoffs(): Promise<import("../types/api").MarketingAGIHandoffListResponse> {
  return request("/api/marketing-agi/handoffs");
}

export function fetchMarketingAGITools(): Promise<import("../types/api").MarketingAGIToolCatalogResponse> {
  return request("/api/marketing-agi/tools");
}

/* -- Marketing Agent integration hub (per-workspace provider connections) -- */

export function fetchMarketingIntegrations(): Promise<{ integrations: import("../types/api").MarketingIntegrationConnection[] }> {
  return request("/api/marketing-agi/integrations");
}

export function fetchMarketingIntegration(provider: string): Promise<import("../types/api").MarketingIntegrationConnection> {
  return request(`/api/marketing-agi/integrations/${provider}`);
}

export function connectMarketingIntegration(
  provider: string,
  body: Record<string, string | undefined>,
): Promise<import("../types/api").MarketingIntegrationConnection> {
  return request(`/api/marketing-agi/integrations/${provider}/connect`, {
    method: "POST",
    body,
  });
}

export function testMarketingIntegration(
  provider: string,
): Promise<import("../types/api").MarketingIntegrationTestResult> {
  return request(`/api/marketing-agi/integrations/${provider}/test`, {
    method: "POST",
  });
}

export function disconnectMarketingIntegration(
  provider: string,
): Promise<import("../types/api").MarketingIntegrationConnection> {
  return request(`/api/marketing-agi/integrations/${provider}/disconnect`, {
    method: "POST",
  });
}

export function startMarketingOAuth(
  provider: string,
  accountId?: string,
): Promise<{ provider: string; authorization_url: string; state_expires_in_seconds: number }> {
  const qs = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  return request(`/api/marketing-agi/integrations/${provider}/oauth/start${qs}`);
}

export function fetchMarketingIntegrationAudit(): Promise<{ audit_events: import("../types/api").MarketingIntegrationAuditEvent[] }> {
  return request("/api/marketing-agi/integrations/audit?limit=50");
}

/* -- Designer Agent workspace ---------------------------------------------
 *
 * Thin wrappers over the private `request<T>()` above, so they inherit its
 * exact auth header, base URL, 401 token-drop and error normalisation. No
 * second fetch implementation is introduced here.
 */

/** Shared query-string builder; keeps the designer calls declarative. */
function qs(params: Record<string, string | number | boolean | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

export function fetchDesignerStatus(
  filters: { status?: string } = {},
): Promise<import("../types/api").DesignerStatus> {
  return request(`/api/designer/status${qs(filters)}`);
}

export function fetchDesignerProjects(
  filters: {
    status?: string;
    project_type?: string;
    analysis_cycle_id?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<import("../types/api").DesignProjectList> {
  return request(`/api/designer/projects${qs(filters)}`);
}

export function createDesignerProject(body: {
  objective: string;
  title?: string;
  project_type?: string;
  analysis_cycle_id?: string;
}): Promise<import("../types/api").DesignProject> {
  return request("/api/designer/projects", { method: "POST", body });
}

export function fetchDesignerProject(
  projectId: string,
): Promise<import("../types/api").DesignProject> {
  return request(`/api/designer/projects/${encodeURIComponent(projectId)}`);
}

export function updateDesignerProject(
  projectId: string,
  body: { title?: string; objective?: string; status?: string },
): Promise<import("../types/api").DesignProject> {
  return request(`/api/designer/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body,
  });
}

/** Full version history for a project; earlier briefs are retained. */
export function fetchDesignerProjectBriefs(
  projectId: string,
): Promise<import("../types/api").CreativeBriefList> {
  return request(`/api/designer/projects/${encodeURIComponent(projectId)}/briefs`);
}

export function fetchDesignerBriefs(
  filters: {
    project_id?: string;
    review_status?: string;
    analysis_cycle_id?: string;
    current_only?: boolean;
    limit?: number;
  } = {},
): Promise<import("../types/api").CreativeBriefList> {
  return request(`/api/designer/briefs${qs(filters)}`);
}

export function fetchDesignerBrief(
  briefId: string,
): Promise<import("../types/api").CreativeBrief> {
  return request(`/api/designer/briefs/${encodeURIComponent(briefId)}`);
}

/**
 * Record a HUMAN review decision. Requires the approver role server-side �
 * this is the only path that moves a brief out of `pending_review`.
 */
export function reviewDesignerBrief(
  briefId: string,
  body: {
    decision: "approved" | "changes_requested" | "rejected";
    notes?: string;
  },
): Promise<import("../types/api").CreativeBrief> {
  return request(`/api/designer/briefs/${encodeURIComponent(briefId)}/review`, {
    method: "POST",
    body,
  });
}

export function fetchDesignerAssets(
  filters: { project_id?: string; kind?: string; limit?: number } = {},
): Promise<import("../types/api").DesignAssetList> {
  return request(`/api/designer/assets${qs(filters)}`);
}

export function fetchDesignerAssetVersions(
  assetId: string,
): Promise<import("../types/api").DesignAssetVersionList> {
  return request(`/api/designer/assets/${encodeURIComponent(assetId)}/versions`);
}

/** Append a NEW immutable revision. Earlier versions are never rewritten. */
export function reviseDesignerAsset(
  assetId: string,
  body: { content: Record<string, unknown>; change_summary: string; rationale?: string },
): Promise<import("../types/api").DesignAssetVersion> {
  return request(`/api/designer/assets/${encodeURIComponent(assetId)}/revisions`, {
    method: "POST",
    body,
  });
}

export function fetchDesignerActivity(
  limit = 20,
): Promise<import("../types/api").DesignerActivityList> {
  return request(`/api/designer/activity${qs({ limit })}`);
}

/**
 * Real image-generation availability. Returns `unavailable` with a reason when
 * no provider is configured � never a fabricated URL.
 */
export function fetchDesignerImageGeneration(): Promise<import("../types/api").DesignerImageGeneration> {
  return request("/api/designer/image-generation");
}

/**
 * Generate one real image for a design asset and store it durably.
 *
 * Resolves with the honest outcome: `completed` only when a validated image
 * is stored, otherwise `unavailable`/`failed` with a stated reason. Never
 * fabricates an asset reference.
 */
export function generateDesignerImage(
  assetId: string | null,
  body: { prompt?: string; steps?: number } = {},
): Promise<import("../types/api").DesignerImageGeneration> {
  if (assetId) {
    return request(
      `/api/designer/assets/${encodeURIComponent(assetId)}/image-generation`,
      { method: "POST", body },
    );
  }
  return request("/api/designer/image-generation", { method: "POST", body });
}

/** Metadata only — the bytes are never included in a listing. */
export function fetchRenderedAssets(
  filters: { asset_id?: string; limit?: number } = {},
): Promise<import("../types/api").RenderedAssetList> {
  const parts = Object.entries(filters)
    .filter(([, v]) => v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return request(
    `/api/designer/rendered-assets${parts.length ? `?${parts.join("&")}` : ""}`,
  );
}

/**
 * URL for the authenticated image bytes.
 *
 * NOTE: this path is for reference and for server-side/automated callers only.
 * A browser `<img src>` cannot send the `Authorization` header this app
 * authenticates with, so the page must use `fetchRenderedAssetBlob()` instead —
 * using this in an `<img>` yields a broken image.
 */
export function renderedAssetContentUrl(renderedId: string): string {
  return `/api/designer/rendered-assets/${encodeURIComponent(renderedId)}/content`;
}

/**
 * Fetch one stored image as a Blob, carrying the bearer token.
 *
 * This is how the dashboard displays stored images: auth travels in a header,
 * so the bytes are fetched explicitly and shown via a temporary object URL.
 * Nothing is ever placed at a public, guessable URL.
 */
export function fetchRenderedAssetBlob(
  renderedId: string,
  signal?: AbortSignal,
): Promise<Blob> {
  return requestBlob(renderedAssetContentUrl(renderedId), signal);
}

export function runDesignerUxAudit(body: {
  objective: string;
  project_id?: string;
  window_days?: number;
}): Promise<import("../types/api").DesignerUxAuditResult> {
  return request("/api/designer/ux-audit", { method: "POST", body });
}

/**
 * Hand a stored brief to another workflow. This records a structured handoff
 * and never approves or executes anything; an optional proposed action still
 * faces the platform's normal approval + EXECUTION_ENABLED gate.
 */
export function createDesignerHandoff(body: {
  target: "marketing_agent" | "product_agent" | "software_agent" | "manager_agent";
  brief_id: string;
  note?: string;
  proposed_action_type?: "generate_opportunity";
}): Promise<import("../types/api").DesignerHandoff> {
  return request("/api/designer/handoffs", { method: "POST", body });
}
