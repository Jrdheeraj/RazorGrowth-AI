/**
 * /marketing-agent — Marketing Agent workstation.
 *
 * The console for the autonomous marketing employee. Every pixel is
 * driven by REAL agent execution state polled from the backend:
 * status, objective, live workstream (real events), current reasoning,
 * research evidence, tool activity, the six-category marketing stack
 * (real integration status), campaign workspace, verification, prepared
 * action, and learning history. No decorative fake animations, no
 * simulated progress, no invented integration status.
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
} from "../lib/api";
import type {
  MarketingAGIStatus,
  MarketingAGIRun,
  MarketingAGIRunEvent,
  MarketingAGICampaign,
  MarketingAGILearning,
  MarketingAGIHandoff,
  MarketingStackEntry,
} from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import { StatusChip } from "../components/StatusIndicator";
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

const RUN_STATUS_LABELS: Record<string, string> = {
  queued: "IDLE",
  running: "WORKING",
  waiting_approval: "READY FOR APPROVAL",
  completed: "COMPLETED",
  blocked: "BLOCKED",
  failed: "BLOCKED",
  cancelled: "IDLE",
};

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

/* User-safe reasoning status for the Groq reasoning engine display. */
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

/* The agent's real workflow, mapped from backend phase — never animated. */
const WORKFLOW_STAGES = [
  "UNDERSTAND",
  "RESEARCH",
  "INVESTIGATE",
  "RETRIEVE",
  "ANALYZE",
  "FORM HYPOTHESIS",
  "SELECT TOOLS",
  "PLAN",
  "CREATE WORK",
  "VERIFY",
  "REQUEST APPROVAL",
  "EXECUTE",
  "MEASURE",
  "LEARN",
] as const;

