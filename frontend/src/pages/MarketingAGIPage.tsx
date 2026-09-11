/**
 * /marketing-agi — Marketing AGI workstation.
 *
 * The console for the autonomous marketing employee. Every pixel is
 * driven by REAL agent execution state polled from the backend:
 * status, objective, live workstream (real events), research evidence,
 * marketing intelligence, campaign workspace, verification, prepared
 * action, and learning history. No decorative fake animations.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchMarketingAGIStatus,
  fetchMarketingAGIRuns,
  fetchMarketingAGIRun,
  fetchMarketingAGIEvents,
  startMarketingAGIRun,
  cancelMarketingAGIRun,
  fetchMarketingAGICampaigns,
  fetchMarketingAGILearnings,
  fetchMarketingAGIHandoffs,
} from "../lib/api";
import type {
  MarketingAGIStatus,
  MarketingAGIRun,
  MarketingAGIRunEvent,
  MarketingAGICampaign,
  MarketingAGILearning,
  MarketingAGIHandoff,
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

const STATUS_LABELS: Record<string, string> = {
  queued: "IDLE",
  running: "WORKING",
  waiting_approval: "READY FOR APPROVAL",
  completed: "COMPLETED",
  blocked: "BLOCKED",
  failed: "FAILED",
  cancelled: "CANCELLED",
};

const PHASE_LABELS: Record<string, string> = {
  load_context: "LOADING CONTEXT",
  observe: "OBSERVING BUSINESS",
  investigate: "INVESTIGATING",
  plan: "PLANNING",
  create: "CREATING WORK",
  verify: "VERIFYING",
  prepare: "PREPARING ACTION",
  awaiting_approval: "AWAITING APPROVAL",
  complete: "COMPLETE",
};

const INTEGRATION_LABELS: Record<string, string> = {
  connected: "CONNECTED",
  draft_only: "DRAFT ONLY",
  requires_integration: "REQUIRES INTEGRATION",
};

function statusChipTone(status: string): "neutral" | "ok" | "accent" {
  if (status === "waiting_approval") return "accent";
  if (status === "completed") return "ok";
  return "neutral";
}

function rupees(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/* ── Component ───────────────────────────────────────────────────────── */

