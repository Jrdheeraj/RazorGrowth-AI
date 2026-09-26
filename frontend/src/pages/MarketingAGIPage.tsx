/**
 * /marketing-agent — Marketing Agent workstation.
 *
 * The console for the autonomous marketing employee. Every value is
 * driven by REAL agent execution state polled from the backend:
 * status, objective, live workstream (real events), current reasoning,
 * research evidence, tool activity, the six-category marketing stack
 * (real integration status), campaign workspace, verification, prepared
 * action, and learning history. No decorative fake animations, no
 * simulated progress, no invented integration status.
 *
 * Visual system: the page lives inside the same illustrated RazorGrowth
 * world as the homepage (GlobalEnvironment — warm peach sky, clouds,
 * city, merchant street). Dashboard sections are browser-window panels
 * (WindowPanel) sitting on top of that world with the world visible
 * between them. Copy is merchant-friendly; technical detail stays
 * inside a collapsed "Technical details" section.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchMarketingAGIStatus,
  fetchMarketingAGIRuns,
  fetchMarketingAGIRun,
  fetchMarketingAGIEvents,
  cancelMarketingAGIRun,
  fetchMarketingAGICampaigns,
  fetchMarketingAGILearnings,
  fetchMarketingAGIHandoffs,
  fetchMarketingAGITools,
  connectMarketingIntegration,
  testMarketingIntegration,
  disconnectMarketingIntegration,
  startMarketingOAuth,
  fetchMarketingIntegrationAudit,
  fetchGrowthRadar,
  fetchAnalyticsOverview,
} from "../lib/api";
import {
  activityRowState,
  canonicalLifecycleStage,
  isApprovalGranted,
  isLifecycleTerminal,
} from "../lib/activityStatus";
import {
  googleCustomerSelector,
  oauthResultMessage,
  parseIntegrationCallback,
} from "../lib/integrationOauth";
import type {
  MarketingAGIStatus,
  MarketingAGIRun,
  MarketingAGIRunEvent,
  MarketingAGICampaign,
  MarketingAGILearning,
  MarketingAGIHandoff,
  MarketingStackEntry,
  GrowthRadarResponse,
  AnalyticsOverviewResponse,
} from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import { StatusChip } from "../components/StatusIndicator";
import { GlobalEnvironment } from "../features/public/Environment/GlobalEnvironment";
import "./MarketingAGIPage.css";

/* ── Status helpers ─────────────────────────────────────────────────── */

const ACTIVE_STATUSES = new Set(["queued", "running"]);
const TERMINAL_STATUSES = new Set([
  "completed",
  "waiting_approval",
  "blocked",
  "failed",
  "cancelled",
]);
/* Canonical action statuses that still represent a live proposal — the
 * dashboard must keep polling while any of these is in force, even when the
 * run itself is parked at waiting_approval / completed. */
const OPEN_ACTION_STATUSES = new Set(["requested", "approved", "executing"]);

/** Whether a freshly loaded run warrants polling (active work, or a parked
 * run whose canonical action is still open). */
function shouldPollRun(r: MarketingAGIRun): boolean {
  if (ACTIVE_STATUSES.has(r.status)) return true;
  const prep = r.state?.prepared_action?.status ?? null;
  if (prep && OPEN_ACTION_STATUSES.has(prep)) return true;
  // Parked with no snapshot yet: only waiting_approval runs need watching.
  if (!prep && r.status === "waiting_approval") return true;
  return false;
}

/** Structural equality for run headers we care about — keeps the activeRun
 * object identity stable across identical polls so the interval effect does
 * not tear down/recreate every tick (RC11). */
function sameRunHeader(a: MarketingAGIRun | null, b: MarketingAGIRun): boolean {
  if (!a || a.id !== b.id) return false;
  const pa = a.state?.prepared_action ?? null;
  const pb = b.state?.prepared_action ?? null;
  return (
    a.status === b.status &&
    a.phase === b.phase &&
    a.iterations === b.iterations &&
    a.tool_call_count === b.tool_call_count &&
    (pa?.status ?? null) === (pb?.status ?? null) &&
    (pa?.approval_state ?? null) === (pb?.approval_state ?? null) &&
    (a.state?.reasoning_status ?? null) === (b.state?.reasoning_status ?? null) &&
    (a.state?.current_decision ?? null) === (b.state?.current_decision ?? null) &&
    (a.state?.tool_calls?.length ?? 0) === (b.state?.tool_calls?.length ?? 0) &&
    (a.state?.observations?.length ?? 0) === (b.state?.observations?.length ?? 0) &&
    (a.state?.errors?.length ?? 0) === (b.state?.errors?.length ?? 0)
  );
}

/** The campaign that belongs to this run (never an unrelated newer draft).
 * Falls back to the campaign linked to the run's canonical action. */
function campaignForRun(
  run: MarketingAGIRun | null,
  campaigns: MarketingAGICampaign[],
): MarketingAGICampaign | null {
  if (!run) return campaigns[0] ?? null;
  const own = campaigns.find((c) => c.run_id === run.id);
  if (own) return own;
  const aid = run.state?.prepared_action?.action_id;
  if (aid) {
    const viaAction = campaigns.find((c) => c.action_id === aid);
    if (viaAction) return viaAction;
  }
  return null;
}

/* Real agent status derived from backend run state (+ campaign execution).
 * Every value traces to run.status / run.phase / campaign.lifecycle, with
 * the canonical agent_actions status (prepared_action.status, overlaid live
 * by the backend) breaking ties — so an approval/execution performed from
 * /actions is reflected here instead of freezing at "ready for approval". */
function agentStatus(
  run: MarketingAGIRun | null,
  campaigns: MarketingAGICampaign[],
  prepStatus: string | null,
): { key: string; label: string; live: boolean } {
  if (!run) return { key: "idle", label: "IDLE", live: false };
  if (run.status === "queued" || run.status === "cancelled")
    return { key: "idle", label: "IDLE", live: false };
  if (run.status === "running") {
    switch (run.phase) {
      case "load_context":
        return { key: "investigating", label: "INVESTIGATING", live: true };
      case "observe":
        return { key: "analyzing", label: "ANALYZING", live: true };
      case "investigate":
        return { key: "researching", label: "RESEARCHING", live: true };
      case "plan":
        return { key: "planning", label: "PLANNING", live: true };
      case "create":
        return { key: "using_tool", label: "USING TOOL", live: true };
      case "verify":
        return { key: "verifying", label: "VERIFYING", live: true };
      case "prepare":
        return { key: "waiting", label: "WAITING", live: true };
      case "awaiting_approval":
        return { key: "ready", label: "READY FOR APPROVAL", live: false };
      case "complete":
        return { key: "completed", label: "COMPLETED", live: false };
      default:
        return { key: "working", label: "WORKING", live: true };
    }
  }
  if (run.status === "waiting_approval") {
    // Canonical action state wins over the parked run status.
    if (prepStatus === "approved")
      return { key: "approved", label: "APPROVED", live: false };
    if (prepStatus === "executing")
      return { key: "executing", label: "EXECUTING", live: true };
    if (prepStatus === "completed")
      return { key: "completed", label: "COMPLETED", live: false };
    if (prepStatus === "failed" || prepStatus === "rejected")
      return { key: "blocked", label: "BLOCKED", live: false };
    return { key: "ready", label: "READY FOR APPROVAL", live: false };
  }
  if (run.status === "completed") {
    if (prepStatus === "failed" || prepStatus === "rejected")
      return { key: "blocked", label: "BLOCKED", live: false };
    // Only THIS run's campaign decides executing — never an unrelated newer draft.
    const own = campaignForRun(run, campaigns);
    if (own && (own.lifecycle === "executing" || own.lifecycle === "approved"))
      return { key: "executing", label: "EXECUTING", live: true };
    return { key: "completed", label: "COMPLETED", live: false };
  }
  return { key: "blocked", label: "BLOCKED", live: false };
}

function statusChipTone(key: string): "neutral" | "ok" | "accent" {
  if (key === "ready") return "accent";
  if (key === "completed" || key === "approved") return "ok";
  return "neutral";
}

/* Merge event batches by primary key, ordered by seq. All events in one
 * timeline belong to the same run, so seq is unique — a stale poll
 * response that lands after a full refresh can never duplicate rows or
 * reorder the timeline (chronological integrity by construction). */
function mergeRunEvents(
  prev: MarketingAGIRunEvent[],
  incoming: MarketingAGIRunEvent[],
): MarketingAGIRunEvent[] {
  const byId = new Map<string, MarketingAGIRunEvent>();
  for (const e of prev) byId.set(e.id, e);
  for (const e of incoming) byId.set(e.id, e);
  return [...byId.values()].sort(
    (a, b) => a.seq - b.seq || a.id.localeCompare(b.id),
  );
}

/* User-safe reasoning status for the technical-details disclosure. */
function reasoningStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case "reasoning":
      return "Reasoning";
    case "selecting_tools":
      return "Selecting tools";
    case "investigating":
      return "Investigating";
    case "planning":
      return "Planning";
    case "waiting_for_approval":
      return "Waiting for approval";
    case "degraded":
      return "Degraded";
    case "done":
      return "Done";
    default:
      return "Idle";
  }
}

/* The agent's real 8-step workflow, mapped from backend phase / status /
 * campaign lifecycle — never animated, never faked. */
const EIGHT_STEPS = [
  { top: "Understand", bottom: "business" },
  { top: "Find", bottom: "opportunities" },
  { top: "Research", bottom: "& analyze" },
  { top: "Prepare", bottom: "campaign" },
  { top: "Safety", bottom: "check" },
  { top: "Waiting for", bottom: "approval" },
  { top: "Execute", bottom: "" },
  { top: "Measure", bottom: "& learn" },
] as const;

function eightStepIndex(
  run: MarketingAGIRun | null,
  campaigns: MarketingAGICampaign[],
  learnings: MarketingAGILearning[],
): number {
  if (!run) return -1;
  if (learnings.length > 0) return 7;
  const lifecycle = campaignForRun(run, campaigns)?.lifecycle ?? null;
  if (lifecycle === "approved" || lifecycle === "executing") return 6;
  if (lifecycle === "rejected") return 5;
  if (lifecycle === "failed") return 6;
  if (lifecycle === "completed" || lifecycle === "measuring" || lifecycle === "learned")
    return 7;
  if (run.status === "waiting_approval") return 5;
  if (run.status === "completed")
    return run.state?.prepared_action ? 5 : 4;
  switch (run.phase) {
    case "load_context":
      return 0;
    case "observe":
      return 1;
    case "investigate":
      return (run.state?.retrieval_log?.length ?? 0) > 0 ? 2 : 1;
    case "plan":
      return (run.state?.hypotheses?.length ?? 0) > 0 ? 3 : 2;
    case "create":
      return 3;
    case "verify":
      return 4;
    case "prepare":
    case "awaiting_approval":
      return 5;
    case "complete":
      return 6;
    default:
      return (run.state?.tool_calls?.length ?? 0) > 0 ? 2 : 0;
  }
}

const LIFECYCLE_STEPS = [
  "idea",
  "research",
  "draft",
  "verify",
  "ready_for_approval",
  "approved",
  "executing",
  "completed",
  "measuring",
  "learned",
] as const;

function lifecycleIndex(lifecycle: string | null | undefined): number {
  if (!lifecycle) return 0;
  const i = (LIFECYCLE_STEPS as readonly string[]).indexOf(lifecycle);
  return i >= 0 ? i : 0;
}

const INTEGRATION_LABELS: Record<string, string> = {
  connected: "CONNECTED",
  draft_only: "DRAFT ONLY",
  requires_integration: "REQUIRES INTEGRATION",
  not_connected: "NOT CONNECTED",
  error: "CONNECTION ERROR",
  disconnected: "DISCONNECTED",
};

/* Provider display names for the live stack (backend truth: the `provider`
 * field on each stack entry). Internal tools are labelled as such so they
 * are never mistaken for external integrations. */
function providerDisplay(provider: string | null | undefined): string {
  switch (provider) {
    case "resend":
      return "Resend";
    case "google_ads":
      return "Google Ads";
    case "meta_ads":
      return "Meta Ads";
    case "instagram":
      return "Instagram";
    case "internal":
      return "Internal";
    default:
      return "—";
  }
}

/* How to connect each external provider (shown when not connected). */
const STACK_CONNECT_HINT: Record<string, string> = {
  email: "Connect with a Resend API key + verified sender below. Sending still requires your approval per campaign.",
  google_ads: "Connect with Google OAuth below (needs a Google Ads account accessible to the Google Cloud project's API access level). Reads go live; writes stay approval-gated and create PAUSED campaigns only.",
  meta_ads: "Connect with Meta OAuth or a system-user token below. Reads go live; writes stay approval-gated and create PAUSED campaigns only.",
  social: "Connect Instagram with Meta OAuth below (a Facebook Page with a linked Instagram business account is required). Publishing stays approval-gated.",
};

/* Fallback stack removed on purpose: the marketing stack is backend-owned
 * (/api/marketing-agi/status → marketing_stack). If the field is absent the
 * UI shows an honest empty/unavailable state — never a hardcoded fake stack. */

/* Where each "View work" button goes — all real destinations. */
const STACK_DESTINATIONS: Record<string, { route: string | null; label: string; anchor?: string }> = {
  email: { route: "/actions", label: "Review in Actions →" },
  google_ads: { route: null, label: "View campaign prep →", anchor: "campaign" },
  meta_ads: { route: null, label: "View campaign prep →", anchor: "campaign" },
  crm: { route: "/agents", label: "Open AI Team →" },
  analytics: { route: "/growth-radar", label: "Open Growth Radar →" },
  social: { route: null, label: "View content prep →", anchor: "campaign" },
};

/* Marketing-channels presentation order + merchant copy. Status itself
 * always comes from the backend stack entry. */
