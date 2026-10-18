/**
 * Command-centre status mapping for the Product Agent and the Marketing Agent.
 *
 * Extracted from AgentsPage so the mapping can be unit-tested without a DOM or
 * a GPU. It is PRESENTATION ONLY: it turns a persisted backend status into the
 * chip and the bubble text the pixel-art office renders. It never invents a
 * state, never invents a reason, and never fabricates a completion.
 *
 * Two defects this fixes:
 *   - the Product Agent fell through to a FAILED branch for
 *     approved_awaiting_execution / executing / completed, so an agent that
 *     had been approved and executed was shown as FAILED in the office;
 *   - the Marketing Agent's catch-all reported BOTH `blocked` and `failed` as
 *     "BLOCKED" and substituted the run objective whenever the error list was
 *     empty, producing "Blocked \u2014 Comprehensive commerce analysis and growth
 *     optimization": a task objective presented as a failure reason.
 */
import type { AgentLiveStatus } from "./agentsShared";
import type { MarketingAGICampaign, MarketingAGIRun, ProductAgentRun } from "@/types/api";

function countOrZero(v: number | null | undefined): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

export const MAGI_PHASE_LABELS: Record<string, string> = {
  load_context: "LOADING CONTEXT",
  observe: "OBSERVING",
  investigate: "RESEARCHING",
  plan: "PLANNING",
  create: "CREATING",
  verify: "VERIFYING",
  prepare: "PREPARING",
  awaiting_approval: "AWAITING APPROVAL",
  complete: "COMPLETE",
};

export interface MagiSlot {
  live: AgentLiveStatus;
  chip: string;
  tone: "neutral" | "ok" | "accent";
  anim: "pulse" | "none";
  monitor: string;
  sub: string;
  progress: number | null;
  tools: string[];
}

/* ── New Product Agent slot — real state from /api/product-agi ───────────
   Mirrors the Marketing Agent slot exactly: the "ProductAgent" roster key
   renders the NEW autonomous Product Agent (same key/position, new data
   source). It is dispatched by the SAME shared analysis cycle, so the
   statuses below are the backend's own values — queued, running,
   waiting_approval, completed_no_actions, blocked or failed. Nothing here
   simulates progress or invents a completion state. */

export const PRODUCT_AGENT_STAGE_LABELS: Record<string, string> = {
  understand_catalog: "READING CATALOG",
  analyze_performance: "ANALYSING PERFORMANCE",
  find_opportunities: "FINDING OPPORTUNITIES",
  research_analyze: "RESEARCHING",
  prepare_recommendation: "PREPARING",
  safety_check: "SAFETY CHECK",
  waiting_approval: "AWAITING APPROVAL",
  execute_measure: "EXECUTING",
  learn: "LEARNING",
};

/** Product Agent statuses that mean the loop has not finished yet. */
const PRODUCT_AGENT_ACTIVE_STATUSES = new Set(["queued", "running"]);

export function isProductAgentActive(status: string | null | undefined): boolean {
  return status != null && PRODUCT_AGENT_ACTIVE_STATUSES.has(status);
}

export interface ProductSlot {
  live: AgentLiveStatus;
  chip: string;
  tone: "neutral" | "ok" | "accent";
  anim: "pulse" | "none";
  monitor: string;
  sub: string;
  progress: number | null;
}

