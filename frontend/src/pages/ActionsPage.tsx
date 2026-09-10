/**
 * /actions — Growth Actions console.
 *
 * Dashboard design adapted from the munder-difflin-main workflow board
 * (TasksKanban + TaskDetail overlay + TriggerHistoryTab approval cards):
 * a status-column board with accent-edged cards, a KPI strip, a detail
 * overlay per action, and approve / reject / run controls inline.
 *
 * All data comes from the existing actions APIs. Nothing is fabricated.
 * MERCHANT LANGUAGE ONLY — no API endpoints, enums, or developer terms.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchActions,
  approveAction,
  rejectAction,
  executeAction,
  fetchActionAudit,
} from "../lib/api";
import type { AgentAction, AuditEventRow, ExecutionResponse } from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import "./ActionsPage.css";

/* ── Formatting helpers ────────────────────────────────────────────────── */

function rupees(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `₹${value.toFixed(2)}`;
}

function timeOf(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const mins = Math.round((Date.now() - t) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/* ── Plain-English translation of action types (no enums shown) ─────────── */

interface ActionCopy {
  title: string;
  what: string;
  willDo: string[];
  wontDo: string[];
}

const ACTION_COPY: Record<string, ActionCopy> = {
  retry_payment: {
    title: "Payment Recovery",
    what: "The AI team identified an unsuccessful payment and proposes a single, carefully retried payment attempt for that customer.",
    willDo: [
      "Retry exactly the one unsuccessful payment listed below",
      "Record the outcome — success or failure — in the audit trail",
    ],
    wontDo: [
      "Charge any other customer",
      "Change the payment amount",
      "Retry a second time automatically",
    ],
  },
  send_campaign: {
    title: "Customer Campaign",
    what: "The AI team proposes a marketing campaign to a selected group of customers.",
    willDo: [
      "Run one campaign to the selected customer group",
      "Stay within the campaign audience limit configured for this workspace",
    ],
    wontDo: [
      "Contact customers outside the selected group",
      "Send more than the approved number of messages",
      "Charge any customer money",
    ],
  },
  create_discount: {
    title: "Discount Offer",
    what: "The AI team proposes a discount offer to encourage purchases.",
    willDo: [
      "Create one discount offer within the allowed percentage limit",
      "Record the discount in the audit trail",
    ],
    wontDo: [
      "Exceed the maximum discount configured for this workspace",
      "Apply the discount to individual customers automatically",
    ],
  },
  generate_opportunity: {
    title: "New Opportunity",
    what: "The AI team proposes recording a new growth opportunity for review.",
    willDo: [
      "Record the opportunity for review and approval",
      "Attach it to the growth opportunity list",
    ],
    wontDo: [
      "Contact any customer",
      "Move any money",
    ],
  },
};

function actionCopy(type: string): ActionCopy {
  return (
    ACTION_COPY[type] ?? {
      title: type.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      what: "The AI team proposed this action from your real business data.",
      willDo: ["Execute exactly the reviewed action"],
      wontDo: ["Take any step beyond what is described here"],
    }
  );
}

/* ── Status presentation ───────────────────────────────────────────────── */

function statusLabel(status: string): string {
  switch (status) {
    case "requested": return "Waiting for approval";
    case "approved": return "Approved";
    case "rejected": return "Rejected";
    case "executing": return "Running";
    case "completed": return "Completed";
    case "failed": return "Failed";
    default: return status;
  }
}

function statusTone(status: string): string {
  switch (status) {
    case "requested": return "waiting";
    case "approved": return "approved";
    case "rejected": return "rejected";
    case "executing": return "running";
    case "completed": return "done";
    case "failed": return "failed";
    default: return "waiting";
  }
}

/** Board column definition — adapted from the reference kanban's COLUMNS. */
const BOARD_COLUMNS: Array<{
  key: string;
  label: string;
  accent: string;
  statuses: string[];
}> = [
  { key: "awaiting", label: "Awaiting approval", accent: "awaiting", statuses: ["requested"] },
  { key: "approved", label: "Approved", accent: "approved", statuses: ["approved"] },
  { key: "running", label: "Running", accent: "running", statuses: ["executing"] },
  { key: "completed", label: "Completed", accent: "completed", statuses: ["completed"] },
  { key: "stopped", label: "Stopped", accent: "stopped", statuses: ["rejected", "failed"] },
];

/* ── Expected impact — derived from real payload values only ────────────── */

/** Money involved in the action, from the real payload. */
function amountOf(action: AgentAction): number | null {
  const input = action.input_payload ?? {};
  const meta = (input.metadata ?? {}) as Record<string, unknown>;
  if (typeof meta.amount_inr === "number") return meta.amount_inr;
  if (action.action_type === "create_discount" && typeof input.proposed_amount === "number") {
    return input.proposed_amount;
  }
  return null;
}

/** Audience size for campaigns, from the real payload. */
function audienceOf(action: AgentAction): number | null {
  const input = action.input_payload ?? {};
  return typeof input.target_count === "number" ? input.target_count : null;
}

/** 1–5 impact meter (reference PriorityDots) over the real money involved. */
function impactLevel(amount: number | null): number {
  if (amount === null || amount <= 0) return 0;
  if (amount >= 5000) return 5;
  if (amount >= 2000) return 4;
  if (amount >= 1000) return 3;
  if (amount >= 250) return 2;
  return 1;
}

function impactTooltip(action: AgentAction): string {
  const amount = amountOf(action);
  if (amount !== null) return `Expected impact: up to ${rupees(amount)}`;
  const audience = audienceOf(action);
  if (audience !== null) return `Expected impact: ${audience} selected customers`;
  return "No monetary impact recorded for this action";
}

/* ── Audit trail: translate event types into merchant language ──────────── */

interface AuditStepView {
  title: string;
  detail: string;
  actor: "ai" | "human" | "system";
}

const AUDIT_COPY: Record<string, { title: string; detail: string }> = {
  action_requested: {
    title: "AI prepared the action",
    detail: "The AI team created this action and requested merchant approval.",
  },
  action_approved: {
    title: "Merchant approved",
    detail: "A merchant user approved this action. Execution could now begin.",
  },
  action_rejected: {
    title: "Merchant rejected",
    detail: "A merchant user rejected this action. Nothing was executed.",
  },
  action_started: {
    title: "Execution started",
    detail: "The approved action began running.",
  },
  action_completed: {
    title: "Execution completed",
    detail: "The action finished. Its result is recorded below.",
  },
  action_failed: {
    title: "Execution failed safely",
    detail: "The action could not complete. It stopped safely and no unauthorized action was taken.",
  },
  action_skipped_idempotent: {
    title: "Duplicate run blocked",
    detail: "The action had already run — the repeat attempt was ignored.",
  },
  opportunity_created: {
    title: "Opportunity detected",
    detail: "The AI team identified this growth opportunity from real business data.",
  },
  payment_created: {
    title: "Payment recorded",
    detail: "A payment record was created.",
  },
  payment_succeeded: {
    title: "Payment succeeded",
    detail: "The TEST payment completed successfully.",
  },
  payment_failed: {
    title: "Payment could not be completed",
    detail: "The payment attempt failed. No money was captured.",
  },
};

function auditStep(event: AuditEventRow): AuditStepView {
  const copy = AUDIT_COPY[event.event_type] ?? {
    title: event.event_type.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    detail: "Recorded by the system.",
  };
  const actor: AuditStepView["actor"] =
    event.actor_type === "merchant_user"
      ? "human"
      : event.actor_type === "ai_agent"
        ? "ai"
        : "system";
  return { title: copy.title, detail: copy.detail, actor };
}

/* ── Payload → plain English (per action type, real values only) ────────── */

interface PayloadView {
  actionLine: string;
  scopeLine: string;
  amountLine: string | null;
}

function payloadView(action: AgentAction): PayloadView {
  const input = action.input_payload ?? {};
  const meta = (input.metadata ?? {}) as Record<string, unknown>;
  const amount = typeof meta.amount_inr === "number" ? meta.amount_inr : null;

  switch (action.action_type) {
    case "retry_payment": {
      const paymentId = typeof input.payment_id === "string" ? input.payment_id : null;
      return {
        actionLine: paymentId
          ? `Retry one unsuccessful payment (reference ${paymentId}).`
          : "Retry one unsuccessful payment.",
        scopeLine: "Exactly one customer and one previously failed payment.",
        amountLine: amount !== null ? `Up to ${rupees(amount)} — the original payment amount.` : null,
      };
    }
    case "send_campaign": {
      const count = typeof input.target_count === "number" ? input.target_count : null;
      const type = typeof input.campaign_type === "string" ? input.campaign_type : "campaign";
      return {
        actionLine: `Run a ${type.replace(/[_-]+/g, " ")} campaign${count !== null ? ` to ${count} selected customer${count === 1 ? "" : "s"}` : ""}.`,
        scopeLine:
          count !== null
            ? `Only the ${count} selected customer${count === 1 ? "" : "s"} in the target group.`
            : "Only the selected customer group.",
        amountLine: null,
      };
    }
    case "create_discount": {
      const pct = typeof input.percentage === "number" ? input.percentage : null;
      return {
        actionLine: pct !== null ? `Create a ${pct}% discount offer.` : "Create a discount offer.",
        scopeLine: "Applies as a general offer — no customer is charged.",
        amountLine:
          typeof input.proposed_amount === "number"
            ? `Up to ${rupees(input.proposed_amount)} in discount value.`
            : null,
      };
    }
    default:
      return {
        actionLine: "The recorded action as described above.",
        scopeLine: "Only what is described in this action.",
        amountLine: amount !== null ? `Up to ${rupees(amount)}.` : null,
      };
  }
}

/* ── Small presentational pieces (adapted from the reference) ───────────── */

/** Impact meter — reference PriorityDots, driven by the real money involved. */
function ImpactDots({ action }: { action: AgentAction }) {
  const level = impactLevel(amountOf(action));
  const title = impactTooltip(action);
  if (level === 0) {
    return (
      <span className="impact-dots impact-dots--none" title={title}>
        no money involved
      </span>
    );
  }
  const color = level >= 4 ? "var(--coral-strong)" : level === 3 ? "var(--act-amber-deep)" : "var(--green-deep)";
  return (
    <span className="impact-dots" title={title} aria-label={title}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span
          key={i}
          className="impact-dot"
          style={{
            background: i <= level ? color : "var(--paper-deep)",
            boxShadow: "inset 0 0 0 1px var(--line-soft)",
          }}
        />
      ))}
    </span>
  );
}