const CHANNEL_ORDER = ["email", "google_ads", "meta_ads", "social", "crm", "analytics"];
const CHANNEL_SHORT: Record<string, string> = {
  email: "EMAIL",
  google_ads: "GOOGLE ADS",
  meta_ads: "META ADS",
  social: "INSTAGRAM",
  crm: "CRM",
  analytics: "ANALYTICS",
};
const CHANNEL_BLURB: Record<string, { on: string; off: string }> = {
  email: { on: "Ready to send campaigns", off: "Connect to send campaigns" },
  google_ads: { on: "Ready to run ads", off: "Connect to unlock ads" },
  meta_ads: { on: "Ready for paid social", off: "Connect for paid social" },
  social: { on: "Ready to publish", off: "Connect to publish content" },
  crm: { on: "Customer data available", off: "Customer data unavailable" },
  analytics: { on: "Business data available", off: "Business data unavailable" },
};

function rupees(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function fmtDelta(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const r = Math.round(v);
  if (r > 0) return `↑ ${r}%`;
  if (r < 0) return `↓ ${Math.abs(r)}%`;
  return "→ 0%";
}

function paramsSummary(params: Record<string, unknown>): string {
  const keys = Object.keys(params ?? {});
  if (keys.length === 0) return "no input";
  const bits: string[] = [];
  for (const k of keys.slice(0, 4)) {
    const v = params[k];
    if (Array.isArray(v)) bits.push(`${k}: ${v.length} items`);
    else if (v !== null && typeof v === "object") bits.push(`${k}: {...}`);
    else bits.push(`${k}: ${String(v).slice(0, 28)}`);
  }
  return bits.join(" · ");
}

/* Merchant-readable relative time for activity + refresh metadata. */
function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "Just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

function prettifyTechnical(text: string | null | undefined): string {
  if (!text) return "Worked on your business";
  const clean = text
    .replace(/^\d{1,2}\s*[—–-]\s*/, "") // strip step numbering ("12 — …")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return "Worked on your business";
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

/* Convert internal execution events into merchant-readable language.
 * Only the wording changes — ordering, timing and source events are
 * untouched backend truth. Canonical lifecycle event types get exact
 * merchant wording FIRST so no generic keyword rule can mislabel them
 * (e.g. action_prepared must never read as an execution event). */
function friendlyEvent(e: MarketingAGIRunEvent): string {
  // Real cross-page lifecycle events (emitted when /actions transitions
  // the canonical action) get exact merchant wording first.
  switch (e.event_type) {
    case "action_approved":
      return "Campaign approved by you";
    case "execution_started":
      return "Campaign execution started";
    case "action_executed":
      return "Campaign executed successfully";
    case "action_failed":
      return "Campaign execution failed";
    case "action_rejected":
      return "Campaign proposal was not approved";
    case "action_reused":
      return "Linked to the open proposal";
    case "action_prepared":
      return "Preparing the campaign for your approval";
    case "awaiting_approval":
      return "Waiting for your approval";
    case "handoff_opened":
      // The backend records the handoff request but does not prove the
      // campaign was sent anywhere — never claim it was sent.
      return "Creative review requested";
    case "phase_started":
      if (e.phase === "prepare") return "Preparing the campaign for your approval";
      if (e.phase === "verify") return "Checking customers and campaign safety";
      break;
    default:
      break;
  }
  const raw = `${e.event_type} ${e.phase} ${e.message}`.toLowerCase();
  const has = (...keys: string[]) => keys.some((k) => raw.includes(k));
  if (has("waiting") && has("approv")) return "Waiting for your approval";
  if (has("approv") && has("request")) return "Prepared an approval request";
  if (has("verification_passed") || (has("verif") && has("pass")))
    return "Campaign safety check completed";
  if (has("verification_failed") || (has("verif") && has("fail")))
    return "Campaign safety review needs attention";
  if (has("failed_payment")) return "Checked failed payments";
  if (has("revenue_trend") || (has("revenue") && has("trend")))
    return "Reviewed revenue trends";
  if (has("business_overview")) return "Reviewed business performance";
  if (has("customer_activity")) return "Reviewed customer activity";
  if (has("segment") || has("find_customers") || has("customer_profile"))
    return "Checked which customers are affected";
  if (has("rag") || has("retriev")) return "Reviewed business data";
  if (has("campaign_draft") || has("create_email") || (has("draft") && has("campaign")))
    return "Prepared the campaign for your review";
  if (has("select_campaign") || has("strategy")) return "Prepared campaign strategy";
  if (has("hypothesis")) return "Formed a growth hypothesis";
  // NOTE: there is deliberately no generic "execut" → "Ran the approved
  // work" rule. execution_started / action_executed are the canonical
  // execution transitions above; anything else falls through honestly.
  if (has("measur") || (has("learn") && !has("learning"))) return "Measured results and learned";
  if (has("plan")) return "Planned the recovery campaign";
  if (has("tool")) return "Used a business tool";
  if (has("reasoning") || has("decision") || has("llm")) return "Reasoned about the best approach";
  if (has("run_started") || has("analysis_started")) return "Started working on your business";
  if (has("run_finished") || has("complete")) return "Finished the current work";
  return prettifyTechnical(e.message);
}

/* Canonical per-action work timestamp: the SAME persisted backend instant
 * the Live Activity timeline is built from — never run.started_at (the
 * loop start, which predates approval/execution by minutes) and never a
 * polling-time "now". Terminal actions show action.completed_at (the real
 * execution instant, matching the action_executed event); open actions show
 * the latest persisted action mutation (updated ⇒ approval/execution start)
 * falling back to creation (the prepare instant, matching awaiting_approval).
 * Runs without a canonical action fall back to run.completed_at/started_at.
 * Polling must NEVER change this value for a historical action. */
function canonicalWorkTimestamp(run: MarketingAGIRun): string | null {
  return (
    run.action_completed_at ??
    run.action_updated_at ??
    run.action_created_at ??
    run.completed_at ??
    run.started_at ??
    null
  );
}

/* Canonical per-campaign work state: lifecycle first (mirrored from the
 * canonical action), run status as fallback. Drives Recent Work rows and
 * the approval/preview panels so they can never contradict /actions. */
function canonicalWorkState(
  lifecycle: string | null | undefined,
  runStatus: string | null | undefined,
): { label: string; tone: "accent" | "ok" | "neutral" } {
  switch (lifecycle) {
    case "ready_for_approval":
    case "draft":
    case "verify":
      return { label: "Ready for approval", tone: "accent" };
    case "approved":
      return { label: "Approved", tone: "ok" };
    case "executing":
      return { label: "Executing", tone: "accent" };
    case "completed":
    case "measuring":
    case "learned":
      return { label: "Completed", tone: "ok" };
    case "rejected":
      return { label: "Not approved", tone: "neutral" };
    case "failed":
      return { label: "Execution failed", tone: "neutral" };
    default:
      break;
  }
  return { label: merchantRunStateLabel(runStatus ?? "idle"), tone: "neutral" };
}

/* Honest rendering of a persisted learning's real execution facts.
 * Only keys actually present in the row are shown — never invented. */
function learningFacts(
  actual: Record<string, unknown> | null | undefined,
): Array<[string, string]> {
  if (!actual || typeof actual !== "object") return [];
  const out: Array<[string, string]> = [];
  const pick = (label: string, v: unknown) => {
    if (v === null || v === undefined || v === "") return;
    out.push([label, typeof v === "object" ? JSON.stringify(v) : String(v)]);
  };
  pick("Mode", actual["mode"]);
  pick("Sent", actual["sent"]);
  pick("Customers targeted", actual["target_count"]);
  pick("Provider", actual["provider"]);
  pick("Email ID", actual["email_id"]);
  if (typeof actual["completed_at"] === "string") {
    const d = new Date(actual["completed_at"] as string);
    if (!Number.isNaN(d.getTime())) {
      out.push(["Completed", d.toLocaleString("en-IN", { hour12: false })]);
    }
  }
  pick("Error", actual["error"]);
  return out;
}

/* Merchant-readable run title: first real observation, else hypothesis,
 * else the run objective. Never invented. */
function merchantRunTitle(r: MarketingAGIRun): string {
  const obs = r.state?.observations?.[0];
  if (obs) return obs.length > 90 ? `${obs.slice(0, 90)}…` : obs;
  const hyp = r.state?.hypotheses?.[0]?.statement;
  if (hyp) return hyp.length > 90 ? `${hyp.slice(0, 90)}…` : hyp;
  return r.objective;
}

function merchantRunStateLabel(status: string): string {
  switch (status) {
    case "queued":
      return "Queued";
    case "running":
      return "Working";
    case "waiting_approval":
      return "Ready for approval";
    case "completed":
      return "Completed";
    case "blocked":
    case "failed":
      return "Needs attention";
    case "cancelled":
      return "Cancelled";
    default:
      return prettifyTechnical(status);
  }
}

/* Honest "Based on" sources derived from the tools the agent really called. */
function evidenceSources(
  toolCalls: Array<{ tool: string }>,
  hasEvidence: boolean,
): string[] {
  const src = new Set<string>();
  for (const c of toolCalls) {
    const t = c.tool.toLowerCase();
    if (t.includes("payment") || t.includes("revenue") || t.includes("order"))
      src.add("Payment activity");
    else if (t.includes("customer") || t.includes("segment"))
      src.add("Customer history");
    else if (t.includes("business") || t.includes("trend") || t.includes("overview") || t.includes("analytic"))
      src.add("Business data");
    else src.add("Business research");
  }
  if (src.size === 0 && hasEvidence) src.add("Business data");
  return [...src].slice(0, 4);
}

/* ── Marketing Agent office illustration ────────────────────────────────
 * Flat RazorGrowth illustration language: warm cream paper, thin dark
 * outlines, terracotta accents, square edges. A small storefront office
 * with the agent at work — NOT photorealistic, NOT neon, NOT 3D. */
function AgentOfficeArt() {
  return (
    <svg
      className="magi-art"
      viewBox="0 0 520 360"
      role="img"
      aria-label="Illustrated Marketing Agent office at work"
    >
      {/* ground */}
      <rect x="24" y="300" width="472" height="26" fill="#EBD9AE" stroke="#2a1810" strokeWidth="3" />
      {/* main shop block */}
      <rect x="70" y="96" width="330" height="208" fill="#FFF3DF" stroke="#2a1810" strokeWidth="3" />
      {/* sign band */}
      <rect x="70" y="96" width="330" height="40" fill="#21130e" stroke="#2a1810" strokeWidth="3" />
      <text x="235" y="122" textAnchor="middle" fontFamily="'IBM Plex Mono',monospace" fontSize="17" letterSpacing="3" fill="#F7EBD7">
        MARKETING AGENT
      </text>
      {/* awning */}
      <g stroke="#2a1810" strokeWidth="3">
        <rect x="70" y="136" width="47" height="26" fill="#D97757" />
        <rect x="117" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="164" y="136" width="47" height="26" fill="#D97757" />
        <rect x="211" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="258" y="136" width="47" height="26" fill="#D97757" />
        <rect x="305" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="352" y="136" width="48" height="26" fill="#D97757" />
      </g>
      {/* window with agent + laptop */}
      <rect x="96" y="182" width="150" height="102" fill="#F5E6CF" stroke="#2a1810" strokeWidth="3" />
      {/* robot head */}
      <rect x="128" y="202" width="52" height="44" rx="6" fill="#EBD9AE" stroke="#2a1810" strokeWidth="3" />
      <line x1="154" y1="202" x2="154" y2="192" stroke="#2a1810" strokeWidth="3" />
      <circle cx="154" cy="188" r="5" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
      <circle cx="143" cy="221" r="5" fill="#2a1810" />
      <circle cx="165" cy="221" r="5" fill="#2a1810" />
      <rect x="146" y="233" width="16" height="4" fill="#2a1810" />
      {/* laptop */}
      <rect x="192" y="230" width="40" height="28" fill="#301B12" stroke="#2a1810" strokeWidth="3" />
      <rect x="196" y="234" width="32" height="16" fill="#70B88A" />
      <rect x="186" y="258" width="52" height="6" fill="#301B12" stroke="#2a1810" strokeWidth="2.5" />
      {/* desk */}
      <line x1="96" y1="266" x2="246" y2="266" stroke="#2a1810" strokeWidth="3" />
      {/* door */}
      <rect x="266" y="182" width="108" height="122" fill="#F0BC92" stroke="#2a1810" strokeWidth="3" />
      <rect x="278" y="196" width="84" height="56" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <circle cx="356" cy="250" r="4" fill="#2a1810" />
      {/* side tree */}
      <rect x="428" y="230" width="16" height="74" fill="#8C7A66" stroke="#2a1810" strokeWidth="3" />
      <circle cx="436" cy="200" r="34" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      <circle cx="414" cy="216" r="18" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      {/* wall tags */}
      <g fontFamily="'IBM Plex Mono',monospace" fontSize="12" letterSpacing="2">
        <rect x="34" y="150" width="86" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="77" y="167" textAnchor="middle" fill="#2a1810">IDEAS</text>
        <rect x="404" y="120" width="102" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="455" y="137" textAnchor="middle" fill="#2a1810">CAMPAIGNS</text>
        <rect x="404" y="262" width="86" height="26" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
        <text x="447" y="279" textAnchor="middle" fill="#21130e">GROWTH</text>
        <rect x="34" y="230" width="88" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="78" y="247" textAnchor="middle" fill="#2a1810">RESULTS</text>
      </g>
      {/* sun */}
      <circle cx="466" cy="52" r="24" fill="#E8936B" stroke="#2a1810" strokeWidth="3" />
    </svg>
  );
}

/* ── Provider icons for marketing.channels ────────────────────────────
 * Hand-drawn flat inline SVGs (no new dependency, no raster images).
 * External brands use their recognizable marks (Google Ads "A", Meta
 * loop, Instagram camera, envelope for email); internal
 * CRM/Analytics use neutral RazorGrowth glyphs so they are never
 * misrepresented as third-party services. */
function ChannelIcon({ channelKey }: { channelKey: string }) {
  const ink = "#2a1810";
  switch (channelKey) {
    case "google_ads":
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Google Ads logo">
          <line x1="21.5" y1="7" x2="12" y2="29.5" stroke="#FBBC04" strokeWidth="6.5" strokeLinecap="round" />
          <line x1="21.5" y1="7" x2="29" y2="29.5" stroke="#4285F4" strokeWidth="6.5" strokeLinecap="round" />
          <circle cx="11" cy="30.5" r="4.6" fill="#34A853" />
        </svg>
      );
    case "meta_ads":
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Meta logo">
          <path
            d="M20 20 C14 11 6 11 6 20 C6 29 14 29 20 20 C26 11 34 11 34 20 C34 29 26 29 20 20 Z"
            fill="none"
            stroke="#0082FB"
            strokeWidth="3.6"
            strokeLinecap="round"
          />
        </svg>
      );
    case "social":
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Instagram logo">
          <rect x="7" y="7" width="26" height="26" rx="7" fill="none" stroke={ink} strokeWidth="2.8" />
          <circle cx="20" cy="20" r="6.5" fill="none" stroke={ink} strokeWidth="2.8" />
          <circle cx="27.5" cy="12.5" r="2.4" fill="#D97757" />
        </svg>
      );
    case "crm":
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="CRM icon">
          <rect x="6" y="8" width="28" height="24" rx="2" fill="#FFF3DF" stroke={ink} strokeWidth="2.8" />
          <circle cx="15" cy="18" r="4" fill="none" stroke={ink} strokeWidth="2.4" />
          <path d="M9 27c1-3.4 3.4-5 6-5s5 1.6 6 5" fill="none" stroke={ink} strokeWidth="2.4" strokeLinecap="round" />
          <line x1="25" y1="16" x2="30" y2="16" stroke="#3E7D58" strokeWidth="2.4" strokeLinecap="round" />
          <line x1="25" y1="21" x2="30" y2="21" stroke="#3E7D58" strokeWidth="2.4" strokeLinecap="round" />
          <line x1="25" y1="26" x2="28" y2="26" stroke="#3E7D58" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case "analytics":
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Analytics icon">
          <line x1="7" y1="6" x2="7" y2="33" stroke={ink} strokeWidth="2.8" strokeLinecap="round" />
          <line x1="7" y1="33" x2="34" y2="33" stroke={ink} strokeWidth="2.8" strokeLinecap="round" />
          <rect x="12" y="22" width="5" height="9" fill="#3E7D58" />
          <rect x="19.5" y="16" width="5" height="15" fill="#3E7D58" />
          <rect x="27" y="10" width="5" height="21" fill="#D97757" />
        </svg>
      );
    case "email":
    default:
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Email icon">
          <rect x="6" y="10" width="28" height="20" rx="2" fill="#FFF3DF" stroke={ink} strokeWidth="2.8" />
          <path d="M7 12l13 9 13-9" fill="none" stroke="#C85F43" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
  }
}

