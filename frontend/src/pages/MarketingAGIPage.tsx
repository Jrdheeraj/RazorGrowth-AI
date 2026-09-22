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

/* Real agent status derived from backend run state (+ campaign execution).
 * Every value traces to run.status / run.phase / campaign.lifecycle. */
function agentStatus(
  run: MarketingAGIRun | null,
  campaigns: MarketingAGICampaign[],
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
  if (run.status === "waiting_approval")
    return { key: "ready", label: "READY FOR APPROVAL", live: false };
  if (run.status === "completed") {
    const latest = campaigns[0];
    if (latest && (latest.lifecycle === "executing" || latest.lifecycle === "approved"))
      return { key: "executing", label: "EXECUTING", live: true };
    return { key: "completed", label: "COMPLETED", live: false };
  }
  return { key: "blocked", label: "BLOCKED", live: false };
}

function statusChipTone(key: string): "neutral" | "ok" | "accent" {
  if (key === "ready") return "accent";
  if (key === "completed") return "ok";
  return "neutral";
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
  const lifecycle =
    (run
      ? campaigns.find((c) => c.run_id === run.id) ?? campaigns[0]
      : campaigns[0]
    )?.lifecycle ?? null;
  if (lifecycle === "approved" || lifecycle === "executing") return 6;
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

/* Fallback stack (honest backend truth) used only if /status predates
 * the marketing_stack field. Mirrors backend _STACK_DEFS exactly. */
const STACK_FALLBACK: MarketingStackEntry[] = [
  {
    key: "email",
    label: "Email",
    status: "draft_only",
    description:
      "Platform campaign store + drafts. No external ESP is connected, so sending is impossible; drafts await human approval.",
    tools: ["get_email_campaigns", "get_email_campaign_performance", "create_email_campaign_draft"],
    capabilities: ["email", "campaign_performance", "draft"],
  },
  {
    key: "google_ads",
    label: "Google Ads",
    status: "requires_integration",
    description:
      "No Google Ads account is connected. The agent may prepare strategy and copy, but it cannot inspect or modify ad accounts.",
    tools: ["get_google_ads_campaigns"],
    capabilities: ["google_ads"],
  },
  {
    key: "meta_ads",
    label: "Meta Ads",
    status: "requires_integration",
    description:
      "No Meta Ads account is connected. The agent may prepare strategy and copy, but it cannot inspect or modify ad accounts.",
    tools: ["get_meta_campaigns"],
    capabilities: ["meta_ads"],
  },
  {
    key: "crm",
    label: "CRM",
    status: "connected",
    description:
      "Internal customer data (this merchant's own customers, orders and payments). Fully usable and tenant-scoped; no external CRM exists.",
    tools: ["get_customer_segments", "find_customers", "get_customer_profile"],
    capabilities: ["segments", "search", "profile"],
  },
  {
    key: "analytics",
    label: "Analytics",
    status: "connected",
    description:
      "Internal commerce analytics computed from this merchant's own orders, payments and customers. Fully usable and tenant-scoped.",
    tools: [
      "get_business_overview",
      "get_revenue_trend",
      "get_customer_activity_trend",
      "get_failed_payment_analytics",
    ],
    capabilities: ["revenue", "trends", "failed_payments", "retention"],
  },
  {
    key: "social",
    label: "Social Platforms",
    status: "requires_integration",
    description:
      "No social API is connected. The agent may prepare post concepts and captions as drafts only; it cannot publish.",
    tools: ["get_social_performance"],
    capabilities: ["social"],
  },
];

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
  const clean = text.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!clean) return "Worked on your business";
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

/* Convert internal execution events into merchant-readable language.
 * Only the wording changes — ordering, timing and source events are
 * untouched backend truth. */