/** One board card — reference TaskCard: accent edge, id, title, hint of detail. */
function BoardCard({
  action,
  accent,
  onOpen,
  onApprove,
  onReject,
  onRun,
  busy,
  result,
}: {
  action: AgentAction;
  accent: string;
  onOpen: () => void;
  onApprove: () => void;
  onReject: () => void;
  onRun: () => void;
  busy: boolean;
  result: ExecutionResponse | undefined;
}) {
  const copy = actionCopy(action.action_type);
  const audience = audienceOf(action);
  return (
    <div className={`board-card board-card--${accent}`}>
      <button type="button" className="board-card__main" onClick={onOpen} title="Open action details">
        <span className={`board-card__edge board-card__edge--${accent}`} aria-hidden="true" />
        <span className="board-card__body">
          <span className="board-card__id">{action.id}</span>
          <span className="board-card__title">{copy.title}</span>
          <span className="board-card__facts">
            <ImpactDots action={action} />
            {audience !== null && (
              <span className="board-card__audience">{audience} customers</span>
            )}
          </span>
          <span className="board-card__time">{relTime(action.created_at)}</span>
        </span>
        {action.status === "requested" && (
          <span className="board-card__you">needs you</span>
        )}
      </button>
      {/* Controls render as siblings (never nested buttons) — reference pattern. */}
      {action.status === "requested" && (
        <div className="board-card__controls">
          <Button variant="primary" mono size="sm" disabled={busy} onClick={onApprove}>
            {busy ? "Saving…" : "Approve"}
          </Button>
          <Button variant="secondary" mono size="sm" disabled={busy} onClick={onReject}>
            Reject
          </Button>
        </div>
      )}
      {action.status === "approved" && (
        <div className="board-card__controls">
          <Button variant="primary" mono size="sm" disabled={busy} onClick={onRun}>
            {busy ? "Running…" : "Run now"}
          </Button>
        </div>
      )}
      {action.status === "executing" && (
        <div className="board-card__controls">
          <span className="action-status action-status--running">
            <span className="action-status__dot" aria-hidden="true" />
            Running…
          </span>
        </div>
      )}
      {(action.status === "failed" || action.status === "rejected") && (
        <div className="board-card__controls">
          <span className={`action-status action-status--${statusTone(action.status)}`}>
            <span className="action-status__dot" aria-hidden="true" />
            {statusLabel(action.status)}
          </span>
        </div>
      )}
      {result && (
        <div className={`board-card__result${result.status === "failed" ? " board-card__result--failure" : ""}`}>
          {result.message}
        </div>
      )}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

type Tab = "waiting" | "approved" | "completed" | "all";

interface ActivityItem {
  kind: string;
  accent: "awaiting" | "completed" | "failed";
  text: string;
  at: string | null;
}

export function ActionsPage() {
  const navigate = useNavigate();
  const [actions, setActions] = useState<AgentAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ExecutionResponse>>({});
  const [audits, setAudits] = useState<Record<string, AuditEventRow[]>>({});
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await fetchActions();
      setActions(data.actions ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load actions");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /* Close the overlay on Escape — reference detail-overlay behavior. */
  useEffect(() => {
    if (!openId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openId]);

  /* Filtering — the original tab semantics, preserved exactly. */
  const visible = (actions ?? []).filter((a) => {
    if (tab === "all") return true;
    if (tab === "waiting") return a.status === "requested";
    if (tab === "approved") return a.status === "approved" || a.status === "executing";
    return a.status === "completed" || a.status === "failed";
  });

  const all = actions ?? [];
  const waitingCount = all.filter((a) => a.status === "requested").length;
  const inFlightCount = all.filter((a) => a.status === "approved" || a.status === "executing").length;
  const completedCount = all.filter((a) => a.status === "completed").length;
  const failedCount = all.filter((a) => a.status === "failed").length;
  const atStake = all
    .filter((a) => a.status === "requested")
    .reduce((sum, a) => sum + (amountOf(a) ?? 0), 0);

  /* Priority order for the awaiting column: highest expected impact first. */
  const byPriority = (a: AgentAction, b: AgentAction) => {
    const la = impactLevel(amountOf(a));
    const lb = impactLevel(amountOf(b));
    if (la !== lb) return lb - la;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  };

  /* Recent activity — derived only from real timestamps on the records. */
  const activity: ActivityItem[] = all
    .flatMap<ActivityItem>((a) => {
      const copy = actionCopy(a.action_type);
      const items: ActivityItem[] = [
        { kind: "proposed", accent: "awaiting", text: `AI team prepared "${copy.title}"`, at: a.created_at },
      ];
      if (a.completed_at) {
        items.push(
          a.status === "failed"
            ? { kind: "failed", accent: "failed", text: `"${copy.title}" could not complete — stopped safely`, at: a.completed_at }
            : { kind: "completed", accent: "completed", text: `"${copy.title}" finished running`, at: a.completed_at },
        );
      }
      return items;
    })
    .filter((i) => i.at !== null)
    .sort((x, y) => new Date(y.at ?? 0).getTime() - new Date(x.at ?? 0).getTime())
    .slice(0, 8);

  /* Approve / reject / execute — existing APIs, unchanged. */
  const handle = async (action: AgentAction, op: "approve" | "reject" | "execute") => {
    setBusyId(action.id);
    setError(null);
    try {
      if (op === "approve") {
        await approveAction(action.id);
      } else if (op === "reject") {
        await rejectAction(action.id);
      } else {
        const result = await executeAction(action.id);
        setResults((r) => ({ ...r, [action.id]: result }));
      }
      await load();
    } catch (err) {
      // Friendly message only — no raw API errors surfaced.
      setError(
        op === "execute"
          ? "The action could not run. It stopped safely — nothing unauthorized happened."
          : "The decision could not be saved. Please try again."
      );
      await load();
    } finally {
      setBusyId(null);
    }
  };

  /* Audit trail — loaded when a detail overlay opens (existing API). */
  const openDetail = async (action: AgentAction) => {
    setOpenId(action.id);
    if (!audits[action.id]) {
      try {
        const data = await fetchActionAudit(action.id);
        // Ascending — story order: proposed → decision → execution → result.
        const events = [...(data.audit_events ?? [])].reverse();
        setAudits((a) => ({ ...a, [action.id]: events }));
      } catch {
        setError("The audit trail could not be loaded. Please try again.");
      }
    }
  };

  const openAction = openId ? all.find((a) => a.id === openId) ?? null : null;

  return (
    <section className="shell section actions-page" aria-labelledby="actions-heading">
      {/* Header — reference toolbar composition: title left, live state right. */}
      <div className="actions-header">
        <div>
          <p className="meta-label">YOUR BUSINESS · GROWTH ACTIONS</p>
          <h1 id="actions-heading" className="display-lg" style={{ margin: "10px 0 0" }}>
            Growth Actions
          </h1>
          <p className="actions-header__lead">
            When your AI team finds an opportunity worth acting on, it prepares the action — you decide
            whether it runs. Every action shows exactly what will happen, what it will not do,
            and who approved it.
          </p>
        </div>
        <span className={`actions-live${waitingCount > 0 ? " actions-live--hot" : ""}`}>
          <span className="actions-live__dot" aria-hidden="true" />
          {waitingCount > 0 ? `${waitingCount} awaiting your decision` : "No decisions pending"}
        </span>
      </div>

      {/* Error */}
      {error && (
        <div className="actions-banner">
          <WindowPanel title="status.app">
            <p style={{ color: "var(--coral-strong)" }}>{error}</p>
          </WindowPanel>
        </div>
      )}

      {/* Loading */}
      {!actions && !error && (
        <div className="actions-banner">
          <WindowPanel title="growth-actions.app">
            <p className="meta-label">Loading your actions…</p>
          </WindowPanel>
        </div>
      )}

      {actions && actions.length === 0 && (
        <div className="actions-empty">
          <p className="meta-label" style={{ color: "var(--coral-strong)" }}>NO ACTIONS PREPARED YET</p>
          <p>
            The AI team has not proposed any actions yet. Run the AI Team analysis from your Growth Radar
            — when an opportunity is strong enough, the team will prepare an action for your approval.
          </p>
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" mono onClick={() => navigate("/growth-radar")}>
              Open Growth Radar →
            </Button>
          </div>
        </div>
      )}

      {actions && actions.length > 0 && (
        <>
          {/* KPI strip */}
          <div className="actions-kpis" role="group" aria-label="Actions overview">
            <div className="actions-kpi">
              <span className="actions-kpi__label">Total actions</span>
              <span className="actions-kpi__value">{all.length}</span>
              <span className="actions-kpi__sub">prepared by your AI team</span>
            </div>
            <div className="actions-kpi actions-kpi--attention">
              <span className="actions-kpi__label">Awaiting approval</span>
              <span className="actions-kpi__value">{waitingCount}</span>
              <span className="actions-kpi__sub">
                {atStake > 0 ? `${rupees(atStake)} at stake` : "no money at stake"}
              </span>
            </div>
            <div className="actions-kpi">
              <span className="actions-kpi__label">Approved & running</span>
              <span className="actions-kpi__value">{inFlightCount}</span>
              <span className="actions-kpi__sub">cleared by you — executing next</span>
            </div>
            <div className="actions-kpi">
              <span className="actions-kpi__label">Completed</span>
              <span className="actions-kpi__value">{completedCount}</span>
              <span className="actions-kpi__sub">finished successfully</span>
            </div>
            <div className="actions-kpi">
              <span className="actions-kpi__label">Failed</span>
              <span className="actions-kpi__value">{failedCount}</span>
              <span className="actions-kpi__sub">stopped safely — no unauthorized action</span>
            </div>
          </div>

          {/* Board toolbar — count left, filter chips right (reference pattern). */}
          <div className="actions-boardbar">
            <span className="actions-boardbar__count">
              {visible.length} of {all.length} shown
            </span>
            <div className="actions-filters" role="tablist" aria-label="Filter actions by status">
              {(
                [
                  ["all", "All"],
                  ["waiting", `Waiting approval${waitingCount > 0 ? ` (${waitingCount})` : ""}`],
                  ["approved", "Approved"],
                  ["completed", "Executed"],
                ] as Array<[Tab, string]>
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  className={`actions-filter${tab === key ? " actions-filter--active" : ""}`}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Status-column board — reference TasksKanban composition. */}
          <div className="actions-board">
            {BOARD_COLUMNS.map((col) => {
              const cards = visible
                .filter((a) => col.statuses.includes(a.status))
                .sort(col.key === "awaiting" ? byPriority : (a, b) =>
                  new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                );
              return (
                <div key={col.key} className={`board-column board-column--${col.accent}`}>
                  <div className={`board-column__head board-column__head--${col.accent}`}>
                    <span>{col.label}</span>
                    <span className="board-column__count">{cards.length}</span>
                  </div>
                  <div className="board-column__body">
                    {cards.length === 0 && (
                      <div className="board-column__empty">—</div>
                    )}
                    {cards.map((action) => (
                      <BoardCard
                        key={action.id}
                        action={action}
                        accent={col.accent}
                        busy={busyId === action.id}
                        result={results[action.id]}
                        onOpen={() => void openDetail(action)}
                        onApprove={() => void handle(action, "approve")}
                        onReject={() => void handle(action, "reject")}
                        onRun={() => void handle(action, "execute")}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Recent activity — reference activity-feed pattern. */}
          <div className="actions-activity">
            <p className="meta-label" style={{ marginBottom: 10 }}>RECENT ACTIVITY</p>
            {activity.length === 0 ? (
              <p className="actions-activity__empty">Nothing has happened yet.</p>
            ) : (
              <div className="actions-activity__list">
                {activity.map((item, i) => (
                  <div className="actions-activity__row" key={`${item.at}-${i}`}>
                    <span className={`actions-activity__kind actions-activity__kind--${item.accent}`}>
                      {item.kind}
                    </span>
                    <span className="actions-activity__text">{item.text}</span>
                    <span className="actions-activity__time">{relTime(item.at)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* Detail overlay — reference TaskDetail: full breakdown, big stage. */}
      {openAction && (
        <ActionDetailOverlay
          action={openAction}
          audit={audits[openAction.id]}
          result={results[openAction.id]}
          busy={busyId === openAction.id}
          onApprove={() => void handle(openAction, "approve")}
          onReject={() => void handle(openAction, "reject")}
          onRun={() => void handle(openAction, "execute")}
          onClose={() => setOpenId(null)}
        />
      )}

      {/* Footer */}
      <div className="actions-footer">
        <p>
          Every decision you make here is recorded in the audit trail — who approved, when, and
          exactly what ran.
        </p>
        <Button variant="secondary" mono onClick={() => navigate("/growth-radar")}>
          Back to Growth Radar →
        </Button>
      </div>
    </section>
  );
}

/* ── Detail overlay — reference TaskDetail, adapted to Actions content ──── */

function ActionDetailOverlay({
  action,
  audit,
  result,
  busy,
  onApprove,
  onReject,
  onRun,
  onClose,
}: {
  action: AgentAction;
  audit: AuditEventRow[] | undefined;
  result: ExecutionResponse | undefined;
  busy: boolean;
  onApprove: () => void;
  onReject: () => void;
  onRun: () => void;
  onClose: () => void;
}) {
  const copy = actionCopy(action.action_type);
  const view = payloadView(action);
  const col =
    BOARD_COLUMNS.find((c) => c.statuses.includes(action.status)) ?? BOARD_COLUMNS[0];

  return (
    <div
      className="action-overlay"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={`${copy.title} details`}
    >
      <div className="action-overlay__panel" onClick={(e) => e.stopPropagation()}>
        <header className="action-overlay__bar">
          <span className="action-overlay__filename">action-detail.app</span>
          <div className="action-overlay__bar-right">
            <span className="action-overlay__kind">GROWTH ACTION · {copy.title.toUpperCase()}</span>
            <button
              type="button"
              className="action-overlay__close"
              onClick={onClose}
              aria-label="Close action details"
            >
              ✕
            </button>
          </div>
        </header>

        <div className="action-overlay__content">
          {/* Title under a status-colored edge — reference detail pattern. */}
          <div className={`action-overlay__title-row action-overlay__title-row--${col.accent}`}>
            <h2 className="action-overlay__title">{copy.title}</h2>
          </div>

          {/* Fact row — reference: id, badge, impact meter, timestamp. */}
          <div className="action-overlay__facts">
            <span className="action-overlay__id">{action.id}</span>
            <span className={`action-status action-status--${statusTone(action.status)}`}>
              <span className="action-status__dot" aria-hidden="true" />
              {statusLabel(action.status)}
            </span>
            {action.requested_by && (
              <span className="action-overlay__badge action-overlay__badge--ai">AI TEAM</span>
            )}
            {action.approved_by && (
              <span className="action-overlay__badge action-overlay__badge--human">YOU APPROVED</span>
            )}
            <ImpactDots action={action} />
            <span className="action-overlay__stamp">Prepared {timeOf(action.created_at)}</span>
          </div>

          {/* What this is / why */}
          <div className="action-overlay__section">
            <p className="action-cell-label">WHY THIS WAS RECOMMENDED</p>
            <p className="action-overlay__prose">{copy.what}</p>
          </div>

          {/* The prepared action, line by line — reference contract box. */}
          <div className="action-overlay__section">
            <p className="action-cell-label">WHAT THE AI WILL DO</p>
            <div className="action-overlay__contract">
              <p>{view.actionLine}</p>
              <p className="action-overlay__contract-sep" />
              <p>{view.scopeLine}</p>
              <p className="action-overlay__contract-sep" />
              <p>{view.amountLine ?? "No money is moved by this action."}</p>
            </div>
          </div>

          {/* Boundaries — reference Q/A trail: paired light boxes. */}
          <div className="action-overlay__bounds">
            <div className="action-overlay__bound action-overlay__bound--will">
              <p className="action-overlay__bound-label">WILL DO</p>
              <ul>
                {copy.willDo.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
            <div className="action-overlay__bound action-overlay__bound--wont">
              <p className="action-overlay__bound-label">WILL NOT DO</p>
              <ul>
                {copy.wontDo.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          </div>

          {/* Execution outcome — real result / failure messages only. */}
          {result && (
            <div className={`action-result${result.status === "failed" ? " action-result--failure" : ""}`}>
              <p className="action-cell-label" style={{ marginBottom: 6, color: result.status === "failed" ? "var(--coral-strong)" : "var(--green-deep)" }}>
                EXECUTION RESULT
              </p>
              <p>{result.message}</p>
            </div>
          )}
          {action.status === "completed" && !result && (
            <div className="action-result">
              <p className="action-cell-label" style={{ marginBottom: 6, color: "var(--green-deep)" }}>
                EXECUTION RESULT
              </p>
              <p>
                This action was executed{action.completed_at ? ` on ${timeOf(action.completed_at)}` : ""}.
                The full recorded sequence is in the audit trail below.
              </p>
            </div>
          )}
          {action.status === "failed" && !result && (
            <div className="action-result action-result--failure">
              <p className="action-cell-label" style={{ marginBottom: 6, color: "var(--coral-strong)" }}>
                EXECUTION FAILED — SAFE STATE
              </p>
              <p>
                This action could not complete. It stopped safely — no unauthorized money action
                was taken.{action.error_message ? ` Reason recorded: ${action.error_message}` : ""}
              </p>
            </div>
          )}

          {/* Audit trail — story order, loaded on open. */}
          <div className="action-overlay__section action-overlay__section--audit">
            <p className="meta-label" style={{ marginBottom: 12 }}>AUDIT TRAIL</p>
            {!audit ? (
              <p className="actions-activity__empty">Loading the recorded sequence…</p>
            ) : audit.length === 0 ? (
              <p className="actions-activity__empty">
                No audit events were recorded for this action yet.
              </p>
            ) : (
              <div className="audit-timeline">
                {audit.map((event) => {
                  const step = auditStep(event);
                  return (
                    <div className={`audit-step audit-step--${step.actor}`} key={event.id}>
                      <span className="audit-step__marker" aria-hidden="true">
                        {step.actor === "human" ? "YOU" : step.actor === "ai" ? "AI" : "SYS"}
                      </span>
                      <div className="audit-step__body">
                        <p className="audit-step__title">{step.title}</p>
                        <p className="audit-step__meta">{timeOf(event.created_at)}</p>
                        <p className="audit-step__detail">{step.detail}</p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Controls — reference detail footer: primary decisions left. */}
          <div className="action-overlay__controls">
            {action.status === "requested" && (
              <>
                <Button variant="primary" mono disabled={busy} onClick={onApprove}>
                  {busy ? "Saving…" : "Approve"}
                </Button>
                <Button variant="secondary" mono disabled={busy} onClick={onReject}>
                  Reject
                </Button>
              </>
            )}
            {action.status === "approved" && (
              <Button variant="primary" mono disabled={busy} onClick={onRun}>
                {busy ? "Running…" : "Run now"}
              </Button>
            )}
            {action.status === "executing" && (
              <span className="action-status action-status--running">
                <span className="action-status__dot" aria-hidden="true" />
                Running…
              </span>
            )}
            <Button variant="ghost-dark" mono onClick={onClose} style={{ marginLeft: "auto" }}>
              Close
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