/* ── Dashboard UI icons ───────────────────────────────────────────────
 * ONE consistent stroke family for every non-provider dashboard icon
 * (currentColor, 1.8px stroke, square 20-grid). Same flat RazorGrowth
 * language as the channel provider marks: ink lines, no fills except
 * tiny accent dots, no gradients, no glow. Sizes stay small (13–22px)
 * so icons anchor headings without dominating content. */
type UiIconName =
  | "search"
  | "spark"
  | "mail"
  | "alert"
  | "bot"
  | "users"
  | "chart"
  | "target"
  | "clock"
  | "check"
  | "check-circle"
  | "send"
  | "play"
  | "git-branch"
  | "clipboard-check"
  | "shield-check"
  | "search-check"
  | "bulb"
  | "pulse"
  | "doc";

function UiIcon({ name, size = 20 }: { name: UiIconName; size?: number }) {
  let body: React.ReactNode;
  switch (name) {
    case "search":
      body = (
        <>
          <circle cx="9" cy="9" r="5.5" />
          <line x1="13.2" y1="13.2" x2="17" y2="17" />
        </>
      );
      break;
    case "spark":
      body = (
        <path
          d="M10 2l1.9 5.6 5.6 1.9-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9z"
          fill="currentColor"
          stroke="none"
        />
      );
      break;
    case "mail":
      body = (
        <>
          <rect x="2.5" y="5" width="15" height="10" rx="1.5" />
          <path d="M3.5 6.5L10 11l6.5-4.5" />
        </>
      );
      break;
    case "alert":
      body = (
        <>
          <path d="M10 2.5L18 16.5H2z" />
          <line x1="10" y1="7.5" x2="10" y2="11.5" />
          <circle cx="10" cy="14" r="0.7" fill="currentColor" stroke="none" />
        </>
      );
      break;
    case "bot":
      body = (
        <>
          <rect x="4" y="7" width="12" height="9" rx="2.5" />
          <line x1="10" y1="7" x2="10" y2="3.5" />
          <circle cx="10" cy="2.8" r="1" fill="currentColor" stroke="none" />
          <circle cx="7.5" cy="11" r="1" fill="currentColor" stroke="none" />
          <circle cx="12.5" cy="11" r="1" fill="currentColor" stroke="none" />
          <line x1="7.5" y1="13.8" x2="12.5" y2="13.8" />
        </>
      );
      break;
    case "users":
      body = (
        <>
          <circle cx="7" cy="7" r="3" />
          <path d="M1.8 16.5c.8-2.8 2.8-4.2 5.2-4.2s4.4 1.4 5.2 4.2" />
          <circle cx="14.2" cy="8" r="2.3" />
          <path d="M14.8 12.6c1.9.3 3.2 1.5 3.7 3.6" />
        </>
      );
      break;
    case "chart":
      body = (
        <>
          <line x1="3" y1="3" x2="3" y2="17" />
          <line x1="3" y1="17" x2="17" y2="17" />
          <line x1="7.2" y1="12" x2="7.2" y2="15" strokeWidth={2.2} />
          <line x1="11.2" y1="8.5" x2="11.2" y2="15" strokeWidth={2.2} />
          <line x1="15.2" y1="5.5" x2="15.2" y2="15" strokeWidth={2.2} />
        </>
      );
      break;
    case "target":
      body = (
        <>
          <circle cx="10" cy="10" r="7" />
          <circle cx="10" cy="10" r="3.5" />
          <circle cx="10" cy="10" r="0.8" fill="currentColor" stroke="none" />
        </>
      );
      break;
    case "clock":
      body = (
        <>
          <circle cx="10" cy="10" r="7" />
          <path d="M10 6.5V10l2.5 1.5" />
        </>
      );
      break;
    case "check":
      body = <path d="M3.5 10.5l4 4L16.5 5.5" strokeWidth={2.2} />;
      break;
    case "bulb":
      body = (
        <>
          <path d="M10 2.5a5.5 5.5 0 0 0-3.2 10c.7.6 1.2 1.3 1.4 2.2h3.6c.2-.9.7-1.6 1.4-2.2A5.5 5.5 0 0 0 10 2.5z" />
          <line x1="8.2" y1="17" x2="11.8" y2="17" />
        </>
      );
      break;
    case "pulse":
      body = <path d="M2 10h4l2-5 3.5 10 2-5H18" strokeWidth={2} />;
      break;
    case "send":
      body = (
        <>
          <path d="M18.3 1.7l-5.8 16.6-3.4-7.5-7.5-3.3z" />
          <line x1="18.3" y1="2" x2="9.2" y2="10.8" />
        </>
      );
      break;
    case "play":
      body = <path d="M6 3.5L16 10 6 16.5z" />;
      break;
    case "check-circle":
      body = (
        <>
          <circle cx="10" cy="10" r="7" />
          <path d="M7 10.3l2.1 2.1 3.9-4.2" />
        </>
      );
      break;
    case "git-branch":
      body = (
        <>
          <line x1="5" y1="2.5" x2="5" y2="12.5" />
          <circle cx="15" cy="5" r="2.5" />
          <circle cx="5" cy="15" r="2.5" />
          <path d="M15 7.5a7.5 7.5 0 0 1-7.5 7.5" />
        </>
      );
      break;
    case "clipboard-check":
      body = (
        <>
          <rect x="7" y="2" width="6" height="3.2" rx="0.8" />
          <path d="M6 4.5H4.8a1.3 1.3 0 0 0-1.3 1.3v11.4a1.3 1.3 0 0 0 1.3 1.3h10.4a1.3 1.3 0 0 0 1.3-1.3V5.8a1.3 1.3 0 0 0-1.3-1.3H14" />
          <path d="M7.3 12.2l1.9 1.9 3.6-3.9" />
        </>
      );
      break;
    case "shield-check":
      body = (
        <>
          <path d="M16.7 10.8c0 4.2-2.9 6.3-6.4 7.5a.8.8 0 0 1-.6 0C6.3 17.1 3.3 15 3.3 10.8V5a.8.8 0 0 1 .8-.8c1.7 0 3.8-1 5.2-2.3a.8.8 0 0 1 1.3 0c1.4 1.3 3.5 2.3 5.2 2.3a.8.8 0 0 1 .9.8z" />
          <path d="M7.6 10l1.7 1.7 3.2-3.4" />
        </>
      );
      break;
    case "search-check":
      body = (
        <>
          <circle cx="9" cy="9" r="6.5" />
          <line x1="13.6" y1="13.6" x2="17.2" y2="17.2" />
          <path d="M6.4 9.3l1.8 1.8 3.1-3.3" />
        </>
      );
      break;
    case "doc":
    default:
      body = (
        <>
          <path d="M5 2.5h6.5L15 6v11.5H5z" />
          <path d="M11.5 2.5V6H15" />
          <line x1="7.5" y1="10.5" x2="12.5" y2="10.5" />
          <line x1="7.5" y1="13.5" x2="12.5" y2="13.5" />
        </>
      );
      break;
  }
  return (
    <svg
      className="magi-uiicon"
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {body}
    </svg>
  );
}

/* Small icon per recent-work run status (real status in, icon out). */
function runIconName(status: string): UiIconName {
  switch (status) {
    case "waiting_approval":
      return "clock";
    case "completed":
      return "check";
    case "running":
    case "queued":
      return "pulse";
    case "blocked":
    case "failed":
      return "alert";
    default:
      return "doc";
  }
}

/* Semantic icon per activity event, keyed ONLY on the canonical backend
 * (event_type, phase) — never on completion status, never on title text.
 * The icon says WHAT happened; the timeline dot says whether it is done.
 * Unknown types fall back to the neutral clock. */
function getActivityIcon(e: MarketingAGIRunEvent): UiIconName {
  switch (e.event_type) {
    case "action_executed":
      return "send";
    case "execution_started":
      return "play";
    case "action_approved":
      return "check-circle";
    case "awaiting_approval":
    case "run_finished":
      return "clock";
    case "handoff_opened":
      return "git-branch";
    case "action_prepared":
      return "clipboard-check";
    case "verification_passed":
      return "shield-check";
    case "verification_failed":
    case "action_failed":
    case "action_rejected":
      return "alert";
    case "action_reused":
      return "doc";
    case "phase_started":
      if (e.phase === "verify") return "search-check";
      if (e.phase === "prepare") return "clipboard-check";
      return "pulse";
    case "phase_completed":
      return "check";
    case "tool_used":
    case "tool_failed":
      return "doc";
    case "rag_started":
    case "rag_sufficient":
      return "search";
    case "signals_detected":
      return "chart";
    case "audience_built":
      return "users";
    case "campaign_created":
      return "mail";
    case "workflow_selected":
      return "target";
    case "memory_recalled":
      return "bulb";
    case "llm_decision":
      return "bot";
    case "run_status":
      return "pulse";
    default:
      return "clock";
  }
}

/* ── Component ───────────────────────────────────────────────────────── */

