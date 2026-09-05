/**
 * /actions — Growth Actions console.
 *
 * The merchant-facing half of the Phase 4 human-in-the-loop workflow:
 * AI-proposed money actions → review (explainable + bounded) →
 * approve / reject → execute → audit trail.
 *
 * All data comes from the existing actions APIs. Nothing is fabricated:
 * if no action has been proposed yet, the page says so.
 *
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

/* ── Status presentation ────────────────────────────────────────────────── */

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

/* ── Page ───────────────────────────────────────────────────────────────── */

type Tab = "waiting" | "approved" | "completed" | "all";

export function ActionsPage() {
  const navigate = useNavigate();
  const [actions, setActions] = useState<AgentAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("waiting");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ExecutionResponse>>({});
  const [audits, setAudits] = useState<Record<string, AuditEventRow[]>>({});

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

  const visible = (actions ?? []).filter((a) => {
    if (tab === "all") return true;
    if (tab === "waiting") return a.status === "requested";
    if (tab === "approved") return a.status === "approved" || a.status === "executing";
    return a.status === "completed" || a.status === "failed";
  });

  const waitingCount = (actions ?? []).filter((a) => a.status === "requested").length;

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

  const loadAudit = async (action: AgentAction) => {
    if (audits[action.id]) {
      setAudits((a) => {
        const next = { ...a };
        delete next[action.id];
        return next;
      });
      return;
    }
    try {
      const data = await fetchActionAudit(action.id);
      // Ascending — story order: proposed → decision → execution → result.
      const events = [...(data.audit_events ?? [])].reverse();
      setAudits((a) => ({ ...a, [action.id]: events }));
    } catch {
      setError("The audit trail could not be loaded. Please try again.");
    }
  };

  return (
    <section className="shell section" aria-labelledby="actions-heading">
      {/* Header */}
      <div className="actions-header">
        <div>
          <p className="meta-label">YOUR BUSINESS · GROWTH ACTIONS</p>
          <h1 id="actions-heading" className="display-lg" style={{ margin: "10px 0 0" }}>
            Growth Actions
          </h1>
          <p className="actions-header__lead">
            When your AI team finds an opportunity worth acting on, it prepares the action — you decide
            whether it runs. Every action below shows exactly what will happen, what it will not do,
            and who approved it.
          </p>
        </div>
        <span className="actions-live">
          <span className="actions-live__dot" aria-hidden="true" />
          {waitingCount > 0 ? `${waitingCount} awaiting your decision` : "No decisions pending"}
        </span>
      </div>

      {/* Journey strip */}
      <div className="actions-journey" aria-hidden="true">
        <span>Radar detects</span>
        <span className="actions-journey__rule" />
        <span>AI team analyses</span>
        <span className="actions-journey__rule" />
        <span className="actions-journey__step--active">You approve</span>
        <span className="actions-journey__rule" />
        <span>System executes</span>
        <span className="actions-journey__rule" />
        <span>Audit records</span>
      </div>

      {/* Error */}
      {error && (
        <div className="actions-section">
          <WindowPanel title="status.app">
            <p style={{ color: "var(--coral-strong)" }}>{error}</p>
          </WindowPanel>
        </div>
      )}

      {/* Actions list */}
      <div className="actions-section">
        <div className="actions-section__head">
          <h2 className="meta-label" style={{ margin: 0 }}>PREPARED ACTIONS</h2>
        </div>
        <p className="actions-section__lede">
          Each action was proposed by the AI team from your real Razorpay TEST data. Approving an action
          lets it run — rejecting stops it permanently. Actions are bounded: they only touch the
          customers and payments named below.
        </p>

        {!actions && !error && (
          <WindowPanel title="growth-actions.app">
            <p className="meta-label" style={{ color: "var(--ink-soft)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "var(--tracking-meta)" }}>
              Loading your actions…
            </p>
          </WindowPanel>
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
            <div className="actions-tabs" role="tablist" aria-label="Filter actions by status">
              {(
                [
                  ["waiting", "Waiting approval"],
                  ["approved", "Approved"],
                  ["completed", "Executed"],
                  ["all", "All"],
                ] as Array<[Tab, string]>
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  className={`actions-tab${tab === key ? " actions-tab--active" : ""}`}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="actions-list">
              {visible.map((action) => {
                const copy = actionCopy(action.action_type);
                const view = payloadView(action);
                const result = results[action.id];
                const audit = audits[action.id];
                return (
                  <article className="action-card" key={action.id}>
                    <div className="action-card__bar">
                      <span>GROWTH ACTION · {copy.title.toUpperCase()}</span>
                      <span className={`action-status action-status--${statusTone(action.status)}`}>
                        <span className="action-status__dot" aria-hidden="true" />
                        {statusLabel(action.status)}
                      </span>
                    </div>
                    <div className="action-card__body">
                      <h3 className="action-card__title">{copy.title}</h3>

                      <div className="action-card__grid">
                        <div className="action-card__cell">
                          <p className="action-cell-label">WHY THIS WAS RECOMMENDED</p>
                          <p>{copy.what}</p>
                        </div>
                        <div className="action-card__cell">
                          <p className="action-cell-label">WHAT THE AI WILL DO</p>
                          <p>{view.actionLine}</p>
                        </div>
                        <div className="action-card__cell">
                          <p className="action-cell-label">SCOPE — WHO / WHAT IS AFFECTED</p>
                          <p>{view.scopeLine}</p>
                        </div>
                        <div className="action-card__cell">
                          <p className="action-cell-label">MAXIMUM AMOUNT INVOLVED</p>
                          <p>{view.amountLine ?? "No money is moved by this action."}</p>
                        </div>
                      </div>

                      <div className="action-card__bounds">
                        <p className="action-cell-label" style={{ marginBottom: 0, color: "var(--green-deep)" }}>
                          BOUNDARIES
                        </p>
                        <ul>
                          {copy.willDo.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                          {copy.wontDo.map((line) => (
                            <li key={line}>Will NOT: {line.replace(/^(Charge|Contact|Send|Exceed|Apply|Retry|Create|Take|Run|Record) /, (m) => `${m.toLowerCase()}`)}</li>
                          ))}
                        </ul>
                      </div>

                      <div className="action-card__footer">
                        <p className="action-card__approval-note">
                          Prepared {timeOf(action.created_at)}
                          {action.requested_by ? " · by the AI team" : ""}
                        </p>
                        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                          {action.status === "requested" && (
                            <>
                              <Button
                                variant="primary"
                                mono
                                disabled={busyId === action.id}
                                onClick={() => handle(action, "approve")}
                              >
                                {busyId === action.id ? "Saving…" : "Approve"}
                              </Button>
                              <Button
                                variant="secondary"
                                mono
                                disabled={busyId === action.id}
                                onClick={() => handle(action, "reject")}
                              >
                                Reject
                              </Button>
                            </>
                          )}
                          {action.status === "approved" && (
                            <Button
                              variant="primary"
                              mono
                              disabled={busyId === action.id}
                              onClick={() => handle(action, "execute")}
                            >
                              {busyId === action.id ? "Running…" : "Run now"}
                            </Button>
                          )}
                          {action.status === "executing" && (
                            <span className="action-status action-status--running">
                              <span className="action-status__dot" aria-hidden="true" />
                              Running…
                            </span>
                          )}
                          <Button variant="ghost-dark" mono onClick={() => loadAudit(action)}>
                            {audit ? "Hide audit trail" : "View audit trail"}
                          </Button>
                        </div>
                      </div>

                      {/* Execution result */}
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
                            Open the audit trail below for the full recorded sequence.
                          </p>
                        </div>
                      )}
                      {action.status === "failed" && !result && (
                        <div className="action-result action-result--failure">
                          <p className="action-cell-label" style={{ marginBottom: 6, color: "var(--coral-strong)" }}>
                            EXECUTION FAILED — SAFE STATE
                          </p>
                          <p>
                            This action could not complete. It stopped safely — no unauthorized money
                            action was taken. You can review the audit trail to see exactly what happened.
                          </p>
                        </div>
                      )}

                      {/* Audit trail */}
                      {audit && (
                        <div style={{ marginTop: 16 }}>
                          <p className="meta-label" style={{ marginBottom: 12 }}>AUDIT TRAIL</p>
                          {audit.length === 0 ? (
                            <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)" }}>
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
                      )}
                    </div>
                  </article>
                );
              })}

              {visible.length === 0 && (
                <div className="actions-empty">
                  <p>No actions match this filter right now.</p>
                </div>
              )}
            </div>
          </>
        )}
      </div>

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