export function productAgentOfficeSlot(
  productRun: ProductAgentRun | null,
  isWorking: boolean = true,
): ProductSlot {
  if (!productRun || (!isWorking && (productRun.status === "running" || productRun.status === "queued" || productRun.status === "executing"))) {
    return {
      live: "IDLE",
      chip: "IDLE",
      tone: "neutral",
      anim: "none",
      monitor: "Ready — autonomous product growth employee",
      sub: "Starts automatically with AI Team Start Analysis",
      progress: null,
    };
  }
  const m = productRun.metrics ?? {};
  const products = m.product_count ?? productRun.products_analyzed;
  const findings = m.finding_count ?? 0;
  const recs = m.recommendation_count ?? productRun.recommendations_created;
  const sub =
    `${countOrZero(products)} products analysed · ${countOrZero(findings)} finding(s) · ` +
    `${countOrZero(recs)} recommendation(s)`;
  const engine = productRun.llm_provider ?? "deterministic";

  if (productRun.status === "queued") {
    return {
      live: "WAITING",
      chip: "QUEUED",
      tone: "neutral",
      anim: "none",
      monitor: "Queued — waiting to start within the shared analysis cycle",
      sub,
      progress: null,
    };
  }
  if (productRun.status === "running") {
    const stage = PRODUCT_AGENT_STAGE_LABELS[productRun.stage] ?? "WORKING";
    return {
      live: "WORKING",
      chip: stage,
      tone: "accent",
      anim: "pulse",
      monitor: `${stage} — ${productRun.objective}`.slice(0, 90),
      sub: `${engine} reasoning + tools · ${sub}`,
      progress: null,
    };
  }
  if (productRun.status === "waiting_approval") {
    return {
      live: "NEEDS_APPROVAL",
      chip: "WAITING FOR APPROVAL",
      tone: "accent",
      anim: "none",
      monitor: `${countOrZero(recs)} recommendation(s) prepared — every action needs your approval`.slice(0, 90),
      sub: `Nothing executed · approval ${productRun.approval_status ?? "required"} · ${sub}`,
      progress: 100,
    };
  }
  if (productRun.status === "completed") {
    return {
      live: "COMPLETED",
      chip: "COMPLETED",
      tone: "ok",
      anim: "none",
      monitor: (productRun.summary ?? "Analysis complete").slice(0, 90),
      sub: `${engine} reasoning + tools · ${sub}`,
      progress: 100,
    };
  }
  if (productRun.status === "completed_no_actions") {
    return {
      live: "COMPLETED",
      chip: "COMPLETED",
      tone: "ok",
      anim: "none",
      monitor: (productRun.summary ?? "Analysis complete — nothing needs approval").slice(0, 90),
      sub,
      progress: 100,
    };
  }
  if (productRun.status === "completed_with_failures") {
    // A real partial outcome: some actions ran, some did not. Reported as
    // itself — never collapsed into plain "completed".
    const failed = countOrZero(m.executed_count) < countOrZero(m.action_count);
    return {
      live: "ERROR",
      chip: "PARTIAL FAILURE",
      tone: "neutral",
      anim: "none",
      monitor: `Partial failure — ${countOrZero(m.executed_count)} of ${countOrZero(m.action_count)} action(s) executed`,
      sub: `${countOrZero(m.executed_count)} executed · ${sub}`,
      progress: null,
    };
  }
  if (productRun.status === "approved_awaiting_execution") {
    // Approvals are resolved; execution has NOT started. This used to fall
    // through to the failure branch, so an approved Product Agent was shown
    // as FAILED in the command centre.
    return {
      live: "IDLE",
      chip: "AWAITING EXECUTION",
      tone: "accent",
      anim: "none",
      monitor: `Approved — ready to execute · approval ${productRun.approval_status ?? "approved"}`,
      sub: `Nothing executing yet · ${sub}`,
      progress: null,
    };
  }
  if (productRun.status === "executing") {
    return {
      live: "WORKING",
      chip: "EXECUTING",
      tone: "accent",
      anim: "pulse",
      monitor: `Executing — ${countOrZero(m.executed_count)} of ${countOrZero(m.action_count)} action(s) done`,
      sub: `Execution in progress · ${sub}`,
      progress: null,
    };
  }
  if (productRun.status === "blocked") {
    return {
      live: "BLOCKED",
      chip: "BLOCKED BY SAFETY",
      tone: "neutral",
      anim: "none",
      // The backend's own reason, not a hardcoded excuse.
      monitor: `Blocked — ${(productRun.errors?.[0] ?? "safety verification rejected the recommendations").slice(0, 60)}`,
      sub: `Needs a safety decision · ${sub}`,
      progress: null,
    };
  }
  if (productRun.status === "cancelled") {
    return {
      live: "IDLE",
      chip: "CANCELLED",
      tone: "neutral",
      anim: "none",
      monitor: "Cancelled — this run was stopped before completing",
      sub,
      progress: null,
    };
  }
  // failed — reported honestly, never as a completed analysis.
  return {
    live: "ERROR",
    chip: "FAILED",
    tone: "neutral",
    anim: "none",
    monitor: `Failed — ${productRun.errors?.[0] ?? "the run did not complete"}`.slice(0, 90),
    sub,
    progress: null,
  };
}