export function MarketingAGIPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<MarketingAGIStatus | null>(null);
  const [runs, setRuns] = useState<MarketingAGIRun[]>([]);
  const [activeRun, setActiveRun] = useState<MarketingAGIRun | null>(null);
  const [events, setEvents] = useState<MarketingAGIRunEvent[]>([]);
  const [campaigns, setCampaigns] = useState<MarketingAGICampaign[]>([]);
  const [learnings, setLearnings] = useState<MarketingAGILearning[]>([]);
  const [handoffs, setHandoffs] = useState<MarketingAGIHandoff[]>([]);
  const [radar, setRadar] = useState<GrowthRadarResponse | null>(null);
  const [analytics, setAnalytics] = useState<AnalyticsOverviewResponse | null>(null);
  const [toolCatalog, setToolCatalog] = useState<
    Array<{ name: string; category: string; description: string; capabilities: string[]; integration_status: string }>
  >([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "login_required" | "no_workspace" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [selectedStack, setSelectedStack] = useState<string | null>(null);
  const [connBusy, setConnBusy] = useState<string | null>(null);
  const [connMsg, setConnMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [auditTrail, setAuditTrail] = useState<import("../types/api").MarketingIntegrationAuditEvent[]>([]);
  const [previewTab, setPreviewTab] = useState<"email" | "details">("email");
  const [showAllRuns, setShowAllRuns] = useState(false);
  // Resend connect form (values stay local; the key is verified live, never displayed back)
  const [resendKey, setResendKey] = useState("");
  const [resendFrom, setResendFrom] = useState("");
  const [resendName, setResendName] = useState("");
  // Manual connect fields for OAuth providers
  const [manualToken, setManualToken] = useState("");
  const [manualAccount, setManualAccount] = useState("");
  const lastSeqRef = useRef(0);
  const lastSeqRunRef = useRef<string | null>(null);
  // ── Live Activity run identity ─────────────────────────────────────
  // Recent Work and Live Activity share ONE canonical selection: the run
  // that owns the selected logical action (action_id ↔ run.state
  // .prepared_action). Every event response is dropped if the selection
  // moved while it was in flight, and the seq cursor never leaks across
  // runs — two actions/runs can never merge into a single timeline.
  const selectedRunIdRef = useRef<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const loadSeqRef = useRef(0);
  const listSeqRef = useRef(0);
  /* "auto": the page owns the selection and follows live work.
   * "manual": the operator pinned a specific run — never yanked away. */
  const selectionModeRef = useRef<"auto" | "manual">("auto");
  const campaignRef = useRef<HTMLDivElement | null>(null);
  const researchRef = useRef<HTMLDivElement | null>(null);
  const toolActivityRef = useRef<HTMLDivElement | null>(null);

  const beginRunSelection = useCallback((runId: string | null) => {
    selectedRunIdRef.current = runId;
    lastSeqRunRef.current = runId;
    lastSeqRef.current = 0;
  }, []);
  const isStillSelected = useCallback(
    (runId: string) => selectedRunIdRef.current === runId,
    [],
  );
  const cursorFor = useCallback(
    (runId: string) => (lastSeqRunRef.current === runId ? lastSeqRef.current : 0),
    [],
  );
  const commitCursor = useCallback((runId: string, seq: number) => {
    if (lastSeqRunRef.current === runId) lastSeqRef.current = seq;
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  /* initial load — monotonic guard so a stale response never overwrites
   * a newer one (RC21). */
  const loadAll = useCallback(
    async (withActiveRun = true) => {
      const seq = ++loadSeqRef.current;
      try {
        const [st, rs, cs, ls, hs, tc, rd, an] = await Promise.all([
          fetchMarketingAGIStatus(),
          fetchMarketingAGIRuns(),
          fetchMarketingAGICampaigns(),
          fetchMarketingAGILearnings(),
          fetchMarketingAGIHandoffs(),
          fetchMarketingAGITools().catch(() => ({ tools: [] })),
          fetchGrowthRadar().catch(() => null),
          fetchAnalyticsOverview(30).catch(() => null),
        ]);
        if (seq !== loadSeqRef.current) return; // stale — a newer load owns state
        setStatus(st);
        setRuns(rs.runs);
        setCampaigns(cs.campaigns);
        setLearnings(ls.learnings);
        setHandoffs(hs.handoffs);
        setToolCatalog(tc.tools ?? []);
        setRadar(rd);
        setAnalytics(an);
        if (withActiveRun) {
          // A fresh load re-establishes the canonical selection, so the page
          // is free to follow live work again (it never overrides an
          // operator's pinned run — only an explicit reload does that).
          selectionModeRef.current = "auto";
          const running = rs.runs.find((r) => ACTIVE_STATUSES.has(r.status));
          const focus = running ?? rs.runs[0] ?? null;
          // ONE canonical selection drives Recent Work highlight AND Live
          // Activity — established BEFORE any await so in-flight responses
          // for a previously selected run are dropped, never merged.
          beginRunSelection(focus?.id ?? null);
          setActiveRun(focus);
          // Persisted workstream: terminal runs must show historical
          // events, not an empty panel. Events come from the backend —
          // never fabricated, never cleared merely because the run ended.
          if (focus) {
            try {
              const ev = await fetchMarketingAGIEvents(focus.id, 0);
              if (!isStillSelected(focus.id)) return; // selection moved on
              commitCursor(
                focus.id,
                ev.events.length ? ev.events[ev.events.length - 1].seq : 0,
              );
              setEvents(ev.events);
            } catch {
              if (!isStillSelected(focus.id)) return;
              commitCursor(focus.id, 0);
              setEvents([]);
            }
          } else {
            setEvents([]);
          }
        } else {
          // Manual refresh / terminal hand-off: re-pull the SAME selected
          // run's timeline in full (identical result on every refresh).
          const sel = selectedRunIdRef.current;
          if (sel) {
            try {
              const ev = await fetchMarketingAGIEvents(sel, 0);
              if (!isStillSelected(sel)) return;
              commitCursor(sel, ev.events.length ? ev.events[ev.events.length - 1].seq : 0);
              setEvents(ev.events);
            } catch {
              /* keep the current timeline on a transient error */
            }
          }
        }
        setLoadState("ready");
        setErrorMsg(null);
        setLastUpdated(new Date().toISOString());
      } catch (e) {
        if (seq !== loadSeqRef.current) return; // stale error — ignore
        const err = e as { status?: number; message?: string };
        if (err.status === 401) setLoadState("login_required");
        else if (err.status === 403) setLoadState("no_workspace");
        else {
          setLoadState("error");
          setErrorMsg(err.message ?? "Failed to load workstation");
        }
      }
    },
    [beginRunSelection, isStillSelected, commitCursor],
  );

  useEffect(() => {
    loadAll();
    return stopPolling;
  }, [loadAll, stopPolling]);

  /* ── Always-on list refresh ───────────────────────────────────────────
   * Recent Work / Campaigns / Learning / Handoffs must track the backend
   * whether or not the selected run is still pollable. Without this, a page
   * sitting on a completed run never hears about a run started afterwards
   * (no interval exists for a terminal selection) and the workstation goes
   * silent until the operator hits Refresh.
   * A monotonic sequence guard keeps a slow response from landing after a
   * newer load took over the same state. */
  const refreshLists = useCallback(async () => {
    const seq = ++listSeqRef.current;
    const loadSeq = loadSeqRef.current;
    try {
      const [rs, cs, ls, hs] = await Promise.all([
        fetchMarketingAGIRuns(),
        fetchMarketingAGICampaigns(),
        fetchMarketingAGILearnings(),
        fetchMarketingAGIHandoffs(),
      ]);
      // Drop superseded responses: a newer list refresh or a full load that
      // started while this one was in flight now owns the shared state.
      if (seq !== listSeqRef.current || loadSeq !== loadSeqRef.current) return null;
      setRuns(rs.runs);
      setCampaigns(cs.campaigns);
      setLearnings(ls.learnings);
      setHandoffs(hs.handoffs);
      setLastUpdated(new Date().toISOString());
      return rs.runs;
    } catch {
      return null; // transient — keep the previous list state
    }
  }, []);

  /* Move the canonical selection to the live run — ONLY while the page owns
   * the selection (auto). An operator-pinned run is never taken away.
   * The selection is claimed before any await so in-flight responses for the
   * previous run are dropped by the isStillSelected guard. */
  const followLiveWork = useCallback(
    (runs: MarketingAGIRun[]) => {
      if (selectionModeRef.current !== "auto") return;
      const focus = runs.find((r) => ACTIVE_STATUSES.has(r.status)) ?? runs[0] ?? null;
      if (!focus || focus.id === selectedRunIdRef.current) return;
      beginRunSelection(focus.id);
      setEvents([]);
      setActiveRun(focus);
      void (async () => {
        try {
          const ev = await fetchMarketingAGIEvents(focus.id, 0);
          if (!isStillSelected(focus.id)) return;
          commitCursor(
            focus.id,
            ev.events.length ? ev.events[ev.events.length - 1].seq : 0,
          );
          setEvents(ev.events);
        } catch {
          /* header still renders without the stream */
        }
      })();
    },
    [beginRunSelection, isStillSelected, commitCursor],
  );

  /* The cadence above runs for the whole life of the page — independent of
   * which run is selected — so the workstation never goes stale. */
  useEffect(() => {
    const id = window.setInterval(() => {
      void refreshLists().then((runs) => {
        if (runs) followLiveWork(runs);
      });
    }, 3000);
    return () => window.clearInterval(id);
  }, [refreshLists, followLiveWork]);

  /* Compact page footer: hide the shared tall SiteFooter while this page
   * is mounted. The class is removed on unmount, so the homepage and all
   * other routes keep their existing footer untouched. */
  useEffect(() => {
    document.body.classList.add("magi-hide-site-footer");
    return () => document.body.classList.remove("magi-hide-site-footer");
  }, []);

  /* Live event polling for the selected run while it is active OR its
   * canonical action is still open (requested → approved → executing).
   * Approvals/execution made from /actions — even in another tab — are
   * detected without refresh. Shared list state is refreshed by the
   * always-on cadence above, so this loop only owns the timeline + header. */
  const pollActiveRun = useCallback(
    async (runId: string) => {
      if (!isStillSelected(runId)) return;
      try {
        const ev = await fetchMarketingAGIEvents(runId, cursorFor(runId));
        // Drop responses for a run that is no longer the selection — an
        // in-flight poll from the previous action must never land in the
        // newly selected action's timeline.
        if (!isStillSelected(runId)) return;
        if (ev.events.length) {
          commitCursor(runId, ev.events[ev.events.length - 1].seq);
          setEvents((prev) => mergeRunEvents(prev, ev.events));
        }
        const run = await fetchMarketingAGIRun(runId);
        if (!isStillSelected(runId)) return;
        setActiveRun((prev) => (sameRunHeader(prev, run) ? prev : run));

        const prep = run.state?.prepared_action?.status ?? null;
        const stillOpen = prep !== null && OPEN_ACTION_STATUSES.has(prep);
        const stillAwaiting =
          run.status === "waiting_approval" && (prep === null || stillOpen);
        if (TERMINAL_STATUSES.has(run.status) && !stillOpen && !stillAwaiting) {
          stopPolling();
          loadAll(false);
        } else if (
          !ACTIVE_STATUSES.has(run.status) &&
          !stillOpen &&
          !stillAwaiting
        ) {
          stopPolling();
        }
      } catch {
        /* transient — keep polling */
      }
    },
    [loadAll, stopPolling, isStillSelected, cursorFor, commitCursor],
  );

  useEffect(() => {
    stopPolling();
    if (activeRun && shouldPollRun(activeRun)) {
      pollRef.current = window.setInterval(
        () => pollActiveRun(activeRun.id),
        1500,
      );
    }
    return stopPolling;
  }, [activeRun, pollActiveRun, stopPolling]);

  /* This page is a monitoring/workspace view. The Marketing Agent is
   * started exclusively by the AI Team "Start Analysis" orchestration
   * (POST /api/agents/run, mode="team") and runs under the shared
   * analysis cycle — this page never creates a run. */
  const handleCancel = async () => {
    if (!activeRun) return;
    try {
      await cancelMarketingAGIRun(activeRun.id);
    } catch {
      /* cooperative cancel may race the loop finishing */
    }
  };

  /* ── integration hub actions (all hit the live backend) ─────────── */
  const refreshStatus = useCallback(async () => {
    try {
      const st = await fetchMarketingAGIStatus();
      setStatus(st);
    } catch {
      /* transient */
    }
  }, []);

  const stackProviderFor = (stackKey: string): string | null => {
    const entry = stack.find((s) => s.key === stackKey);
    return entry?.provider ?? null;
  };

  const handleTest = async (stackKey: string) => {
    const provider = stackProviderFor(stackKey);
    if (!provider || provider === "internal") return;
    setConnBusy(provider);
    setConnMsg(null);
    try {
      const res = await testMarketingIntegration(provider);
      setConnMsg({
        ok: res.ok,
        text: res.ok
          ? `✓ Connection verified — ${res.account?.ad_account_name ?? res.account?.username ?? res.account?.customer_name ?? provider} · ${res.verified_at ?? ""}`
          : `✕ Connection failed — ${res.error_code}: ${res.message}`,
      });
    } catch (e) {
      setConnMsg({ ok: false, text: `✕ Test failed — ${(e as Error).message}` });
    } finally {
      setConnBusy(null);
      refreshStatus();
    }
  };

  const handleDisconnect = async (stackKey: string) => {
    const provider = stackProviderFor(stackKey);
    if (!provider || provider === "internal") return;
    setConnBusy(provider);
    setConnMsg(null);
    try {
      await disconnectMarketingIntegration(provider);
      setConnMsg({ ok: true, text: "Disconnected. Stored credentials were wiped." });
    } catch (e) {
      setConnMsg({ ok: false, text: `✕ Disconnect failed — ${(e as Error).message}` });
    } finally {
      setConnBusy(null);
      refreshStatus();
    }
  };

  const handleOAuth = async (stackKey: string) => {
    const provider = stackProviderFor(stackKey);
    if (!provider) return;
    setConnBusy(provider);
    setConnMsg(null);
    try {
      const res = await startMarketingOAuth(
        provider,
        // Google Ads: carry the Customer ID the operator typed (validated
        // to digits before it reaches the signed state).
        provider === "google_ads" ? googleCustomerSelector(manualAccount) : undefined,
      );
      window.location.href = res.authorization_url;
    } catch (e) {
      setConnMsg({ ok: false, text: `✕ OAuth start failed — ${(e as Error).message}` });
      setConnBusy(null);
    }
  };

  const handleConnectResend = async () => {
    setConnBusy("resend");
    setConnMsg(null);
    try {
      await connectMarketingIntegration("resend", {
        api_key: resendKey,
        from_email: resendFrom,
        from_name: resendName || undefined,
      });
      setConnMsg({ ok: true, text: "✓ Resend connected and verified live." });
      setResendKey("");
    } catch (e) {
      setConnMsg({ ok: false, text: `✕ Connect failed — ${(e as Error).message}` });
    } finally {
      setConnBusy(null);
      refreshStatus();
    }
  };

  const handleConnectManual = async (stackKey: string) => {
    const provider = stackProviderFor(stackKey);
    if (!provider) return;
    setConnBusy(provider);
    setConnMsg(null);
    try {
      await connectMarketingIntegration(provider, {
        access_token: manualToken || undefined,
        account_id: manualAccount || undefined,
      });
      setConnMsg({ ok: true, text: `✓ ${provider} connected and verified live.` });
      setManualToken("");
      setManualAccount("");
    } catch (e) {
      setConnMsg({ ok: false, text: `✕ Connect failed — ${(e as Error).message}` });
    } finally {
      setConnBusy(null);
      refreshStatus();
    }
  };

  const openStackModal = async (stackKey: string) => {
    setSelectedStack(stackKey);
    setConnMsg(null);
    try {
      const audit = await fetchMarketingIntegrationAudit();
      setAuditTrail(audit.audit_events ?? []);
    } catch {
      setAuditTrail([]);
    }
  };

  const selectRun = async (runId: string) => {
    // Re-picking the run the page would follow anyway is not an override —
    // anything else pins the selection so live work never yanks it away.
    const followTarget =
      runs.find((r) => ACTIVE_STATUSES.has(r.status))?.id ?? runs[0]?.id ?? null;
    selectionModeRef.current = runId === followTarget ? "auto" : "manual";
    stopPolling();
    // Claim the selection BEFORE any await: responses still in flight for
    // the previously selected run are dropped by the isStillSelected guard.
    beginRunSelection(runId);
    setEvents([]);
    try {
      const run = await fetchMarketingAGIRun(runId);
      if (!isStillSelected(runId)) return;
      // The interval effect below owns the timer — never start a second one.
      setActiveRun(run);
      // Historical workstream for terminal runs (same as mount behavior).
      try {
        const ev = await fetchMarketingAGIEvents(runId, 0);
        if (!isStillSelected(runId)) return;
        commitCursor(
          runId,
          ev.events.length ? ev.events[ev.events.length - 1].seq : 0,
        );
        setEvents(ev.events);
      } catch {
        /* run header still displays without the stream */
      }
    } catch {
      /* ignore */
    }
  };

  const scrollTo = (anchor: string) => {
    if (anchor === "campaign") campaignRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    else if (anchor === "research") researchRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    else toolActivityRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const scrollToCampaign = (tab?: "email" | "details") => {
    if (tab) setPreviewTab(tab);
    campaignRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  /* ── derived real state ────────────────────────────────────────────── */

  const run = activeRun;
  const live = run !== null && ACTIVE_STATUSES.has(run.status);
  // Canonical action status: live overlay from agent_actions (backend),
  // falling back to the campaign row's mirrored action_status.
  const prepStatus = useMemo(() => {
    const fromRun = run?.state?.prepared_action?.status;
    if (fromRun) return fromRun;
    if (!run) return campaigns[0]?.action_status ?? null;
    return campaignForRun(run, campaigns)?.action_status ?? null;
  }, [run, campaigns]);
  const agent = useMemo(() => agentStatus(run, campaigns, prepStatus), [run, campaigns, prepStatus]);
  const stepIndex = useMemo(
    () => eightStepIndex(run, campaigns, learnings),
    [run, campaigns, learnings],
  );
  const state = run?.state;
  const toolCalls = state?.tool_calls ?? [];

  const stack: MarketingStackEntry[] = useMemo(
    () => status?.marketing_stack ?? [],
    [status],
  );

  /* ── OAuth callback round-trip ───────────────────────────────────────
   * The provider sends the browser to the backend callback, which has no
   * auth header and therefore never renders provider payloads: it 302s
   * back here with ONLY integration/status/code (whitelisted codes).
   * Step 1 (below) renders the merchant copy and strips the params so a
   * refresh doesn't replay the banner. Step 2 opens the matching
   * connection modal once the stack status has loaded. */
  const pendingOauthIntegrationRef = useRef<string | null>(null);

  useEffect(() => {
    const raw = window.location.search;
    if (!raw || raw === "?") return;
    const cb = parseIntegrationCallback(raw);
    if (!cb.integration || !cb.status) return;
    const msg = oauthResultMessage(raw);
    if (msg) setConnMsg(msg);
    pendingOauthIntegrationRef.current = cb.integration;
    void refreshStatus();
    navigate({ pathname: "/marketing-agent", search: "" }, { replace: true });
  }, [navigate, refreshStatus]);

  useEffect(() => {
    const pending = pendingOauthIntegrationRef.current;
    if (!pending) return;
    const entry = stack.find((s) => s.provider === pending);
    if (!entry) return;
    pendingOauthIntegrationRef.current = null;
    setSelectedStack(entry.key);
  }, [stack]);

  const orderedStack = useMemo(() => {
    const byKey = new Map(stack.map((s) => [s.key, s]));
    const ordered = CHANNEL_ORDER.map((k) => byKey.get(k)).filter(
      (s): s is MarketingStackEntry => Boolean(s),
    );
    for (const s of stack) if (!CHANNEL_ORDER.includes(s.key)) ordered.push(s);
    return ordered;
  }, [stack]);

  const stackActivity = useMemo(() => {
    const byKey: Record<string, { count: number; last: string | null }> = {};
    for (const entry of stack) {
      const names = new Set(entry.tools);
      let count = 0;
      let last: string | null = null;
      for (const c of toolCalls) {
        if (names.has(c.tool)) {
          count += 1;
          if (c.ts) last = c.ts;
        }
      }
      byKey[entry.key] = { count, last };
    }
    return byKey;
  }, [stack, toolCalls]);

  const draft = state?.campaign_draft as
    | {
        name?: string;
        objective?: string;
        audience_count?: number;
        workflow?: string;
        content?: { message?: string; subject_variants?: string[]; variants?: string[]; cta?: string; timing?: string };
        expected_impact?: { rationale?: string; estimated_revenue_inr?: number; risks?: string[] };
        success_metric?: string;
        integration_status?: string;
        channel?: string;
      }
    | null
    | undefined;
  const verification = state?.verification as
    | { passed: boolean; checks: Array<{ name: string; passed: boolean; detail: string }>; failed?: string[] }
    | null
    | undefined;
  const preparedAction = state?.prepared_action as
    | { action_id: string; status: string; approval_state: string }
    | null
    | undefined;

  const runCampaign: MarketingAGICampaign | null = useMemo(
    () => campaignForRun(run, campaigns),
    [run, campaigns],
  );
  const lifecycle = runCampaign?.lifecycle ?? (draft ? "draft" : "idea");
  const audience = (runCampaign?.audience ?? null) as {
    criteria?: Record<string, unknown>;
    customer_ids?: string[];
  } | null;

  /* Business snapshot — real backend values only. Revenue/customers from
   * analytics (falling back to growth radar); recovery figures from the
   * real campaign draft / campaign row. */
  const totalRevenue = analytics?.revenue.current_period ?? radar?.metrics.captured_revenue ?? null;
  const revenueDelta = analytics?.revenue.change_percentage ?? null;
  const totalCustomers = analytics?.customers.total_customers ?? radar?.metrics.total_customers ?? null;
  const audienceCount = draft?.audience_count ?? runCampaign?.audience_count ?? null;
  const recoveryValue =
    draft?.expected_impact?.estimated_revenue_inr ?? runCampaign?.estimated_revenue_inr ?? null;
  const hasOpportunity =
    audienceCount !== null && audienceCount !== undefined && audienceCount > 0 &&
    recoveryValue !== null && recoveryValue !== undefined;

  /* Canonical action state for the focused work: the live agent_actions
   * status (overlaid by the backend), falling back to the campaign row's
   * mirrored action_status, then to the legacy parked-run heuristic.
   * `requested` is the ONLY state that means "waiting for approval". */
  const canonicalActionState: string | null =
    prepStatus ??
    (preparedAction ? "requested" : null) ??
    (run?.status === "waiting_approval" ? "requested" : null);
  const needsApproval = canonicalActionState === "requested";
  const campaignName = draft?.name ?? runCampaign?.name ?? null;
  const campaignChannel = draft?.channel ?? runCampaign?.channel ?? "email";
  const mailContent = (draft?.content ?? runCampaign?.content ?? null) as {
    message?: string;
    subject_variants?: string[];
    cta?: string;
    timing?: string;
  } | null;
  const mailSubject = mailContent?.subject_variants?.[0] ?? "Your order is waiting";
  const mailBody = mailContent?.message ?? null;
  const mailCta = mailContent?.cta ?? "Complete your payment";
  const mailTiming =
    mailContent?.timing ??
    (runCampaign?.content as { timing?: string } | null)?.timing ??
    "Immediately + 3 days";

  const topHypothesis = state?.hypotheses?.[0] ?? null;
  const impactBadge = topHypothesis
    ? topHypothesis.confidence >= 0.75
      ? "High Impact"
      : topHypothesis.confidence >= 0.45
        ? "Medium Impact"
        : "Low Impact"
    : hasOpportunity
      ? "High Impact"
      : null;

  const sources = useMemo(
    () => evidenceSources(toolCalls, (state?.evidence.length ?? 0) > 0),
    [toolCalls, state],
  );

  const activityFeed = useMemo(
    () => [...events].reverse().slice(0, 8),
    [events],
  );

  /* Recent Work is grouped by canonical action identity (prepared
   * action_id) — never by title/amount/timestamp. Runs linked to the same
   * open action (re-runs, retries, shared cycles) consolidate into ONE row
   * showing the live canonical state; runs that produced genuinely
   * separate actions stay separate rows, disambiguated by action id.
   *
   * Deterministic canonical run: `runs` arrives ordered by created_at DESC
   * from the backend, so groupRuns[0] is ALWAYS the newest run for that
   * action. Live Activity renders ONLY this canonical run's events — events
   * from other runs are never merged (see list_events scoping + the
   * isStillSelected guard on every async response). */
  interface WorkGroup {
    key: string;
    actionId: string | null;
    latest: MarketingAGIRun;
    runIds: string[];
    count: number;
  }
  const workGroups: WorkGroup[] = useMemo(() => {
    const members = new Map<string, MarketingAGIRun[]>();
    const order: string[] = [];
    for (const r of runs) {
      const aid = r.state?.prepared_action?.action_id ?? null;
      const key = aid ? `action:${aid}` : `run:${r.id}`;
      if (!members.has(key)) {
        members.set(key, []);
        order.push(key);
      }
      members.get(key)!.push(r);
    }
    return order.map((key) => {
      const groupRuns = members.get(key)!;
      return {
        key,
        actionId: groupRuns[0].state?.prepared_action?.action_id ?? null,
        latest: groupRuns[0],
        runIds: groupRuns.map((r) => r.id),
        count: groupRuns.length,
      };
    });
  }, [runs]);
  const visibleGroups = showAllRuns ? workGroups : workGroups.slice(0, 4);

  /* Temporary diagnostic trace (task acceptance): proves the selection +
   * timestamp invariants on every render in dev/beta. Logs the exact IDs
   * and persisted instants at each stage so a browser console snapshot can
   * verify: Recent Work action_id/run_id == Live Activity run_id/action_ids,
   * event seq/created_at + action created_at/completed_at are persisted
   * backend values (never polling-time "now"). */
  useEffect(() => {
    if (!run) return;
    const selectedActionId =
      run.state?.prepared_action?.action_id ?? null;
    const liveRunIds = new Set(events.map((e) => e.run_id));
    const liveActionIds = new Set(
      events.map((e) => e.action_id ?? null),
    );
    // eslint-disable-next-line no-console
    console.debug("[magi-canonical-trace]", {
      selectedRunId: run.id,
      selectedActionId,
      selectedActionStatus: run.state?.prepared_action?.status ?? null,
      selectedRunStartedAt: run.started_at,
      selectedRunCompletedAt: run.completed_at,
      selectedActionCreatedAt: run.action_created_at ?? null,
      selectedActionUpdatedAt: run.action_updated_at ?? null,
      selectedActionCompletedAt: run.action_completed_at ?? null,
      recentWorkTimestamp: canonicalWorkTimestamp(run),
      liveActivityRunIds: [...liveRunIds],
      liveActivityActionIds: [...liveActionIds],
      liveEventCount: events.length,
      liveEventSeqs: events.map((e) => e.seq),
      liveEventCreatedAts: events.map((e) => e.created_at),
      liveActivityBelongsToSelection:
        (liveRunIds.size === 0 ||
          (liveRunIds.size === 1 && liveRunIds.has(run.id))) &&
        [...liveActionIds].every(
          (aid) => aid === null || aid === selectedActionId,
        ),
    });
  }, [run, events]);

  const checklist = {
    audience: (audienceCount ?? 0) > 0,
    content: Boolean(mailBody),
    safety: verification?.passed === true,
  };

  const statusHeadline = hasOpportunity
    ? `Found an opportunity to recover ${rupees(recoveryValue)} from ${audienceCount} customers.`
    : run && live
      ? run.phase === "load_context"
        ? "Getting to know your business…"
        : run.phase === "observe"
          ? "Looking for opportunities in your data…"
          : run.phase === "investigate"
            ? "Researching with real data…"
            : run.phase === "plan"
              ? "Planning the best next move…"
              : run.phase === "create"
                ? "Preparing a campaign…"
                : run.phase === "verify"
                  ? "Running safety checks…"
                  : "Working on your business…"
      : run && run.status === "waiting_approval"
        ? "A campaign is ready for your review."
        : run && run.status === "completed"
          ? "Work complete — here's what I found."
          : "Your marketing employee is ready.";
  const statusSupport =
    state?.observations?.[0] ??
    topHypothesis?.statement ??
    (run
      ? "I've analyzed your business data and prepared what's below. Nothing moves without your approval."
      : "Start an AI Team analysis and I'll investigate your business data here.");

  const modalEntry = selectedStack ? stack.find((s) => s.key === selectedStack) ?? null : null;
  const modalCalls = modalEntry
    ? toolCalls.filter((c) => modalEntry.tools.includes(c.tool))
    : [];

  /* ── render gates ──────────────────────────────────────────────────── */

  if (loadState === "loading") {
    return (
      <div className="magi-world">
        <GlobalEnvironment />
        <div className="magi-shell">
          <p className="magi-loading">Loading Marketing Agent workstation…</p>
        </div>
      </div>
    );
  }

  if (loadState === "login_required") {
    return (
      <div className="magi-world">
        <GlobalEnvironment />
        <div className="magi-shell">
          <WindowPanel title="marketing-agent.app" className="magi-gate">
            <p className="magi-eyebrow">MARKETING AGENT</p>
            <h1 className="magi-gate__title">Your autonomous marketing employee.</h1>
            <p className="magi-gate__lead">
              Log in to monitor the autonomous marketing employee working on your business.
            </p>
            <div style={{ marginTop: 16 }}>
              <Button variant="primary" mono onClick={() => navigate("/login")}>Sign in</Button>
            </div>
          </WindowPanel>
        </div>
      </div>
    );
  }

  if (loadState === "no_workspace") {
    return (
      <div className="magi-world">
        <GlobalEnvironment />
        <div className="magi-shell">
          <WindowPanel title="marketing-agent.app" className="magi-gate">
            <p className="magi-eyebrow">MARKETING AGENT</p>
            <h1 className="magi-gate__title">Your autonomous marketing employee.</h1>
            <p className="magi-gate__lead">
              Your account has no merchant workspace yet. Sign up creates one automatically.
            </p>
          </WindowPanel>
        </div>
      </div>
    );
  }

  return (
    <div className="magi-world">
      <GlobalEnvironment />

      <div className="magi-shell">
        {/* ── HERO — a large WindowPanel, same system as the dashboard ── */}
        <WindowPanel title="marketing.agent" className="magi-hero">
          <div className="magi-hero__inner">
            <div className="magi-hero__copy">
              <p className="magi-eyebrow">MARKETING AGENT</p>
              <h1 className="magi-hero__title">
                Your autonomous
                <br />
                <span className="magi-hero__accent">marketing employee.</span>
              </h1>
              <p className="magi-hero__sub">
                Finds opportunities, researches with real data, prepares campaigns,
                and waits for your approval.
              </p>
            </div>
            <div className="magi-hero__art">
              <AgentOfficeArt />
              <p className="magi-hero__caption">
                <span className="magi-hero__tick" aria-hidden="true" />
                Working to grow
                <br />
                your business 24/7
              </p>
            </div>
          </div>
        </WindowPanel>

        {loadState === "error" && (
          <WindowPanel title="marketing-agent.app" className="magi-gate">
            <p className="magi-error">{errorMsg ?? "Failed to load workstation"}</p>
            <div style={{ marginTop: 12 }}>
              <Button variant="primary" mono onClick={() => loadAll()}>Retry</Button>
            </div>
          </WindowPanel>
        )}

        {/* ── ROW 1: AGENT STATUS + BUSINESS SNAPSHOT ──────────────── */}
        <div className="magi-grid">
          <WindowPanel title="agent.status" className="magi-span-status">
            <div className="magi-status__top">
              <span className="magi-live">
                <UiIcon name="bot" size={22} />
                <span
                  className={`magi-live__dot${agent.live ? " magi-live__dot--on" : ""}`}
                  aria-hidden="true"
                />
                {agent.live ? "Working on your business" : merchantRunStateLabel(run?.status ?? "idle")}
              </span>
              <span className="magi-status__meta">
                Last updated: {lastUpdated ? relTime(lastUpdated) : "—"}
                <button type="button" className="magi-refresh" onClick={() => loadAll(false)}>
                  Refresh
                </button>
                {live && (
                  <button type="button" className="magi-refresh magi-refresh--danger" onClick={handleCancel}>
                    Cancel run
                  </button>
                )}
              </span>
            </div>

            <div className="magi-status__main">
              <div className="magi-status__left">
                <h2 className="magi-status__headline">{statusHeadline}</h2>
                <p className="magi-status__support">{statusSupport}</p>
                {(draft || runCampaign) && (
                  <div className="magi-status__actions">
                    <Button variant="primary" mono onClick={() => scrollToCampaign("email")}>
                      Review Campaign →
                    </Button>
                    <Button variant="secondary" mono onClick={() => scrollToCampaign("details")}>
                      View Details
                    </Button>
                  </div>
                )}
              </div>
              <div className="magi-status__check">
                <p className="magi-status__checktitle">
                  CAMPAIGN
                  <br />
                  READY
                </p>
                <ul className="magi-checklist">
                  <li className={checklist.audience ? "is-done" : ""}>
                    <span aria-hidden="true">{checklist.audience ? "✓" : "○"}</span> Audience prepared
                  </li>
                  <li className={checklist.content ? "is-done" : ""}>
                    <span aria-hidden="true">{checklist.content ? "✓" : "○"}</span> Content drafted
                  </li>
                  <li className={checklist.safety ? "is-done" : ""}>
                    <span aria-hidden="true">{checklist.safety ? "✓" : "○"}</span> Safety checked
                  </li>
                  <li className={needsApproval ? "is-now" : ""}>
                    <span aria-hidden="true">{needsApproval ? "●" : "○"}</span> Waiting for approval
                  </li>
                </ul>
              </div>
            </div>
          </WindowPanel>

          <WindowPanel title="business.snapshot" className="magi-span-snapshot">
            <div className="magi-snap">
              <div className="magi-snap__cell">
                <span className="magi-snap__value"><UiIcon name="chart" size={18} />{totalRevenue !== null ? rupees(totalRevenue) : "—"}</span>
                <span className="magi-snap__label">Total Revenue</span>
                <span className="magi-snap__delta">{fmtDelta(revenueDelta)}</span>
              </div>
              <div className="magi-snap__cell">
                <span className="magi-snap__value"><UiIcon name="users" size={18} />{totalCustomers !== null ? totalCustomers.toLocaleString("en-IN") : "—"}</span>
                <span className="magi-snap__label">Total Customers</span>
                <span className="magi-snap__delta">→ live</span>
              </div>
              <div className="magi-snap__cell">
                <span className="magi-snap__value"><UiIcon name="target" size={18} />{recoveryValue !== null ? rupees(recoveryValue) : "—"}</span>
                <span className="magi-snap__label">Recovery Opportunity</span>
              </div>
              <div className="magi-snap__cell">
                <span className="magi-snap__value"><UiIcon name="users" size={18} />{audienceCount !== null ? audienceCount.toLocaleString("en-IN") : "—"}</span>
                <span className="magi-snap__label">Customers Affected</span>
              </div>
            </div>
            {!run && (
              <p className="magi-stream__empty">
                Live business figures appear here once the agent has run.
              </p>
            )}
          </WindowPanel>

          {/* ── ROW 2: AGENT PROGRESS (full width) ─────────────────── */}
          <WindowPanel title="agent.progress" className="magi-span-full">
            <ol className="magi-steps" aria-label="Agent progress">
              {EIGHT_STEPS.map((s, i) => (
                <li
                  key={s.top + s.bottom}
                  className={`magi-steps__step${i < stepIndex ? " is-done" : ""}${i === stepIndex ? " is-now" : ""}`}
                  aria-current={i === stepIndex ? "step" : undefined}
                >
                  <span className="magi-steps__node" aria-hidden="true">
                    {i < stepIndex ? (
                      <svg className="magi-steps__check" viewBox="0 0 16 16" width="17" height="17" aria-hidden="true">
                        <path
                          d="M3 8.5l3.5 3.5L13 4.5"
                          fill="none"
                          stroke="#FFF3DF"
                          strokeWidth="2.4"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : (
                      i + 1
                    )}
                  </span>
                  <span className="magi-steps__words">
                    <span>{s.top}</span>
                    {s.bottom && <span>{s.bottom}</span>}
                  </span>
                </li>
              ))}
            </ol>
            <p className="magi-steps__caption">
              {stepIndex < 0
                ? "Not started yet — start an AI Team analysis to put the agent to work."
                : lifecycle === "rejected"
                  ? "Current stage: Not approved (from live agent state)"
                  : lifecycle === "failed"
                    ? "Current stage: Execution failed (from live agent state)"
                    : `Current stage: ${EIGHT_STEPS[stepIndex].top} ${EIGHT_STEPS[stepIndex].bottom} (from live agent state)`}
            </p>
          </WindowPanel>

          {/* ── ROW 3: APPROVAL REQUIRED (right-aligned) ───────────── */}
          <div className="magi-span-approval">
            <WindowPanel title="approval.required" className={needsApproval ? "magi-approval magi-approval--hot" : "magi-approval"}>
              <div className="magi-approval__head">
                <span className="magi-approval__icon" aria-hidden="true"><UiIcon name="alert" size={15} /></span>
                <h2 className="magi-approval__title">
                  {canonicalActionState === "approved"
                    ? "Approved"
                    : canonicalActionState === "executing"
                      ? "Executing"
                      : canonicalActionState === "completed"
                        ? "Campaign executed"
                        : canonicalActionState === "failed"
                          ? "Execution failed"
                          : canonicalActionState === "rejected"
                            ? "Not approved"
                            : needsApproval
                              ? "Your approval needed"
                              : "Approvals"}
                </h2>
              </div>
              {needsApproval ? (
                <>
                  <p className="magi-approval__campaign">{campaignName ?? "Campaign ready"}</p>
                  <p className="magi-approval__meta">
                    {audienceCount ?? "—"} customers · {recoveryValue !== null ? rupees(recoveryValue) : "—"} opportunity · {campaignChannel === "email" ? "Email" : prettifyTechnical(campaignChannel)}
                  </p>
                  <p className="magi-approval__note">
                    Nothing will be sent until you approve this campaign.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="primary" mono onClick={() => scrollToCampaign("email")}>
                      Review Campaign →
                    </Button>
                    <Button variant="secondary" mono onClick={() => navigate("/actions")}>
                      Approve &amp; Continue
                    </Button>
                  </div>
                </>
              ) : canonicalActionState === "approved" ? (
                <>
                  <p className="magi-approval__campaign">{campaignName ?? "Campaign ready"}</p>
                  <p className="magi-approval__meta">
                    {audienceCount ?? "—"} customers · {recoveryValue !== null ? rupees(recoveryValue) : "—"} opportunity · {campaignChannel === "email" ? "Email" : prettifyTechnical(campaignChannel)}
                  </p>
                  <p className="magi-approval__note">
                    Approved — ready to execute. Run it from Approvals when you&apos;re ready.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="primary" mono onClick={() => navigate("/actions")}>
                      Open in Actions →
                    </Button>
                    <Button variant="secondary" mono onClick={() => scrollToCampaign("email")}>
                      Review Campaign
                    </Button>
                  </div>
                </>
              ) : canonicalActionState === "executing" ? (
                <>
                  <p className="magi-approval__campaign">{campaignName ?? "Campaign"}</p>
                  <p className="magi-approval__note">
                    Campaign execution is running. Results will appear here once finished.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="secondary" mono onClick={() => navigate("/actions")}>
                      Open in Actions →
                    </Button>
                  </div>
                </>
              ) : canonicalActionState === "completed" ? (
                <>
                  <p className="magi-approval__campaign">{campaignName ?? "Campaign"}</p>
                  <p className="magi-approval__note">
                    Campaign executed. Outcomes will feed future recommendations.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="secondary" mono onClick={() => navigate("/actions")}>
                      Open in Actions →
                    </Button>
                  </div>
                </>
              ) : canonicalActionState === "failed" ? (
                <>
                  <p className="magi-approval__campaign">{campaignName ?? "Campaign"}</p>
                  <p className="magi-approval__note">
                    Execution failed — nothing was sent. Check Actions for the recorded error.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="secondary" mono onClick={() => navigate("/actions")}>
                      Open in Actions →
                    </Button>
                  </div>
                </>
              ) : canonicalActionState === "rejected" ? (
                <>
                  <p className="magi-approval__campaign">{campaignName ?? "Campaign"}</p>
                  <p className="magi-approval__note">
                    You declined this proposal — nothing was sent.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="secondary" mono onClick={() => navigate("/agents")}>
                      Open AI Team →
                    </Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="magi-approval__meta">No approvals pending.</p>
                  <p className="magi-approval__note">
                    Nothing will be sent without your approval — proposed campaigns will appear here.
                  </p>
                  <div className="magi-approval__actions">
                    <Button variant="secondary" mono onClick={() => navigate("/actions")}>
                      Open Approvals →
                    </Button>
                  </div>
                </>
              )}
            </WindowPanel>
          </div>

          {/* ── ROW 4: WHAT I FOUND / RECOMMENDATION / PREVIEW ─────── */}
          <WindowPanel title="what.i.found" className="magi-span-third">
            <div className="magi-sec__head">
              <span className="magi-sec__icon" aria-hidden="true"><UiIcon name="search" size={15} /></span>
              <h2 className="magi-sec__title">
                {campaignName ?? (run ? merchantRunTitle(run) : "Payment recovery opportunity")}
              </h2>
            </div>
            {run || draft || runCampaign ? (
              <>
                <p className="magi-sec__text">
                  {state?.observations?.[0] ??
                    topHypothesis?.statement ??
                    runCampaign?.objective ??
                    "The agent hasn't recorded findings for this run yet."}
                </p>
                <div className="magi-found__metrics">
                  <div className="magi-found__metric">
                    <span className="magi-found__value">{recoveryValue !== null ? rupees(recoveryValue) : "—"}</span>
                    <span className="magi-found__label">Recoverable revenue</span>
                  </div>
                  <div className="magi-found__metric">
                    <span className="magi-found__value">{audienceCount !== null ? audienceCount : "—"}</span>
                    <span className="magi-found__label">Customers affected</span>
                  </div>
                </div>
                {hasOpportunity && (
                  <div className="magi-sec__block">
                    <h3 className="magi-sec__h">Why this matters</h3>
                    <p className="magi-sec__text">
                      These customers have already shown purchase intent, so they may be
                      more likely to complete the transaction.
                    </p>
                  </div>
                )}
                {sources.length > 0 && (
                  <div className="magi-sec__block">
                    <h3 className="magi-sec__h">Based on</h3>
                    <div className="magi-chiprow">
                      {sources.map((s) => (
                        <span key={s} className="magi-tag">{s}</span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <p className="magi-stream__empty">
                No findings yet — start an AI Team analysis and I'll investigate your
                business data here.
              </p>
            )}
          </WindowPanel>

          <WindowPanel title="my.recommendation" className="magi-span-third">
            <div className="magi-sec__head">
              <span className="magi-sec__icon" aria-hidden="true"><UiIcon name="spark" size={15} /></span>
              <h2 className="magi-sec__title">{campaignName ?? "Failed payment recovery"}</h2>
            </div>
            {impactBadge && <span className="magi-badge">{impactBadge}</span>}
            {(draft || runCampaign) ? (
              <>
                <p className="magi-sec__text">
                  {draft?.objective ?? runCampaign?.objective ?? "Reach out to customers whose payments didn't complete and give them a simple way to finish their purchase."}
                </p>
                <dl className="magi-rec">
                  <div><dt>Audience</dt><dd>{audienceCount !== null ? `${audienceCount} customers` : "—"}</dd></div>
                  <div><dt>Potential recovery</dt><dd>{recoveryValue !== null ? rupees(recoveryValue) : "—"}</dd></div>
                  <div><dt>Channel</dt><dd>{campaignChannel === "email" ? "Email" : prettifyTechnical(campaignChannel)}</dd></div>
                  <div><dt>Timing</dt><dd>{mailTiming}</dd></div>
                </dl>
                <div className="magi-sec__actions">
                  <Button variant="primary" mono onClick={() => scrollToCampaign("email")}>
                    Review Campaign →
                  </Button>
                  <Button variant="secondary" mono onClick={() => scrollTo("research")}>
                    View Strategy
                  </Button>
                </div>
              </>
            ) : (
              <p className="magi-stream__empty">
                No recommendation yet. Once the agent finds something worth acting on,
                the plan will appear here.
              </p>
            )}
          </WindowPanel>

          <div ref={campaignRef} className="magi-span-third magi-anchor" />
          <WindowPanel title="campaign.preview" className="magi-span-third magi-span-preview">
            <div className="magi-prev__tabs" role="tablist" aria-label="Campaign preview">
              <span className="magi-prev__icon" aria-hidden="true"><UiIcon name="mail" size={17} /></span>
              <button
                type="button"
                role="tab"
                aria-selected={previewTab === "email"}
                className={`magi-prev__tab${previewTab === "email" ? " is-active" : ""}`}
                onClick={() => setPreviewTab("email")}
              >
                Email Preview
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={previewTab === "details"}
                className={`magi-prev__tab${previewTab === "details" ? " is-active" : ""}`}
                onClick={() => setPreviewTab("details")}
              >
                Details
              </button>
              <span className="magi-prev__status">
                {(() => {
                  const ws = canonicalWorkState(lifecycle, run?.status);
                  return <StatusChip tone={ws.tone}>{ws.label}</StatusChip>;
                })()}
              </span>
            </div>

            {previewTab === "email" ? (
              draft || runCampaign ? (
                <div className="magi-mail">
                  <p className="magi-mail__row">
                    <span>From</span>
                    <strong>Your Store &lt;noreply@yourstore.com&gt;</strong>
                  </p>
                  <p className="magi-mail__row">
                    <span>Subject</span>
                    <strong>{mailSubject}</strong>
                  </p>
                  <div className="magi-mail__body">
                    <p className="magi-mail__brand">Your Store</p>
                    <h3 className="magi-mail__subject">{mailSubject}</h3>
                    {mailBody ? (
                      <p className="magi-mail__text">{mailBody}</p>
                    ) : (
                      <p className="magi-mail__text magi-mail__text--muted">
                        The agent hasn't drafted the message body yet — it will appear
                        here once prepared.
                      </p>
                    )}
                    <span className="magi-mail__cta">{mailCta}</span>
                  </div>
                </div>
              ) : (
                <p className="magi-stream__empty">
                  No campaign content yet. A realistic preview appears here once the
                  agent drafts one.
                </p>
              )
            ) : draft || runCampaign ? (
              <div className="magi-details">
                <div className="magi-lifecycle" aria-label="Campaign lifecycle">
                  {LIFECYCLE_STEPS.map((s, i) => {
                    const idx = lifecycleIndex(lifecycle);
                    return (
                      <span
                        key={s}
                        className={`magi-lifecycle__step${i === idx ? " magi-lifecycle__step--now" : ""}${i < idx ? " magi-lifecycle__step--done" : ""}`}
                      >
                        {s.replace(/_/g, " ")}
                      </span>
                    );
                  })}
                </div>
                <dl className="magi-rec">
                  <div><dt>Objective</dt><dd>{draft?.objective ?? runCampaign?.objective ?? "—"}</dd></div>
                  <div>
                    <dt>Audience</dt>
                    <dd>
                      {audienceCount !== null ? `${audienceCount} customers (real, verified)` : "—"}
                      {audience?.criteria && (
                        <> · criteria: {Object.entries(audience.criteria).map(([k, v]) => `${k}=${String(v)}`).join(", ")}</>
                      )}
                    </dd>
                  </div>
                  <div><dt>Strategy</dt><dd>{draft?.workflow ?? runCampaign?.workflow ?? "—"}</dd></div>
                  <div><dt>Channel</dt><dd>{campaignChannel}</dd></div>
                  <div><dt>Timing</dt><dd>{mailTiming}</dd></div>
                  <div>
                    <dt>Expected impact</dt>
                    <dd>
                      {draft?.expected_impact?.rationale ??
                        (runCampaign?.expected_impact as { rationale?: string } | null)?.rationale ?? "—"}
                      {recoveryValue !== null ? ` (${rupees(recoveryValue)})` : ""}
                    </dd>
                  </div>
                  <div><dt>Success metric</dt><dd>{draft?.success_metric ?? runCampaign?.success_metric ?? "—"}</dd></div>
                  <div><dt>Approval state</dt><dd>{preparedAction ? preparedAction.approval_state : "not requested yet"}</dd></div>
                  <div>
                    <dt>Execution state</dt>
                    <dd>
                      {runCampaign?.action_id
                        ? `prepared as action ${runCampaign.action_id.slice(0, 8)}… · lifecycle ${runCampaign.lifecycle.replace(/_/g, " ")}`
                        : "nothing sent — execution requires your approval"}
                    </dd>
                  </div>
                </dl>
                <details className="magi-tech">
                  <summary>Technical details</summary>
                  <dl className="magi-rec">
                    <div><dt>Reasoning engine</dt><dd>{run?.llm_provider ?? status?.llm_provider ?? "Groq"}</dd></div>
                    <div><dt>Model</dt><dd>{run?.llm_model ?? status?.llm_model ?? "—"}</dd></div>
                    <div><dt>Reasoning status</dt><dd>{reasoningStatusLabel(state?.reasoning_status)}</dd></div>
                    <div><dt>Tools this run</dt><dd>{state?.tool_calls.length ?? 0}</dd></div>
                    <div><dt>Run</dt><dd>{run ? `${run.id.slice(0, 8)}… · ${run.iterations} iterations` : "—"}</dd></div>
                    {run?.analysis_cycle_id && (
                      <div><dt>Analysis cycle</dt><dd>{run.analysis_cycle_id.slice(0, 8)}…</dd></div>
                    )}
                  </dl>
                </details>
              </div>
            ) : (
              <p className="magi-stream__empty">No campaign details yet.</p>
            )}
          </WindowPanel>

          {/* ── ROW 5: MARKETING CHANNELS (full width) ─────────────── */}
          <WindowPanel title="marketing.channels" className="magi-span-full">
            <p className="magi-panel__sub">Manage your integrations</p>
            {orderedStack.length === 0 ? (
              <p className="magi-stream__empty">
                {status
                  ? "Marketing stack unavailable — the backend did not return stack data for this workspace."
                  : "Loading marketing stack…"}
              </p>
            ) : (
            <div className="magi-channels">
              {orderedStack.map((entry) => {
                const connected = entry.status === "connected";
                const busy = connBusy === entry.provider;
                const blurb = CHANNEL_BLURB[entry.key];
                return (
                  <div key={entry.key} className="magi-channel">
                    <div className="magi-channel__logozone">
                      <ChannelIcon channelKey={entry.key} />
                    </div>
                    <h3 className="magi-channel__name">{CHANNEL_SHORT[entry.key] ?? entry.label.toUpperCase()}</h3>
                    <span className={`magi-channel__pill${connected ? " is-on" : ""}`}>
                      {connected ? "Connected" : entry.status === "draft_only" ? "Draft only" : "Not connected"}
                    </span>
                    <p className="magi-channel__blurb">
                      {blurb ? (connected ? blurb.on : blurb.off) : entry.description}
                    </p>
                    <p className="magi-channel__provider">{providerDisplay(entry.provider)}</p>
                    <div className="magi-channel__actions">
                      {!connected && entry.provider !== "internal" && (
                        <button
                          type="button"
                          className="magi-stackcard__btn"
                          disabled={busy}
                          onClick={() => openStackModal(entry.key)}
                        >
                          Connect →
                        </button>
                      )}
                      {connected && entry.provider !== "internal" && (
                        <>
                          <button
                            type="button"
                            className="magi-stackcard__btn"
                            disabled={busy}
                            onClick={() => handleTest(entry.key)}
                          >
                            {busy ? "Testing…" : "Test"}
                          </button>
                          <button
                            type="button"
                            className="magi-stackcard__btn magi-stackcard__btn--danger"
                            disabled={busy}
                            onClick={() => handleDisconnect(entry.key)}
                          >
                            Disconnect
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className="magi-stackcard__btn"
                        onClick={() => openStackModal(entry.key)}
                      >
                        Details →
                      </button>
                    </div>
                  </div>
                  );
              })}
            </div>
            )}
            {connMsg && (
              <p className={`magi-connmsg magi-connmsg--${connMsg.ok ? "ok" : "bad"}`}>
                {connMsg.text}
              </p>
            )}
          </WindowPanel>

          {/* ── ROW 6: RECENT WORK + AGENT ACTIVITY ────────────────── */}
          <WindowPanel title="recent.work" className="magi-span-half">
            <div className="magi-sec__head magi-sec__head--split">
              <h2 className="magi-sec__title">Recent Work</h2>
              {workGroups.length > 4 && (
                <button
                  type="button"
                  className="magi-linkbtn"
                  onClick={() => setShowAllRuns((v) => !v)}
                >
                  {showAllRuns ? "Show less" : "View all →"}
                </button>
              )}
            </div>
            {runs.length === 0 ? (
              <p className="magi-stream__empty">
                No work yet — runs started by the AI Team will appear here.
              </p>
            ) : (
              <ul className="magi-work">
                {visibleGroups.map((g) => {
                  const r = g.latest;
                  // Canonical per-group state: the linked action's campaign
                  // lifecycle first (mirrored from agent_actions), so an
                  // approval/execution in /actions updates this row.
                  const rc = g.actionId
                    ? campaigns.find((c) => c.action_id === g.actionId) ?? null
                    : campaigns.find((c) => c.run_id === r.id) ?? null;
                  const ws = canonicalWorkState(rc?.lifecycle, r.status);
                  return (
                  <li key={g.key}>
                    <button
                      type="button"
                      className={`magi-work__item${run && g.runIds.includes(run.id) ? " is-active" : ""}`}
                      onClick={() => selectRun(g.runIds[0])}
                      data-testid={`recent-work-${g.actionId ?? g.runIds[0]}`}
                      data-action-id={g.actionId ?? ""}
                      data-run-id={g.runIds[0]}
                    >
                      <span className="magi-work__icon" aria-hidden="true">
                        <UiIcon name={runIconName(r.status)} size={17} />
                      </span>
                      <span className="magi-work__title">{merchantRunTitle(r)}</span>
                      <span className={`magi-work__state magi-work__state--${rc?.lifecycle ?? r.status}`}>
                        {ws.label}
                      </span>
                      <span className="magi-work__meta">
                        {r.iterations} iter · {r.tool_call_count} tools · {(() => {
                          const ts = canonicalWorkTimestamp(r);
                          return ts ? relTime(ts) : "—";
                        })()}
                        {g.actionId ? ` · action ${g.actionId.slice(0, 8)}` : ""}
                        {g.count > 1 ? ` · ${g.count} runs` : ""}
                      </span>
                    </button>
                  </li>
                  );
                })}
              </ul>
            )}
          </WindowPanel>

          <WindowPanel title="agent.activity" className="magi-span-half">
            <div className="magi-sec__head">
              <span className={`magi-live__dot${live ? " magi-live__dot--on" : ""}`} aria-hidden="true" />
              <h2 className="magi-sec__title">Live activity</h2>
            </div>
            {activityFeed.length === 0 ? (
              <p className="magi-stream__empty">
                {run
                  ? "No activity recorded for this run yet."
                  : "Activity from the agent will stream in here while it works."}
              </p>
            ) : (
              <ol className="magi-activity" data-testid="live-activity" data-run-id={run?.id ?? ""}>
                {activityFeed.map((e, idx) => {
                  // Indicator state is derived per row from the event's
                  // canonical lifecycle stage plus the selected run's
                  // canonical lifecycle position/terminality/approval (the
                  // same inputs that drive polling) — never from row
                  // position, never from titles. Approval is the boundary:
                  // before the merchant approves, rows stay neutral with
                  // only the live cursor active; orange always means
                  // "completed in the approved execution flow".
                  const rowState = activityRowState(e.event_type, e.phase, {
                    isNewest: idx === 0,
                    runLive: run ? shouldPollRun(run) : false,
                    currentStage: canonicalLifecycleStage(
                      canonicalActionState,
                      run?.status,
                      run?.phase,
                    ),
                    terminal: run
                      ? isLifecycleTerminal(canonicalActionState, run.status)
                      : false,
                    approvalGranted: isApprovalGranted(canonicalActionState),
                  });
                  return (
                    <li
                      key={e.id}
                      className={`magi-activity__row magi-activity__row--${rowState}`}
                      data-testid={`live-event-${e.seq}`}
                      data-run-id={e.run_id}
                      data-action-id={e.action_id ?? ""}
                      data-seq={e.seq}
                      data-created-at={e.created_at}
                      data-state={rowState}
                    >
                      <span className="magi-activity__dot" aria-hidden="true" />
                      <div className="magi-activity__body">
                        <p className="magi-activity__title"><UiIcon name={getActivityIcon(e)} size={14} />{friendlyEvent(e)}</p>
                        <p className="magi-activity__time">{relTime(e.created_at)}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </WindowPanel>

          {/* ── Hidden anchors kept for modal deep-links ───────────── */}
          <div ref={toolActivityRef} style={{ display: "contents" }} />
          <div ref={researchRef} style={{ display: "contents" }} />

          {/* ── ROW 7: WHAT I'M LEARNING (full width) ──────────────── */}
          <WindowPanel title="what.im.learning" className="magi-span-full">
            {(() => {
              // Lifecycle-aware learning state: empty only when genuinely
              // nothing exists; pending/approved/executing distinguished.
              // Handoffs render independently of learnings (RC8).
              const hasLearn = learnings.length > 0;
              const hasHandoff = handoffs.length > 0;
              const stage =
                hasLearn || hasHandoff ? "available"
                : canonicalActionState === "approved" ? "approved"
                : canonicalActionState === "executing" ? "executing"
                : canonicalActionState === "completed" ? "pending"
                : canonicalActionState === "failed" ? "failed-empty"
                : "empty";
              if (stage === "available") {
                return (
              <div className="magi-learnlist">
                {learnings.map((l) => {
                  const facts = learningFacts(l.actual);
                  return (
                  <div key={l.id} className="magi-learn">
                    <div className="magi-learn__head">
                      <span className={`magi-learn__verdict magi-learn__verdict--${l.verdict ?? l.status}`}>
                        <UiIcon name="spark" size={13} />
                        {l.verdict ?? l.status}
                      </span>
                      <span className="magi-learn__date">
                        {new Date(l.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="magi-learn__insight">{l.insights}</p>
                    {facts.length > 0 && (
                      <dl className="magi-learn__facts">
                        {facts.map(([k, v]) => (
                          <div key={k}>
                            <dt>{k}</dt>
                            <dd>{v}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </div>
                  );
                })}
                {hasHandoff && (
                  <div className="magi-block">
                    <h3 className="magi-block__title">Specialist handoffs</h3>
                    {handoffs.map((h) => (
                      <div key={h.id} className="magi-learn">
                        <div className="magi-learn__head">
                          <span className="magi-tag">{h.specialist.replace(/_/g, " ")}</span>
                          <span className="magi-tag magi-tag--src">{h.status}</span>
                        </div>
                        <p className="magi-learn__insight">
                          {(h.request as { question?: string } | null)?.question ?? ""}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
                );
              }
              const copy: Record<string, [string, string]> = {
                empty: [
                  "No campaign results yet.",
                  "Once an approved campaign runs, I'll track the outcome and use what I learn to improve future recommendations.",
                ],
                approved: [
                  "Campaign approved.",
                  "Results will appear after execution.",
                ],
                executing: [
                  "Campaign is executing.",
                  "Outcome measurement is pending.",
                ],
                pending: [
                  "Campaign executed.",
                  "Outcome measurement is pending.",
                ],
                "failed-empty": [
                  "Execution failed.",
                  "No outcome to learn from — check Actions for the recorded error.",
                ],
              };
              const [title, text] = copy[stage];
              return (
              <div className="magi-learnempty">
                <div className="magi-learnempty__copy">
                  <h2 className="magi-sec__title magi-ico-title"><UiIcon name="bulb" size={19} />{title}</h2>
                  <p className="magi-sec__text">{text}</p>
                </div>
                <div className="magi-learnempty__visual" aria-hidden="true">
                  <span className="magi-learnempty__ring" />
                  <p>
                    Continuous improvement
                    <br />
                    <span>Gets smarter over time</span>
                  </p>
                </div>
              </div>
              );
            })()}
          </WindowPanel>
        </div>

        {/* Custom workspace sign-off (the app footer stays as-is via layout) */}
        <p className="magi-signoff">
          <span>RazorGrowth AI — Growth / Agents / Approval</span>
          <span>© {new Date().getFullYear()} · Guardrails on</span>
        </p>
      </div>

      {/* ── Stack detail modal (real backend data, no dead buttons) ──── */}
      {modalEntry && (
        <div
          className="magi-modalback"
          onClick={() => setSelectedStack(null)}
          role="presentation"
        >
          <div
            className="magi-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`${modalEntry.label} work`}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="magi-modal__head">
              <div>
                <p className="magi-eyebrow">MARKETING STACK · REAL BACKEND STATE</p>
                <h2 className="magi-modal__title">{modalEntry.label} Work</h2>
              </div>
              <span className={`magi-int__status magi-int__status--${modalEntry.status}`}>
                {INTEGRATION_LABELS[modalEntry.status] ?? modalEntry.status}
              </span>
            </div>

            <p className="magi-modal__desc">{modalEntry.description}</p>

            {/* ── Live connection (backend truth, never hardcoded) ─── */}
            {modalEntry.provider === "internal" ? (
              <div className="magi-modal__note">
                <strong>Internal.</strong> This tool runs on your workspace&apos;s own
                database — no external connection is needed or claimed.
              </div>
            ) : (
              <div className="magi-conn">
                <div className="magi-conn__row">
                  <span className="magi-conn__label">Provider</span>
                  <span>{providerDisplay(modalEntry.provider)}</span>
                </div>
                <div className="magi-conn__row">
                  <span className="magi-conn__label">Account</span>
                  <span>{modalEntry.account_name ?? modalEntry.account_id ?? "—"}</span>
                </div>
                <div className="magi-conn__row">
                  <span className="magi-conn__label">Last verified</span>
                  <span>
                    {modalEntry.last_verified_at
                      ? new Date(modalEntry.last_verified_at).toLocaleString("en-IN", { hour12: false })
                      : "never — connect to verify live"}
                  </span>
                </div>
                {modalEntry.connection?.last_error && (
                  <div className="magi-conn__row">
                    <span className="magi-conn__label">Last error</span>
                    <span className="magi-conn__err">{modalEntry.connection.last_error}</span>
                  </div>
                )}
                {modalEntry.status !== "connected" && STACK_CONNECT_HINT[modalEntry.key] && (
                  <p className="magi-modal__desc">{STACK_CONNECT_HINT[modalEntry.key]}</p>
                )}

                {modalEntry.status !== "connected" && modalEntry.key === "email" && (
                  <div className="magi-connform">
                    <label>
                      Resend API key
                      <input
                        type="password"
                        value={resendKey}
                        onChange={(e) => setResendKey(e.target.value)}
                        placeholder="re_…"
                        autoComplete="off"
                      />
                    </label>
                    <label>
                      Sender email (must be on a verified Resend domain)
                      <input
                        type="email"
                        value={resendFrom}
                        onChange={(e) => setResendFrom(e.target.value)}
                        placeholder="brand@company.com"
                        autoComplete="off"
                      />
                    </label>
                    <label>
                      Sender name
                      <input
                        type="text"
                        value={resendName}
                        onChange={(e) => setResendName(e.target.value)}
                        placeholder="Brand"
                        autoComplete="off"
                      />
                    </label>
                    <Button
                      variant="primary"
                      mono
                      disabled={connBusy === "resend" || !resendKey || !resendFrom}
                      onClick={handleConnectResend}
                    >
                      {connBusy === "resend" ? "Verifying…" : "Connect + Verify →"}
                    </Button>
                  </div>
                )}

                {modalEntry.status !== "connected" && modalEntry.key !== "email" && (
                  <div className="magi-connform">
                    <Button
                      variant="primary"
                      mono
                      disabled={connBusy === modalEntry.provider}
                      onClick={() => handleOAuth(modalEntry.key)}
                    >
                      {connBusy === modalEntry.provider
                        ? "Starting…"
                        : modalEntry.key === "social"
                          ? "Connect with Meta OAuth →"
                          : `Connect with ${modalEntry.key === "google_ads" ? "Google" : "Meta"} OAuth →`}
                    </Button>
                    {(modalEntry.key === "meta_ads" || modalEntry.key === "social") && (
                      <>
                        <p className="magi-modal__desc">
                          Or paste a long-lived token manually (verified live before storing):
                        </p>
                        <label>
                          Access token
                          <input
                            type="password"
                            value={manualToken}
                            onChange={(e) => setManualToken(e.target.value)}
                            placeholder="EAAG…"
                            autoComplete="off"
                          />
                        </label>
                        <label>
                          {modalEntry.key === "meta_ads" ? "Ad account ID (optional)" : "Page ID (optional)"}
                          <input
                            type="text"
                            value={manualAccount}
                            onChange={(e) => setManualAccount(e.target.value)}
                            placeholder={modalEntry.key === "meta_ads" ? "act_123…" : "page id…"}
                            autoComplete="off"
                          />
                        </label>
                        <Button
                          variant="secondary"
                          mono
                          disabled={!manualToken || connBusy === modalEntry.provider}
                          onClick={() => handleConnectManual(modalEntry.key)}
                        >
                          Verify + Store Token →
                        </Button>
                      </>
                    )}
                    {modalEntry.key === "google_ads" && (
                      <>
                        <p className="magi-modal__desc">
                          Optional account selection (else the first accessible account is used):
                        </p>
                        <label>
                          Customer ID
                          <input
                            type="text"
                            value={manualAccount}
                            onChange={(e) => setManualAccount(e.target.value)}
                            placeholder="1234567890"
                            autoComplete="off"
                          />
                        </label>
                      </>
                    )}
                  </div>
                )}

                {modalEntry.status === "connected" && (
                  <div className="magi-modal__actions">
                    <Button
                      variant="secondary"
                      mono
                      disabled={connBusy === modalEntry.provider}
                      onClick={() => handleTest(modalEntry.key)}
                    >
                      {connBusy === modalEntry.provider ? "Testing…" : "Test Connection"}
                    </Button>
                    <Button
                      variant="secondary"
                      mono
                      disabled={connBusy === modalEntry.provider}
                      onClick={() => handleDisconnect(modalEntry.key)}
                    >
                      Disconnect
                    </Button>
                  </div>
                )}

                {connMsg && (
                  <p className={`magi-connmsg magi-connmsg--${connMsg.ok ? "ok" : "bad"}`}>
                    {connMsg.text}
                  </p>
                )}

                {auditTrail.filter((a) => a.entity_id === modalEntry.provider).slice(0, 5).length > 0 && (
                  <>
                    <h3 className="magi-block__title">Recent connection audit</h3>
                    <ul className="magi-evidence">
                      {auditTrail
                        .filter((a) => a.entity_id === modalEntry.provider)
                        .slice(0, 5)
                        .map((a) => (
                          <li key={a.id}>
                            <span className="magi-tag">{a.event_type}</span>
                            <span className="magi-evidence__stmt">
                              {new Date(a.created_at).toLocaleString("en-IN", { hour12: false })}
                              {a.actor_id ? ` · ${a.actor_id}` : ""}
                            </span>
                          </li>
                        ))}
                    </ul>
                  </>
                )}
              </div>
            )}

            <h3 className="magi-block__title">
              Agent tool calls ({modalCalls.length})
            </h3>
            {modalCalls.length === 0 ? (
              <p className="magi-stream__empty">
                The agent has not called {modalEntry.label} tools in this run yet.
              </p>
            ) : (
              <ul className="magi-evidence">
                {modalCalls.map((c, i) => (
                  <li key={i}>
                    <span className="magi-tag magi-tag--tool">{c.tool}</span>
                    <span className="magi-evidence__stmt">
                      {c.summary ?? "done"} · {paramsSummary(c.params)}
                      {c.latency_ms ? ` · ${c.latency_ms}ms` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {(modalEntry.key === "email" || modalEntry.key === "google_ads" || modalEntry.key === "meta_ads" || modalEntry.key === "social") && campaigns.length > 0 && (
              <>
                <h3 className="magi-block__title">Prepared drafts ({campaigns.length})</h3>
                <ul className="magi-evidence">
                  {campaigns.slice(0, 5).map((c) => (
                    <li key={c.id}>
                      <span className="magi-tag magi-tag--src">{c.lifecycle.replace(/_/g, " ")}</span>
                      <span className="magi-evidence__stmt">
                        {c.name} — {c.audience_count} customers · {rupees(c.estimated_revenue_inr)} expected
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {modalEntry.key === "crm" && (draft || runCampaign) && (
              <>
                <h3 className="magi-block__title">Audience under work</h3>
                <p className="magi-modal__desc">
                  {draft?.audience_count ?? runCampaign?.audience_count ?? 0} customers
                  {audience?.criteria
                    ? ` · criteria: ${Object.entries(audience.criteria).map(([k, v]) => `${k}=${String(v)}`).join(", ")}`
                    : ""}
                  . All customer data is scoped to your merchant workspace.
                </p>
              </>
            )}

            <div className="magi-modal__actions">
              {(() => {
                const dest = STACK_DESTINATIONS[modalEntry.key];
                if (!dest) return null;
                if (dest.route) {
                  return (
                    <Button variant="primary" mono onClick={() => navigate(dest.route as string)}>
                      {dest.label}
                    </Button>
                  );
                }
                return (
                  <Button
                    variant="primary"
                    mono
                    onClick={() => {
                      setSelectedStack(null);
                      scrollTo(dest.anchor ?? "campaign");
                    }}
                  >
                    {dest.label}
                  </Button>
                );
              })()}
              <Button variant="secondary" mono onClick={() => setSelectedStack(null)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