function friendlyEvent(e: MarketingAGIRunEvent): string {
  const raw = `${e.event_type} ${e.phase} ${e.message}`.toLowerCase();
  const has = (...keys: string[]) => keys.some((k) => raw.includes(k));
  if (has("waiting") && has("approv")) return "Waiting for your approval";
  if (has("approv") && has("request")) return "Prepared an approval request";
  if (has("verification_passed") || (has("verif") && has("pass")))
    return "Completed campaign safety review";
  if (has("verification_failed") || (has("verif") && has("fail")))
    return "Campaign safety review needs attention";
  if (has("failed_payment")) return "Checked failed payments";
  if (has("revenue_trend") || (has("revenue") && has("trend")))
    return "Reviewed revenue trends";
  if (has("business_overview")) return "Reviewed business performance";
  if (has("customer_activity")) return "Reviewed customer activity";
  if (has("segment") || has("find_customers") || has("customer_profile"))
    return "Reviewed customer segments";
  if (has("rag") || has("retriev")) return "Reviewed business data";
  if (has("campaign_draft") || has("create_email") || (has("draft") && has("campaign")))
    return "Prepared campaign draft";
  if (has("select_campaign") || has("strategy")) return "Prepared campaign strategy";
  if (has("hypothesis")) return "Formed a growth hypothesis";
  if (has("execut")) return "Ran the approved work";
  if (has("measur") || (has("learn") && !has("learning"))) return "Measured results and learned";
  if (has("plan")) return "Planned the next steps";
  if (has("tool")) return "Used a business tool";
  if (has("reasoning") || has("decision") || has("llm")) return "Reasoned about the best approach";
  if (has("run_started") || has("analysis_started")) return "Started working on your business";
  if (has("run_finished") || has("complete")) return "Finished the current work";
  return prettifyTechnical(e.message);
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
 * External brands use their recognizable marks (Google Ads overlapping
 * circles, Meta loop, Instagram camera, envelope for email); internal
 * CRM/Analytics use neutral RazorGrowth glyphs so they are never
 * misrepresented as third-party services. */
function ChannelIcon({ channelKey }: { channelKey: string }) {
  const ink = "#2a1810";
  switch (channelKey) {
    case "google_ads":
      return (
        <svg className="magi-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Google Ads logo">
          <circle cx="15" cy="20" r="11" fill="#4285F4" />
          <circle cx="25" cy="20" r="11" fill="#FBBC04" fillOpacity="0.9" />
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
  const pollRef = useRef<number | null>(null);
  const campaignRef = useRef<HTMLDivElement | null>(null);
  const researchRef = useRef<HTMLDivElement | null>(null);
  const toolActivityRef = useRef<HTMLDivElement | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  /* initial load */
  const loadAll = useCallback(
    async (withActiveRun = true) => {
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
        setStatus(st);
        setRuns(rs.runs);
        setCampaigns(cs.campaigns);
        setLearnings(ls.learnings);
        setHandoffs(hs.handoffs);
        setToolCatalog(tc.tools ?? []);
        setRadar(rd);
        setAnalytics(an);
        if (withActiveRun) {
          const running = rs.runs.find((r) => ACTIVE_STATUSES.has(r.status));
          const focus = running ?? rs.runs[0] ?? null;
          setActiveRun(focus);
          // Persisted workstream: terminal runs must show historical
          // events, not an empty panel. Events come from the backend —
          // never fabricated, never cleared merely because the run ended.
          if (focus) {
            try {
              const ev = await fetchMarketingAGIEvents(focus.id, 0);
              lastSeqRef.current = ev.events.length
                ? ev.events[ev.events.length - 1].seq
                : 0;
              setEvents(ev.events);
            } catch {
              lastSeqRef.current = 0;
              setEvents([]);
            }
          } else {
            lastSeqRef.current = 0;
            setEvents([]);
          }
        }
        setLoadState("ready");
        setErrorMsg(null);
        setLastUpdated(new Date().toISOString());
      } catch (e) {
        const err = e as { status?: number; message?: string };
        if (err.status === 401) setLoadState("login_required");
        else if (err.status === 403) setLoadState("no_workspace");
        else {
          setLoadState("error");
          setErrorMsg(err.message ?? "Failed to load workstation");
        }
      }
    },
    [],
  );

  useEffect(() => {
    loadAll();
    return stopPolling;
  }, [loadAll, stopPolling]);

  /* Compact page footer: hide the shared tall SiteFooter while this page
   * is mounted. The class is removed on unmount, so the homepage and all
   * other routes keep their existing footer untouched. */
  useEffect(() => {
    document.body.classList.add("magi-hide-site-footer");
    return () => document.body.classList.remove("magi-hide-site-footer");
  }, []);

  /* live polling while a run is active — real events only */
  const pollActiveRun = useCallback(
    async (runId: string) => {
      try {
        const ev = await fetchMarketingAGIEvents(runId, lastSeqRef.current);
        if (ev.events.length) {
          lastSeqRef.current = ev.events[ev.events.length - 1].seq;
          setEvents((prev) => [...prev, ...ev.events]);
        }
        const run = await fetchMarketingAGIRun(runId);
        setActiveRun(run);
        if (TERMINAL_STATUSES.has(run.status)) {
          stopPolling();
          loadAll(false);
        }
      } catch {
        /* transient — keep polling */
      }
    },
    [loadAll, stopPolling],
  );

  useEffect(() => {
    stopPolling();
    if (activeRun && ACTIVE_STATUSES.has(activeRun.status)) {
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
      const res = await startMarketingOAuth(provider);
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

  const selectRun = async (runId: string) => {    stopPolling();
    setEvents([]);
    lastSeqRef.current = 0;
    try {
      const run = await fetchMarketingAGIRun(runId);
      setActiveRun(run);
      // Historical workstream for terminal runs (same as mount behavior).
      try {
        const ev = await fetchMarketingAGIEvents(runId, 0);
        lastSeqRef.current = ev.events.length
          ? ev.events[ev.events.length - 1].seq
          : 0;
        setEvents(ev.events);
      } catch {
        /* run header still displays without the stream */
      }
      if (ACTIVE_STATUSES.has(run.status)) {
        pollRef.current = window.setInterval(() => pollActiveRun(runId), 1500);
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
  const agent = useMemo(() => agentStatus(run, campaigns), [run, campaigns]);
  const stepIndex = useMemo(
    () => eightStepIndex(run, campaigns, learnings),
    [run, campaigns, learnings],
  );
  const state = run?.state;
  const toolCalls = state?.tool_calls ?? [];

  const stack: MarketingStackEntry[] = useMemo(() => {
    const remote = status?.marketing_stack;
    if (remote && remote.length > 0) return remote;
    return STACK_FALLBACK;
  }, [status]);

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

  const runCampaign: MarketingAGICampaign | null = useMemo(() => {
    if (!run) return campaigns[0] ?? null;
    return campaigns.find((c) => c.run_id === run.id) ?? campaigns[0] ?? null;
  }, [run, campaigns]);
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

  const needsApproval = Boolean(preparedAction) || run?.status === "waiting_approval";
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

  const visibleRuns = showAllRuns ? runs : runs.slice(0, 4);

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
                <span className="magi-snap__value">{totalRevenue !== null ? rupees(totalRevenue) : "—"}</span>
                <span className="magi-snap__label">Total Revenue</span>
                <span className="magi-snap__delta">{fmtDelta(revenueDelta)}</span>
              </div>
              <div className="magi-snap__cell">
                <span className="magi-snap__value">{totalCustomers !== null ? totalCustomers.toLocaleString("en-IN") : "—"}</span>
                <span className="magi-snap__label">Total Customers</span>
                <span className="magi-snap__delta">→ live</span>
              </div>
              <div className="magi-snap__cell">
                <span className="magi-snap__value">{recoveryValue !== null ? rupees(recoveryValue) : "—"}</span>
                <span className="magi-snap__label">Recovery Opportunity</span>
              </div>
              <div className="magi-snap__cell">
                <span className="magi-snap__value">{audienceCount !== null ? audienceCount.toLocaleString("en-IN") : "—"}</span>
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
                : `Current stage: ${EIGHT_STEPS[stepIndex].top} ${EIGHT_STEPS[stepIndex].bottom} (from live agent state)`}
            </p>
          </WindowPanel>

          {/* ── ROW 3: APPROVAL REQUIRED (right-aligned) ───────────── */}
          <div className="magi-span-approval">
            <WindowPanel title="approval.required" className={needsApproval ? "magi-approval magi-approval--hot" : "magi-approval"}>
              <div className="magi-approval__head">
                <span className="magi-approval__icon" aria-hidden="true">!</span>
                <h2 className="magi-approval__title">Your approval needed</h2>
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
              <span className="magi-sec__icon" aria-hidden="true">◆</span>
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
              <span className="magi-sec__icon" aria-hidden="true">★</span>
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
                <StatusChip tone={needsApproval ? "accent" : "neutral"}>
                  {needsApproval ? "Ready for Approval" : merchantRunStateLabel(run?.status ?? "idle")}
                </StatusChip>
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
              {runs.length > 4 && (
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
                {visibleRuns.map((r) => (
                  <li key={r.id}>
                    <button
                      type="button"
                      className={`magi-work__item${run?.id === r.id ? " is-active" : ""}`}
                      onClick={() => selectRun(r.id)}
                    >
                      <span className="magi-work__title">{merchantRunTitle(r)}</span>
                      <span className={`magi-work__state magi-work__state--${r.status}`}>
                        {merchantRunStateLabel(r.status)}
                      </span>
                      <span className="magi-work__meta">
                        {r.iterations} iter · {r.tool_call_count} tools · {r.started_at ? relTime(r.started_at) : "—"}
                      </span>
                    </button>
                  </li>
                ))}
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
              <ol className="magi-activity">
                {activityFeed.map((e) => (
                  <li key={e.id} className="magi-activity__row">
                    <span className="magi-activity__dot" aria-hidden="true" />
                    <div className="magi-activity__body">
                      <p className="magi-activity__title">{friendlyEvent(e)}</p>
                      <p className="magi-activity__time">{relTime(e.created_at)}</p>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </WindowPanel>

          {/* ── Hidden anchors kept for modal deep-links ───────────── */}
          <div ref={toolActivityRef} style={{ display: "contents" }} />
          <div ref={researchRef} style={{ display: "contents" }} />

          {/* ── ROW 7: WHAT I'M LEARNING (full width) ──────────────── */}
          <WindowPanel title="what.im.learning" className="magi-span-full">
            {learnings.length === 0 ? (
              <div className="magi-learnempty">
                <div className="magi-learnempty__copy">
                  <h2 className="magi-sec__title">No campaign results yet.</h2>
                  <p className="magi-sec__text">
                    Once an approved campaign runs, I&apos;ll track the outcome
                    and use what I learn to improve future recommendations.
                  </p>
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
            ) : (
              <div className="magi-learnlist">
                {learnings.map((l) => (
                  <div key={l.id} className="magi-learn">
                    <div className="magi-learn__head">
                      <span className={`magi-learn__verdict magi-learn__verdict--${l.verdict ?? l.status}`}>
                        {l.verdict ?? l.status}
                      </span>
                      <span className="magi-learn__date">
                        {new Date(l.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="magi-learn__insight">{l.insights}</p>
                  </div>
                ))}
                {handoffs.length > 0 && (
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
            )}
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