export function marketingAgentOfficeSlot(
  magiRun: MarketingAGIRun | null,
  magiCampaigns: MarketingAGICampaign[],
  isWorking: boolean = true,
): MagiSlot {
  const tools: string[] = magiRun
    ? Array.from(new Set((magiRun.state?.tool_calls ?? []).map((c) => c.tool)))
    : [];
  const latestCampaign = magiCampaigns[0] ?? null;
  if (!magiRun || (!isWorking && (magiRun.status === "running" || magiRun.status === "queued"))) {
    return {
      live: "IDLE",
      chip: "IDLE",
      tone: "neutral",
      anim: "none",
      monitor: "Ready — autonomous marketing employee",
      sub: "Researches data · builds campaigns · verifies · learns",
      progress: null,
      tools: [],
    };
  }
  const st = magiRun.state;
  const evidenceCount = st?.evidence.length ?? 0;
  const toolCount = st?.tool_calls.length ?? 0;
  const llmCount = st?.llm_decisions.length ?? 0;
  const engine = magiRun.llm_provider ?? "Cloudflare Workers AI";
  const sub = `${evidenceCount} evidence · ${toolCount} tools used · ${llmCount} LLM decisions`;
  if (magiRun.status === "queued" || magiRun.status === "cancelled") {
    return { live: "IDLE", chip: "IDLE", tone: "neutral", anim: "none", monitor: "Ready — autonomous marketing employee", sub, progress: null, tools };
  }
  if (magiRun.status === "running") {
    const phase = MAGI_PHASE_LABELS[magiRun.phase] ?? "WORKING";
    return {
      live: "WORKING",
      chip: phase,
      tone: "accent",
      anim: "pulse",
      monitor: `${phase} — ${magiRun.objective}`.slice(0, 90),
      sub: `${engine} reasoning + tools · ${sub}`,
      progress: null,
      tools,
    };
  }
  if (magiRun.status === "waiting_approval") {
    return {
      live: "NEEDS_APPROVAL",
      chip: "READY FOR APPROVAL",
      tone: "accent",
      anim: "none",
      monitor: `Ready for approval — ${latestCampaign?.name ?? magiRun.objective}`.slice(0, 90),
      sub: `Marketing work prepared / approval required · ${sub}`,
      progress: 100,
      tools,
    };
  }
  if (magiRun.status === "completed") {
    const head = st?.observations[0] ?? magiRun.objective;
    return {
      live: "COMPLETED",
      chip: "COMPLETED",
      tone: "ok",
      anim: "none",
      monitor: head.slice(0, 90),
      sub: `Marketing work prepared · ${sub}`,
      progress: 100,
      tools,
    };
  }
  /* Remaining statuses are `blocked` and `failed` — two DIFFERENT outcomes.
   *
   * This used to be a single catch-all that labelled both "BLOCKED" and
   * substituted the run's objective whenever the error list was empty, which
   * is how the office ended up showing
   *   "Blocked — Comprehensive commerce analysis and growth optimization"
   * i.e. a task objective presented as a failure reason, for a run that was
   * in fact FAILED (or blocked, for a reason the backend had already
   * recorded). It also hardcoded "LLM unavailable" without checking whether
   * the LLM was actually degraded.
   *
   * Display only — the Marketing Agent's own pipeline, prompts and outputs
   * are untouched. */
  const degraded = st?.reasoning_status === "degraded" || st?.llm_degraded === true;
  const reason = st?.errors[0] ?? null;
  const isBlocked = magiRun.status === "blocked";

  if (isBlocked) {
    return {
      live: "BLOCKED",
      chip: "BLOCKED",
      tone: "neutral",
      anim: "none",
      monitor: `Blocked — ${reason ?? "the safety policy rejected this run"}`.slice(0, 90),
      sub: `Needs a decision before it can continue · ${sub}`,
      progress: null,
      tools,
    };
  }
  if (magiRun.status === "failed") {
    return {
      live: "ERROR",
      chip: "FAILED",
      tone: "neutral",
      anim: "none",
      monitor: `Failed — ${reason ?? "the run did not complete"}`.slice(0, 90),
      sub: `${degraded ? "LLM unavailable" : "run did not complete"} · ${sub}`,
      progress: null,
      tools,
    };
  }
  // An unrecognised status is reported as unknown rather than mislabelled.
  return {
    live: "IDLE",
    chip: "UNKNOWN STATE",
    tone: "neutral",
    anim: "none",
    monitor: `Unrecognised run state "${String(magiRun.status)}"`.slice(0, 90),
    sub,
    progress: null,
    tools,
  };
}

