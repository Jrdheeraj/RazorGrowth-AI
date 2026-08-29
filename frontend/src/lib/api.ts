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
} from "../types/api";

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
        : d && typeof d === "object" && "error" in (d as Record<string, unknown>)
          ? String((d as Record<string, unknown>).error)
          : `API error ${res.status}`;
    throw new ApiError(res.status, message);
  }

  return (await res.json()) as T;
}

/* ── Auth ─────────────────────────────────────────────────────────────── */

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: { email, password },
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

export function fetchRankedOpportunities(): Promise<RankedOpportunitiesResponse> {
  return request<RankedOpportunitiesResponse>("/api/opportunities/ranked");
}

/* ── Agents ───────────────────────────────────────────────────────────── */

export function fetchAgentsMeta(): Promise<AgentsListResponse> {
  return request<AgentsListResponse>("/api/agents");
}

export function fetchAgentRuns(limit = 25): Promise<AgentRunsResponse> {
  return request<AgentRunsResponse>(`/api/agents/runs?limit=${limit}`);
}

export function runAgents(
  body: AgentRunRequest,
): Promise<OrchestratorRunResponse> {
  return request<OrchestratorRunResponse>("/api/agents/run", {
    method: "POST",
    body,
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