export function MarketingAGIPage() {
  const [status, setStatus] = useState<MarketingAGIStatus | null>(null);
  const [runs, setRuns] = useState<MarketingAGIRun[]>([]);
  const [activeRun, setActiveRun] = useState<MarketingAGIRun | null>(null);
  const [events, setEvents] = useState<MarketingAGIRunEvent[]>([]);
  const [campaigns, setCampaigns] = useState<MarketingAGICampaign[]>([]);
  const [learnings, setLearnings] = useState<MarketingAGILearning[]>([]);
  const [handoffs, setHandoffs] = useState<MarketingAGIHandoff[]>([]);
  const [starting, setStarting] = useState(false);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "login_required" | "no_workspace" | "error">("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const lastSeqRef = useRef(0);
  const pollRef = useRef<number | null>(null);

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
        const [st, rs, cs, ls, hs] = await Promise.all([
          fetchMarketingAGIStatus(),
          fetchMarketingAGIRuns(),
          fetchMarketingAGICampaigns(),
          fetchMarketingAGILearnings(),
          fetchMarketingAGIHandoffs(),
        ]);
        setStatus(st);
        setRuns(rs.runs);
        setCampaigns(cs.campaigns);
        setLearnings(ls.learnings);
        setHandoffs(hs.handoffs);
        if (withActiveRun) {
          const running = rs.runs.find((r) => ACTIVE_STATUSES.has(r.status));
          const focus = running ?? rs.runs[0] ?? null;
          setActiveRun(focus);
          lastSeqRef.current = 0;
          setEvents([]);
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

  /* live polling while a run is active */
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

  /* actions */
  const handleStart = async () => {
    setStarting(true);
    try {
      await startMarketingAGIRun();
      await loadAll();
      setEvents([]);
      lastSeqRef.current = 0;
    } catch (e) {
      setErrorMsg((e as Error).message ?? "Could not start the agent");
    } finally {
      setStarting(false);
    }
  };

  const handleCancel = async () => {
    if (!activeRun) return;
    try {
      await cancelMarketingAGIRun(activeRun.id);
    } catch {
      /* cooperative cancel may race the loop finishing */
    }
  };

  const selectRun = async (runId: string) => {
    stopPolling();
    setEvents([]);
    lastSeqRef.current = 0;
    try {
      const run = await fetchMarketingAGIRun(runId);
      setActiveRun(run);
      if (ACTIVE_STATUSES.has(run.status)) {
        pollRef.current = window.setInterval(() => pollActiveRun(runId), 1500);
      }
    } catch {
      /* ignore */
    }
  };

  /* ── render ────────────────────────────────────────────────────────── */

  if (loadState === "loading") {
    return (
      <div className="magi-page">
        <p className="magi-loading">Loading Marketing AGI workstation…</p>
      </div>
    );
  }

  if (loadState === "login_required") {
    return (
      <div className="magi-page">
        <WindowPanel title="marketing-agi.app" className="magi-banner">
          <h1 className="magi-title">Marketing AGI</h1>
          <p className="magi-lead">
            Log in to put the autonomous marketing employee to work on your business.
          </p>
        </WindowPanel>
      </div>
    );
  }

  if (loadState === "no_workspace") {
    return (
      <div className="magi-page">
        <WindowPanel title="marketing-agi.app" className="magi-banner">
          <h1 className="magi-title">Marketing AGI</h1>
          <p className="magi-lead">
            Your account has no merchant workspace yet. Sign up creates one automatically.
          </p>
        </WindowPanel>
      </div>
    );
  }

  const run = activeRun;
  const live = run !== null && ACTIVE_STATUSES.has(run.status);
  const phaseLabel = run ? (PHASE_LABELS[run.phase] ?? run.phase) : null;
  const state = run?.state;
  const draft = state?.campaign_draft as
    | {
        name?: string;
        objective?: string;
        audience_count?: number;
        workflow?: string;
        content?: { message?: string; subject_variants?: string[]; cta?: string; timing?: string };
        expected_impact?: { rationale?: string; estimated_revenue_inr?: number };
        success_metric?: string;
        integration_status?: string;
      }
    | null
    | undefined;
  const verification = state?.verification;
  const preparedAction = state?.prepared_action;

  return (
    <div className="magi-page">
      {/* ── Banner ─────────────────────────────────────────────────── */}
      <WindowPanel title="marketing-agi.app" className="magi-banner">
        <div className="magi-banner__row">
          <div>
            <h1 className="magi-title">Marketing AGI</h1>
            <p className="magi-lead">
              An autonomous marketing employee. It investigates your real business
              data, decides what marketing work matters, prepares the campaign, and
              waits for your approval — never acting on customers without you.
            </p>
          </div>
          <div className="magi-banner__actions">
            <Button
              variant="primary"
              mono
              onClick={handleStart}
              disabled={starting || live}
            >
              {starting ? "Starting…" : live ? "Agent working…" : "Put the AGI to work"}
            </Button>
            {live && (
              <Button variant="secondary" mono onClick={handleCancel}>
                Cancel
              </Button>
            )}
          </div>
        </div>

        <div className="magi-meta">
          <StatusChip
            tone={run ? statusChipTone(run.status) : "neutral"}
            pulse={live}
          >
            {run ? (STATUS_LABELS[run.status] ?? run.status) : "IDLE"}
          </StatusChip>
          {phaseLabel && <span className="magi-meta__phase">{phaseLabel}</span>}
          {status && (
            <span className="magi-meta__item">
              {status.llm_configured
                ? `Reasoning: ${status.llm_model ?? status.llm_provider}`
                : "Reasoning: deterministic (no LLM key)"}
            </span>
          )}
          {run && (
            <span className="magi-meta__item">
              {run.tool_call_count} tool calls · {run.iterations} iterations
            </span>
          )}
        </div>

        {errorMsg && <p className="magi-error">{errorMsg}</p>}
      </WindowPanel>

      <div className="magi-grid">
        {/* ── Live workstream ─────────────────────────────────────── */}
        <WindowPanel title="workstream.log" className="magi-panel magi-workstream">
          <h2 className="magi-panel__title">Live Workstream</h2>
          <p className="magi-panel__sub">Real execution events — nothing simulated.</p>
          <div className="magi-stream">
            {events.length === 0 && !live && (
              <p className="magi-stream__empty">
                {run
                  ? "Select a run to view its workstream, or start the agent."
                  : "The agent hasn't worked on this business yet."}
              </p>
            )}
            {events.map((e) => (
              <div key={e.id} className={`magi-evt magi-evt--${e.event_type}`}>
                <span className="magi-evt__seq">
                  {String(e.seq).padStart(2, "0")}
                </span>
                <span className="magi-evt__msg">{e.message}</span>
              </div>
            ))}
            {live && (
              <div className="magi-evt magi-evt--live">
                <span className="magi-evt__seq">··</span>
                <span className="magi-evt__msg">{phaseLabel}…</span>
              </div>
            )}
          </div>
        </WindowPanel>

        {/* ── Current objective + research ────────────────────────── */}
        <WindowPanel title="research.notebook" className="magi-panel" tone="navy" dark>
          <h2 className="magi-panel__title">Research</h2>
          {run ? (
            <>
              <p className="magi-objective">{run.objective}</p>

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

              {state?.hypotheses.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">Hypotheses</h3>
                  {state.hypotheses.map((h, i) => (
                    <div key={i} className="magi-hypo">
                      <span
                        className={`magi-hypo__status magi-hypo__status--${h.status}`}
                      >
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

              {state?.retrieval_log.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">Agentic RAG</h3>
                  {state.retrieval_log.map((r, i) => (
                    <div key={i} className="magi-rag">
                      <div className="magi-rag__q">{r.question}</div>
                      <div className="magi-rag__meta">
                        {r.rounds} rounds · {r.retrievals.length} retrievals ·{" "}
                        {r.sufficient ? "sufficient" : "insufficient"} ·{" "}
                        {r.strategy}
                      </div>
                      <div className="magi-rag__tools">
                        {r.retrievals.map((rr, j) => (
                          <span key={j} className="magi-tag">
                            {rr.tool} ({rr.item_count})
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}

              {state?.knowledge_gaps.length ? (
                <div className="magi-block">
                  <h3 className="magi-block__title">Knowledge Gaps (honest)</h3>
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
                    {state.evidence.slice(0, 10).map((e, i) => (
                      <li key={i}>
                        <span className="magi-tag magi-tag--src">{e.source}</span>
                        <span className="magi-evidence__stmt">{e.statement}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : (
            <p className="magi-stream__empty">No research yet.</p>
          )}
        </WindowPanel>

        {/* ── Campaign workspace ──────────────────────────────────── */}
        <WindowPanel title="campaign.workspace" className="magi-panel">
          <h2 className="magi-panel__title">Campaign Workspace</h2>
          {!draft && (
            <p className="magi-stream__empty">
              No campaign drafted yet. The agent creates one only when evidence
              justifies it.
            </p>
          )}
          {draft && (
            <div className="magi-campaign">
              <div className="magi-campaign__head">
                <h3 className="magi-campaign__name">{draft.name}</h3>
                <StatusChip tone="accent">
                  {draft.integration_status
                    ? (INTEGRATION_LABELS[draft.integration_status] ?? draft.integration_status)
                    : "DRAFT ONLY"}
                </StatusChip>
              </div>
              <dl className="magi-defs">
                <div>
                  <dt>Objective</dt>
                  <dd>{draft.objective}</dd>
                </div>
                <div>
                  <dt>Audience</dt>
                  <dd>{draft.audience_count} customers (real, verified)</dd>
                </div>
                <div>
                  <dt>Strategy</dt>
                  <dd>{draft.workflow}</dd>
                </div>
                <div>
                  <dt>Message</dt>
                  <dd>{draft.content?.message}</dd>
                </div>
                {!!draft.content?.subject_variants?.length && (
                  <div>
                    <dt>Variants</dt>
                    <dd>{draft.content.subject_variants.join(" · ")}</dd>
                  </div>
                )}
                <div>
                  <dt>CTA</dt>
                  <dd>{draft.content?.cta}</dd>
                </div>
                <div>
                  <dt>Timing</dt>
                  <dd>{draft.content?.timing}</dd>
                </div>
                <div>
                  <dt>Expected impact</dt>
                  <dd>
                    {draft.expected_impact?.rationale} (
                    {rupees(draft.expected_impact?.estimated_revenue_inr)})
                  </dd>
                </div>
                <div>
                  <dt>Success metric</dt>
                  <dd>{draft.success_metric}</dd>
                </div>
              </dl>
            </div>
          )}
        </WindowPanel>

        {/* ── Verification ───────────────────────────────────────── */}
        <WindowPanel title="verification.report" className="magi-panel">
          <h2 className="magi-panel__title">Verification</h2>
          {!verification && (
            <p className="magi-stream__empty">Nothing verified yet.</p>
          )}
          {verification && (
            <>
              <div className={`magi-verify magi-verify--${verification.passed ? "pass" : "fail"}`}>
                {verification.passed ? "PASSED" : "FAILED"}
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
                    <span className="magi-checks__name">{c.name}</span>
                    <span className="magi-checks__detail">{c.detail}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </WindowPanel>

        {/* ── Action ──────────────────────────────────────────────── */}
        <WindowPanel title="action.review" className="magi-panel" tone="navy" dark>
          <h2 className="magi-panel__title">Prepared Action</h2>
          {!preparedAction && (
            <p className="magi-stream__empty">
              No action prepared. The AGI proposes; only you approve.
            </p>
          )}
          {preparedAction && (
            <div className="magi-action">
              <div className="magi-action__row">
                <span className="magi-action__label">Action</span>
                <span className="magi-action__value">send_campaign (email)</span>
              </div>
              <div className="magi-action__row">
                <span className="magi-action__label">Action ID</span>
                <span className="magi-action__value mono">{preparedAction.action_id}</span>
              </div>
              <div className="magi-action__row">
                <span className="magi-action__label">Approval</span>
                <span className="magi-action__value magi-action__value--warn">
                  REQUIRED — the AGI can never approve its own work
                </span>
              </div>
              <p className="magi-action__note">
                Approve or reject from the Growth Actions console — this agent
                structurally cannot.
              </p>
            </div>
          )}
        </WindowPanel>

        {/* ── Marketing intelligence ──────────────────────────────── */}
        <WindowPanel title="intelligence.deck" className="magi-panel">
          <h2 className="magi-panel__title">Marketing Intelligence</h2>
          {state?.tool_calls?.length ? (
            <>
              <p className="magi-panel__sub">
                Tools the agent actually used this run ({state.tool_calls.length}).
              </p>
              <div className="magi-tools">
                {state.tool_calls.map((c, i) => (
                  <span key={i} className="magi-tag magi-tag--tool">
                    {c.tool}
                    {c.latency_ms ? ` · ${c.latency_ms}ms` : ""}
                  </span>
                ))}
              </div>
              {state.duplicate_tool_calls > 0 && (
                <p className="magi-note">
                  {state.duplicate_tool_calls} duplicate tool call(s) prevented.
                </p>
              )}
            </>
          ) : (
            <p className="magi-stream__empty">
              The agent uses only the tools the evidence justifies.
            </p>
          )}
          {status && (
            <div className="magi-integrations">
              <h3 className="magi-block__title">Integrations (honest)</h3>
              {Object.entries(status.integration_status).map(([k, v]) => (
                <div key={k} className="magi-int">
                  <span className="magi-int__name">{k.replace(/_/g, " ")}</span>
                  <span
                    className={`magi-int__status magi-int__status--${v}`}
                  >
                    {INTEGRATION_LABELS[v] ?? v}
                  </span>
                </div>
              ))}
            </div>
          )}
        </WindowPanel>

        {/* ── Learning ────────────────────────────────────────────── */}
        <WindowPanel title="learning.log" className="magi-panel">
          <h2 className="magi-panel__title">Learning</h2>
          {learnings.length === 0 && (
            <p className="magi-stream__empty">
              No measured campaign outcomes yet. Learnings appear after approved
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
              <h3 className="magi-block__title">Specialist Handoffs</h3>
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

        {/* ── Run history ─────────────────────────────────────────── */}
        <WindowPanel title="runs.history" className="magi-panel">
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
                    {STATUS_LABELS[r.status] ?? r.status}
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
      </div>

      {/* ── Campaign drafts (all runs) ─────────────────────────────── */}
      {campaigns.length > 0 && (
        <WindowPanel title="campaigns.drafts" className="magi-panel magi-campaigns-panel">
          <h2 className="magi-panel__title">Campaign Drafts</h2>
          <div className="magi-cards">
            {campaigns.map((c) => (
              <div key={c.id} className="magi-card">
                <div className="magi-card__head">
                  <h3 className="magi-card__name">{c.name}</h3>
                  <span
                    className={`magi-int__status magi-int__status--${c.integration_status}`}
                  >
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
                    Growth Actions.
                  </p>
                )}
              </div>
            ))}
          </div>
        </WindowPanel>
      )}
    </div>
  );
}