function workflowIndex(
  run: MarketingAGIRun | null,
  learnings: MarketingAGILearning[],
): number {
  if (!run) return -1;
  const state = run.state;
  if (run.status === "completed" || run.status === "waiting_approval") {
    if (learnings.length > 0) return 13;
    if (state?.prepared_action) return 10;
    return 9;
  }
  switch (run.phase) {
    case "load_context":
      return 0;
    case "observe":
      return 4;
    case "investigate":
      return (state?.retrieval_log?.length ?? 0) > 0 ? 3 : 2;
    case "plan":
      return (state?.hypotheses?.length ?? 0) > 0 ? 7 : 5;
    case "create":
      return 8;
    case "verify":
      return 9;
    case "prepare":
    case "awaiting_approval":
      return 10;
    case "complete":
      return 12;
    default:
      return (state?.tool_calls?.length ?? 0) > 0 ? 6 : 1;
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

function rupees(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
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

function timeOf(ts: string | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleTimeString("en-IN", { hour12: false });
  } catch {
    return "—";
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
  const [toolCatalog, setToolCatalog] = useState<
    Array<{ name: string; category: string; description: string; capabilities: string[]; integration_status: string }>
  >([]);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "login_required" | "no_workspace" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [selectedStack, setSelectedStack] = useState<string | null>(null);
  const [connBusy, setConnBusy] = useState<string | null>(null);
  const [connMsg, setConnMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [auditTrail, setAuditTrail] = useState<import("../types/api").MarketingIntegrationAuditEvent[]>([]);
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
        const [st, rs, cs, ls, hs, tc] = await Promise.all([
          fetchMarketingAGIStatus(),
          fetchMarketingAGIRuns(),
          fetchMarketingAGICampaigns(),
          fetchMarketingAGILearnings(),
          fetchMarketingAGIHandoffs(),
          fetchMarketingAGITools().catch(() => ({ tools: [] })),
        ]);
        setStatus(st);
        setRuns(rs.runs);
        setCampaigns(cs.campaigns);
        setLearnings(ls.learnings);
        setHandoffs(hs.handoffs);
        setToolCatalog(tc.tools ?? []);
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
    else toolActivityRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  /* ── derived real state ────────────────────────────────────────────── */

  const run = activeRun;
  const live = run !== null && ACTIVE_STATUSES.has(run.status);
  const agent = useMemo(() => agentStatus(run, campaigns), [run, campaigns]);
  const wfIndex = useMemo(() => workflowIndex(run, learnings), [run, learnings]);
  const state = run?.state;
  const toolCalls = state?.tool_calls ?? [];

  const catalogByName = useMemo(() => {
    const m = new Map<string, { category: string; description: string; capabilities: string[]; integration_status: string }>();
    for (const t of toolCatalog) m.set(t.name, t);
    return m;
  }, [toolCatalog]);

  const stack: MarketingStackEntry[] = useMemo(() => {
    const remote = status?.marketing_stack;
    if (remote && remote.length > 0) return remote;
    return STACK_FALLBACK;
  }, [status]);

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
  const plan = (state?.plan ?? []) as Array<{ step: string; tool: string; status: string }>;

  const runCampaign: MarketingAGICampaign | null = useMemo(() => {
    if (!run) return campaigns[0] ?? null;
    return campaigns.find((c) => c.run_id === run.id) ?? campaigns[0] ?? null;
  }, [run, campaigns]);
  const lifecycle = runCampaign?.lifecycle ?? (draft ? "draft" : "idea");
  const audience = (runCampaign?.audience ?? null) as {
    criteria?: Record<string, unknown>;
    customer_ids?: string[];
  } | null;

  const modalEntry = selectedStack ? stack.find((s) => s.key === selectedStack) ?? null : null;
  const modalCalls = modalEntry
    ? toolCalls.filter((c) => modalEntry.tools.includes(c.tool))
    : [];

  /* ── render gates ──────────────────────────────────────────────────── */

  if (loadState === "loading") {
    return (
      <div className="magi-page">
        <p className="magi-loading">Loading Marketing Agent workstation…</p>
      </div>
    );
  }

  if (loadState === "login_required") {
    return (
      <div className="magi-page">
        <WindowPanel title="marketing-agent.app" className="magi-banner">
          <h1 className="magi-title">Marketing Agent</h1>
          <p className="magi-lead">
            Log in to monitor the autonomous marketing employee working on your business.
          </p>
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" mono onClick={() => navigate("/login")}>Sign in</Button>
          </div>
        </WindowPanel>
      </div>
    );
  }

  if (loadState === "no_workspace") {
    return (
      <div className="magi-page">
        <WindowPanel title="marketing-agent.app" className="magi-banner">
          <h1 className="magi-title">Marketing Agent</h1>
          <p className="magi-lead">
            Your account has no merchant workspace yet. Sign up creates one automatically.
          </p>
        </WindowPanel>
      </div>
    );
  }

  return (
    <div className="magi-page">
      {/* ── Agent header ─────────────────────────────────────────────── */}
      <WindowPanel title="marketing-agent.app" className="magi-banner" tone="navy" dark>
        <p className="magi-eyebrow">AI TEAM · AUTONOMOUS MARKETING EMPLOYEE</p>
        <div className="magi-banner__row">
          <div>
            <h1 className="magi-title magi-title--light">Marketing Agent</h1>
            <p className="magi-lead magi-lead--light">
              An autonomous marketing employee working on your business. It
              investigates real data, gathers evidence, prepares campaigns, and
              waits for your approval — never acting on customers without you.
            </p>
          </div>
          <div className="magi-banner__actions">
            {live && (
              <Button variant="secondary" mono onClick={handleCancel}>
                Cancel
              </Button>
            )}
            <Button variant="ghost-dark" mono onClick={() => navigate("/agents")}>
              ← AI Team
            </Button>
          </div>
        </div>

        <div className="magi-statusrow">
          <StatusChip tone={statusChipTone(agent.key)} pulse={agent.live}>
            {agent.label}
          </StatusChip>
          <div className="magi-objectivebox">
            <span className="magi-objectivebox__label">Current objective</span>
            <span className="magi-objectivebox__value">
              {run?.objective ?? "No active objective — start an AI Team analysis to assign one."}
            </span>
          </div>
          {status && (
            <span className="magi-meta__item magi-meta__item--light">
              {status.llm_configured
                ? `Reasoning: ${status.llm_model ?? status.llm_provider}`
                : "Reasoning: deterministic (no LLM key)"}
            </span>
          )}
          {run && (
            <span className="magi-meta__item magi-meta__item--light">
              {run.tool_call_count} tool calls · {run.iterations} iterations
            </span>
          )}
        </div>

        {/* AI Team cycle membership — this page never starts a run */}
        <div className="magi-statusrow">
          <span className="magi-meta__item magi-meta__item--light">
            {!run && "Waiting for the next AI Team analysis."}
            {run && live && `Running as part of AI Team analysis${run.analysis_cycle_id ? ` · cycle ${run.analysis_cycle_id.slice(0, 8)}…` : ""}.`}
            {run && !live && (run.status === "waiting_approval" || run.status === "completed") &&
              "Marketing Agent completed this analysis cycle."}
            {run && !live && (run.status === "blocked" || run.status === "failed") &&
              "Marketing Agent run degraded — sibling agents were unaffected."}
          </span>
          {run?.analysis_cycle_id && (
            <span className="magi-meta__item magi-meta__item--light">
              Analysis cycle {run.analysis_cycle_id.slice(0, 8)}…
            </span>
          )}
        </div>

        {/* Reasoning engine — Groq + agentic tools */}
        <div className="magi-statusrow">
          <span className="magi-meta__item magi-meta__item--light">
            AI ENGINE {run?.llm_provider ?? status?.llm_provider ?? "Groq"}
          </span>
          <span className="magi-meta__item magi-meta__item--light">
            MODEL {run?.llm_model ?? status?.llm_model ?? "—"}
          </span>
          <span className="magi-meta__item magi-meta__item--light">
            REASONING STATUS {reasoningStatusLabel(state?.reasoning_status)}
          </span>
          {state?.current_decision && (
            <span className="magi-meta__item magi-meta__item--light">
              CURRENT DECISION {state.current_decision}
            </span>
          )}
          <span className="magi-meta__item magi-meta__item--light">
            TOOLS THIS RUN {state?.tool_calls.length ?? 0}
          </span>
          <span className="magi-meta__item magi-meta__item--light">
            LLM DECISIONS {state?.llm_decisions.length ?? 0}
          </span>
          {(state?.llm_degraded || run?.status === "failed" || run?.status === "blocked") && (
            <span className="magi-meta__item magi-meta__item--light">
              {run?.status === "failed" || run?.status === "blocked"
                ? "DEGRADED / FAILED — LLM unavailable"
                : "Degraded — deterministic fallback"}
            </span>
          )}
        </div>

        {/* Real workflow position — highlights only reached stages */}
        <div className="magi-flow" aria-label="Agent workflow position">
          {WORKFLOW_STAGES.map((s, i) => (
            <span
              key={s}
              className={`magi-flow__stage${i === wfIndex ? " magi-flow__stage--now" : ""}${i < wfIndex ? " magi-flow__stage--done" : ""}`}
              title={i === wfIndex ? "Current stage (from backend execution state)" : s}
            >
              {s}
            </span>
          ))}
        </div>

        {errorMsg && <p className="magi-error">{errorMsg}</p>}
      </WindowPanel>

      <div className="magi-grid">
        {/* ── 1. Live workstream ─────────────────────────────────────── */}
        <WindowPanel title="live-workstream.log" className="magi-panel magi-s7">
          <h2 className="magi-panel__title">Live Workstream</h2>
          <p className="magi-panel__sub">Actual execution events — nothing simulated.</p>
          <div className="magi-stream">
            {events.length === 0 && !live && (
              <p className="magi-stream__empty">
                {run
                  ? "Select a run to view its workstream."
                  : "The agent hasn't worked on this business yet — start an AI Team analysis."}
              </p>
            )}
            {events.map((e) => (
              <div key={e.id} className={`magi-evt magi-evt--${e.event_type}`}>
                <span className="magi-evt__seq">
                  {String(e.seq).padStart(2, "0")}
                </span>
                <span className="magi-evt__phase">{e.phase.replace(/_/g, " ")}</span>
                <span className="magi-evt__msg">{e.message}</span>
              </div>
            ))}
            {live && (
              <div className="magi-evt magi-evt--live">
                <span className="magi-evt__seq">··</span>
                <span className="magi-evt__msg">Working… next event arrives when the backend emits it.</span>
              </div>
            )}
          </div>
        </WindowPanel>

        {/* ── 2. Current reasoning / objective ───────────────────────── */}
        <WindowPanel title="current-reasoning.md" className="magi-panel magi-s5" tone="navy" dark>
          <h2 className="magi-panel__title">Current Reasoning</h2>
          {run ? (
            <>
              <p className="magi-objective">{run.objective}</p>
              <div className="magi-kv">
                <span>Status</span>
                <strong>{agent.label}</strong>
              </div>
              <div className="magi-kv">
                <span>Reasoning engine</span>
                <strong>
                  {run.llm_provider ?? status?.llm_provider ?? "Groq"}
                  {` · ${run.llm_model ?? status?.llm_model ?? "—"}`}
                </strong>
              </div>
              <div className="magi-kv">
                <span>Reasoning status</span>
                <strong>{reasoningStatusLabel(state?.reasoning_status)}</strong>
              </div>
              {state?.reasoning_summary && (
                <p className="magi-objective">{state.reasoning_summary}</p>
              )}
              {state?.current_decision && (
                <div className="magi-kv">
                  <span>Current decision</span>
                  <strong>{state.current_decision}</strong>
                </div>
              )}
              <div className="magi-kv">
                <span>Workflow</span>
                <strong>{state?.workflow?.replace(/_/g, " ") ?? "not selected yet"}</strong>
              </div>
              <div className="magi-kv">
                <span>Evidence</span>
                <strong>{state?.evidence.length ?? 0} items · {state?.hypotheses.length ?? 0} hypotheses</strong>
              </div>
              <div className="magi-kv">
                <span>LLM decisions</span>
                <strong>
                  {state?.llm_decisions.length ?? 0} decisions · {state?.llm_calls ?? 0} calls
                  {(state?.llm_degraded ?? false) ? " · degraded" : ""}
                </strong>
              </div>
              {plan.length > 0 && (
                <div className="magi-block">
                  <h3 className="magi-block__title">Plan</h3>
                  <ol className="magi-plan">
                    {plan.map((p, i) => (
                      <li key={i} className={`magi-plan__step magi-plan__step--${p.status}`}>
                        <span className="magi-plan__tool">{p.tool}</span>
                        <span>{p.step}</span>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {(state?.errors?.length ?? 0) > 0 && (
                <div className="magi-block">
                  <h3 className="magi-block__title">Run notes (honest)</h3>
                  <ul className="magi-list magi-list--gaps">
                    {state!.errors.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <p className="magi-stream__empty">No reasoning yet — run an AI Team analysis to start the agent.</p>
          )}
        </WindowPanel>

        {/* ── 5. Tool activity (marketing intelligence) ──────────────── */}
        <div ref={toolActivityRef} style={{ display: "contents" }} />
        <WindowPanel title="tool-activity.log" className="magi-panel magi-s12">
          <h2 className="magi-panel__title">Tool Activity</h2>
          <p className="magi-panel__sub">
            Every tool the agent actually called this run — with real inputs, results and durations.
            {state && state.duplicate_tool_calls > 0 && (
              <> {state.duplicate_tool_calls} duplicate call(s) prevented.</>
            )}
          </p>
          {toolCalls.length === 0 ? (
            <p className="magi-stream__empty">
              No tool calls yet. The agent uses only the tools the evidence justifies.
            </p>
          ) : (
            <div className="magi-tablewrap">
              <table className="magi-table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Status</th>
                    <th>Input / purpose</th>
                    <th>Result</th>
                    <th>Time · Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {toolCalls.map((c, i) => {
                    const spec = catalogByName.get(c.tool);
                    return (
                      <tr key={i}>
                        <td className="magi-table__tool">{c.tool}</td>
                        <td>
                          <span className={`magi-pill magi-pill--${c.ok ? "ok" : "bad"}`}>
                            {c.ok ? "✓ ok" : "✕ failed"}
                          </span>
                        </td>
                        <td className="magi-table__dim" title={spec?.description ?? ""}>
                          {paramsSummary(c.params)}
                        </td>
                        <td>{c.summary ?? (c.ok ? "done" : "failed")}</td>
                        <td className="magi-table__dim">
                          {timeOf(c.ts)}{c.latency_ms ? ` · ${c.latency_ms}ms` : ""}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </WindowPanel>

        {/* ── 3. Research & evidence (agentic RAG) ───────────────────── */}
        <WindowPanel title="research-evidence.notebook" className="magi-panel magi-s6">
          <h2 className="magi-panel__title">Research &amp; Evidence</h2>
          <p className="magi-panel__sub">Multi-step retrieval with sufficiency checks — never a single lookup.</p>
          {run ? (
            <>
              {state?.observations.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">Observations</h3>
                  <ul className="magi-list">
                    {state.observations.map((o, i) => (
                      <li key={i}>{o}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {state?.retrieval_log.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">
                    Agentic RAG — {state.retrieval_log.length} question(s)
                  </h3>
                  {state.retrieval_log.map((r, i) => (
                    <div key={i} className="magi-rag">
                      <div className="magi-rag__q">
                        Q{i + 1}: {r.question}
                      </div>
                      <div className="magi-rag__meta">
                        {r.rounds} retrieval round(s) · {r.retrievals.length} retrievals ·{" "}
                        {r.sufficient ? "evidence sufficient" : "evidence insufficient — reformulated"} ·{" "}
                        {r.strategy}
                      </div>
                      <div className="magi-rag__tools">
                        {r.retrievals.map((rr, j) => (
                          <span key={j} className="magi-tag">
                            {rr.tool} ({rr.item_count})
                          </span>
                        ))}
                      </div>
                      {(r.gaps?.length ?? 0) > 0 && (
                        <div className="magi-rag__gaps">
                          Gaps: {r.gaps.join(" · ")}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : null}

              {state?.hypotheses.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">Hypotheses</h3>
                  {state.hypotheses.map((h, i) => (
                    <div key={i} className="magi-hypo">
                      <span className={`magi-hypo__status magi-hypo__status--${h.status}`}>
                        {h.status}
                      </span>
                      <span className="magi-hypo__text">{h.statement}</span>
                      <span className="magi-hypo__conf">
                        {(h.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}

              {state?.knowledge_gaps.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">Knowledge gaps (honest)</h3>
                  <ul className="magi-list magi-list--gaps">
                    {state.knowledge_gaps.map((g, i) => (
                      <li key={i}>{g}</li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {state?.evidence.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">
                    Evidence ({state.evidence.length})
                  </h3>
                  <ul className="magi-evidence">
                    {state.evidence.slice(0, 12).map((e, i) => (
                      <li key={i}>
                        <span className="magi-tag magi-tag--src">{e.source}</span>
                        <span className="magi-evidence__stmt">{e.statement}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {!state?.observations.length &&
                !state?.retrieval_log.length &&
                !state?.evidence.length && (
                  <p className="magi-stream__empty">No research recorded for this run yet.</p>
                )}
            </>
          ) : (
            <p className="magi-stream__empty">No research yet.</p>
          )}
        </WindowPanel>

        {/* ── 6. Campaign workspace ──────────────────────────────────── */}
        <div ref={campaignRef} style={{ display: "contents" }} />
        <WindowPanel title="campaign-workspace.console" className="magi-panel magi-s6">
          <h2 className="magi-panel__title">Campaign Workspace</h2>
          {!draft && !runCampaign ? (
            <p className="magi-stream__empty">
              No campaign drafted yet. The agent creates one only when evidence justifies it.
            </p>
          ) : (
            <div className="magi-campaign">
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
              <div className="magi-campaign__head">
                <h3 className="magi-campaign__name">
                  {draft?.name ?? runCampaign?.name ?? "Untitled campaign"}
                </h3>
                <StatusChip tone="accent">
                  {draft?.integration_status
                    ? (INTEGRATION_LABELS[draft.integration_status] ?? draft.integration_status)
                    : runCampaign
                      ? (INTEGRATION_LABELS[runCampaign.integration_status] ?? runCampaign.integration_status)
                      : "DRAFT ONLY"}
                </StatusChip>
              </div>
              <dl className="magi-defs">
                <div>
                  <dt>Objective</dt>
                  <dd>{draft?.objective ?? runCampaign?.objective ?? "—"}</dd>
                </div>
                <div>
                  <dt>Audience</dt>
                  <dd>
                    {draft?.audience_count ?? runCampaign?.audience_count ?? 0} customers (real, verified)
                    {audience?.criteria && (
                      <> · criteria: {Object.entries(audience.criteria).map(([k, v]) => `${k}=${String(v)}`).join(", ")}</>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Strategy</dt>
                  <dd>{draft?.workflow ?? runCampaign?.workflow ?? "—"}</dd>
                </div>
                <div>
                  <dt>Message</dt>
                  <dd>{draft?.content?.message ?? (runCampaign?.content as { message?: string } | null)?.message ?? "—"}</dd>
                </div>
                {((draft?.content?.subject_variants?.length ?? 0) > 0 ||
                  ((runCampaign?.content as { subject_variants?: string[] } | null)?.subject_variants?.length ?? 0) > 0) && (
                  <div>
                    <dt>Variants</dt>
                    <dd>
                      {(draft?.content?.subject_variants ??
                        (runCampaign?.content as { subject_variants?: string[] })?.subject_variants ??
                        []).join(" · ")}
                    </dd>
                  </div>
                )}
                <div>
                  <dt>Channel</dt>
                  <dd>{draft?.channel ?? runCampaign?.channel ?? "email"}</dd>
                </div>
                <div>
                  <dt>Timing</dt>
                  <dd>{draft?.content?.timing ?? (runCampaign?.content as { timing?: string } | null)?.timing ?? "—"}</dd>
                </div>
                <div>
                  <dt>Expected impact</dt>
                  <dd>
                    {draft?.expected_impact?.rationale ?? (runCampaign?.expected_impact as { rationale?: string } | null)?.rationale ?? "—"} (
                    {rupees(draft?.expected_impact?.estimated_revenue_inr ?? runCampaign?.estimated_revenue_inr)})
                  </dd>
                </div>
                <div>
                  <dt>Success metric</dt>
                  <dd>{draft?.success_metric ?? runCampaign?.success_metric ?? "—"}</dd>
                </div>
                <div>
                  <dt>Approval state</dt>
                  <dd>{preparedAction ? preparedAction.approval_state : "not requested yet"}</dd>
                </div>
                <div>
                  <dt>Execution state</dt>
                  <dd>
                    {runCampaign?.action_id
                      ? `prepared as action ${runCampaign.action_id.slice(0, 8)}… · lifecycle ${runCampaign.lifecycle.replace(/_/g, " ")}`
                      : "nothing sent — execution requires your approval"}
                  </dd>
                </div>
              </dl>
            </div>
          )}
        </WindowPanel>

        {/* ── Marketing stack (six real integrations) ────────────────── */}
        <WindowPanel title="marketing-stack.tools" className="magi-panel magi-s12">
          <h2 className="magi-panel__title">Marketing Stack</h2>
          <p className="magi-panel__sub">
            Real capability status from the backend tool registry — never claimed from a UI card.
          </p>
          <div className="magi-stack">
            {stack.map((entry) => {
              const act = stackActivity[entry.key] ?? { count: 0, last: null };
              const isInternal = entry.provider === "internal";
              const isConnected = entry.status === "connected";
              const busy = connBusy === entry.provider;
              return (
                <div key={entry.key} className="magi-stackcard">
                  <div className="magi-stackcard__head">
                    <h3 className="magi-stackcard__name">{entry.label}</h3>
                    <span className={`magi-int__status magi-int__status--${entry.status}`}>
                      {entry.status === "connected" && isInternal
                        ? "CONNECTED — INTERNAL"
                        : (INTEGRATION_LABELS[entry.status] ?? entry.status)}
                    </span>
                  </div>
                  <p className="magi-stackcard__desc">{entry.description}</p>
                  <div className="magi-stackcard__meta">
                    <span>{providerDisplay(entry.provider)}</span>
                    {isConnected && entry.account_name && (
                      <span>{entry.account_name}</span>
                    )}
                  </div>
                  {isConnected && (
                    <div className="magi-stackcard__meta">
                      <span>
                        Last verified:{" "}
                        {entry.last_verified_at
                          ? new Date(entry.last_verified_at).toLocaleString("en-IN", { hour12: false })
                          : "—"}
                      </span>
                    </div>
                  )}
                  {(entry.capabilities?.length ?? 0) > 0 && (
                    <div className="magi-stackcard__caps">
                      {entry.capabilities.slice(0, 5).map((c) => (
                        <span key={c} className="magi-tag">{c.replace(/_/g, " ")}</span>
                      ))}
                    </div>
                  )}
                  <div className="magi-stackcard__meta">
                    <span>{act.count} tool call{act.count === 1 ? "" : "s"} this run</span>
                    <span>Last: {act.last ? timeOf(act.last) : "—"}</span>
                  </div>
                  {!isInternal && (
                    <div className="magi-stackcard__actions">
                      {!isConnected && (
                        <button
                          type="button"
                          className="magi-stackcard__btn"
                          disabled={busy}
                          onClick={() => openStackModal(entry.key)}
                        >
                          {entry.key === "email" && "Connect Email →"}
                          {entry.key === "google_ads" && "Connect Google Ads →"}
                          {entry.key === "meta_ads" && "Connect Meta Ads →"}
                          {entry.key === "social" && "Connect Instagram →"}
                        </button>
                      )}
                      {isConnected && (
                        <>
                          <button
                            type="button"
                            className="magi-stackcard__btn"
                            disabled={busy}
                            onClick={() => handleTest(entry.key)}
                          >
                            {busy ? "Testing…" : "Test Connection"}
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
                    </div>
                  )}
                  <button
                    type="button"
                    className="magi-stackcard__btn"
                    onClick={() => openStackModal(entry.key)}
                  >
                    {entry.key === "email" && "View Email Work →"}
                    {entry.key === "google_ads" && "View Google Ads Work →"}
                    {entry.key === "meta_ads" && "View Meta Work →"}
                    {entry.key === "crm" && "View Customer Work →"}
                    {entry.key === "analytics" && "View Analytics →"}
                    {entry.key === "social" && "View Social Work →"}
                  </button>
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

        {/* ── 7. Verification ────────────────────────────────────────── */}
        <WindowPanel title="verification.report" className="magi-panel magi-s4">
          <h2 className="magi-panel__title">Verification</h2>
          {!verification ? (
            <p className="magi-stream__empty">Nothing verified yet.</p>
          ) : (
            <>
              <div className={`magi-verify magi-verify--${verification.passed ? "pass" : "fail"}`}>
                {verification.passed ? "VERIFICATION PASSED" : "VERIFICATION FAILED"}
              </div>
              <ul className="magi-checks">
                {verification.checks.map((c) => (
                  <li
                    key={c.name}
                    className={`magi-checks__item magi-checks__item--${c.passed ? "ok" : "bad"}`}
                  >
                    <span className="magi-checks__mark">
                      {c.passed ? "✓" : "✕"}
                    </span>
                    <span className="magi-checks__name">{c.name.replace(/_/g, " ")}</span>
                    <span className="magi-checks__detail">{c.detail}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </WindowPanel>

        {/* ── 8. Approval / action ───────────────────────────────────── */}
        <WindowPanel title="approval-action.gate" className="magi-panel magi-s4" tone="navy" dark>
          <h2 className="magi-panel__title">Approval</h2>
          {!preparedAction ? (
            <>
              <p className="magi-approval__state">NOTHING TO APPROVE</p>
              <p className="magi-stream__empty">
                No action prepared. The agent proposes; only you approve.
              </p>
            </>
          ) : (
            <div className="magi-action">
              <p className="magi-approval__state magi-approval__state--ready">READY FOR APPROVAL</p>
              <div className="magi-action__row">
                <span className="magi-action__label">Campaign</span>
                <span className="magi-action__value">
                  prepared for {draft?.audience_count ?? runCampaign?.audience_count ?? "?"} customers
                </span>
              </div>
              <div className="magi-action__row">
                <span className="magi-action__label">Action</span>
                <span className="magi-action__value">send_campaign</span>
              </div>
              <div className="magi-action__row">
                <span className="magi-action__label">Action ID</span>
                <span className="magi-action__value mono">{preparedAction.action_id}</span>
              </div>
              <div className="magi-action__row">
                <span className="magi-action__label">Approval</span>
                <span className="magi-action__value magi-action__value--warn">
                  REQUIRED — the agent can never approve its own work
                </span>
              </div>
              <Button variant="primary" mono onClick={() => navigate("/actions")}>
                Review in Actions →
              </Button>
            </div>
          )}
        </WindowPanel>

        {/* ── 9. Learning ────────────────────────────────────────────── */}
        <WindowPanel title="learning.log" className="magi-panel magi-s4">
          <h2 className="magi-panel__title">Learning</h2>
          {learnings.length === 0 && (
            <p className="magi-stream__empty">
              No measured outcomes yet. Learnings appear after approved
              campaigns run and real results come in.
            </p>
          )}
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
        </WindowPanel>

        {/* ── Run history ────────────────────────────────────────────── */}
        <WindowPanel title="runs.history" className="magi-panel magi-s5">
          <h2 className="magi-panel__title">Runs</h2>
          {runs.length === 0 && (
            <p className="magi-stream__empty">No autonomous runs yet.</p>
          )}
          <ul className="magi-runs">
            {runs.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  className={`magi-run ${run?.id === r.id ? "magi-run--active" : ""}`}
                  onClick={() => selectRun(r.id)}
                >
                  <span className={`magi-run__status magi-run__status--${r.status}`}>
                    {RUN_STATUS_LABELS[r.status] ?? r.status}
                  </span>
                  <span className="magi-run__objective">{r.objective}</span>
                  <span className="magi-run__meta">
                    {r.iterations} iter · {r.tool_call_count} tools
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </WindowPanel>

        {/* ── Campaign drafts ────────────────────────────────────────── */}
        <WindowPanel title="campaigns.drafts" className="magi-panel magi-s7">
          <h2 className="magi-panel__title">Campaign Drafts ({campaigns.length})</h2>
          {campaigns.length === 0 ? (
            <p className="magi-stream__empty">
              No drafts yet — drafts appear here with their real lifecycle and approval state.
            </p>
          ) : (
            <div className="magi-cards">
              {campaigns.map((c) => (
                <div key={c.id} className="magi-card">
                  <div className="magi-card__head">
                    <h3 className="magi-card__name">{c.name}</h3>
                    <span className={`magi-int__status magi-int__status--${c.integration_status}`}>
                      {INTEGRATION_LABELS[c.integration_status] ?? c.integration_status}
                    </span>
                  </div>
                  <p className="magi-card__obj">{c.objective}</p>
                  <div className="magi-card__meta">
                    <span>{c.audience_count} customers</span>
                    <span>{rupees(c.estimated_revenue_inr)} expected</span>
                    <span className={`magi-run__status magi-run__status--${c.lifecycle}`}>
                      {c.lifecycle.replace(/_/g, " ")}
                    </span>
                  </div>
                  {c.action_id && (
                    <p className="magi-card__action">
                      Action {c.action_id.slice(0, 8)}… awaiting your approval in
                      Growth Actions.{" "}
                      <button
                        type="button"
                        className="magi-linkbtn"
                        onClick={() => navigate("/actions")}
                      >
                        Review →
                      </button>
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </WindowPanel>
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
                <strong>Internal.</strong> This tool runs on your workspace's own
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
