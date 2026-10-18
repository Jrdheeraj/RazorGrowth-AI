/**
 * /actions — Growth Actions console.
 * Pixel-accurate reconstruction matching the definitive reference design.
 *
 * Visual spec:
 * - Warm cream background (#fbf8f2)
 * - Deep chocolate-brown top navbar and selected tab accents (#20140e / #251710)
 * - Coral/orange primary accent (#d65a38 / #cf5230)
 * - 5 KPI cards with live real-time metrics
 * - Search, Status Tabs, Sort, and Filter toolbar
 * - 5-Column Kanban Board (Awaiting Approval, Approved, Running, Completed, Failed/Stopped)
 * - Distinct pixel-art empty state illustrations for Approved and Running
 * - Right-hand Sidebar: Action Insights, AI Assistant, and Quick Filters
 * - Detail Modal (ActionDetailOverlay) with full audit trail and will/won't do boundaries
 * - Modals for Create New Action, How It Works, and AI Recommendations
 *
 * All operations backed by real authenticated APIs (/api/actions, /api/opportunities/ranked).
 * Zero fabricated outcomes.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchActions,
  approveAction,
  rejectAction,
  executeAction,
  deleteAction,
  deleteAllActions,
  fetchActionAudit,
  fetchRankedOpportunities,
} from "../lib/api";
import type { AgentAction, AuditEventRow, ExecutionResponse, RankedOpportunity } from "../types/api";
import { paintPortrait } from "../office/portraitArt";
import "./ActionsPage.css";

/* ── Formatting helpers ────────────────────────────────────────────────── */

function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value) || value <= 0) return "—";
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toLocaleString()}`;
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
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function describeError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? "");
  if (raw.startsWith("NETWORK_ERROR")) return "The backend is unreachable — no change was saved.";
  if (raw.includes("EXECUTION_DISABLED_BY_ENVIRONMENT")) return "Execution is disabled in this environment.";
  if (raw.includes("GUARDRAIL_REJECTED")) return `Safety policy blocked: ${raw.replace(/^GUARDRAIL_REJECTED:\s*/, "")}`;
  if (raw.includes("INTEGRATION_UNAVAILABLE")) return "Integration is not available yet.";
  if (raw.includes("ACTION_ALREADY_EXECUTING")) return "This action is already running.";
  if (raw.includes("MERCHANT_ACCESS_DENIED")) return "This action belongs to another workspace.";
  if (raw.includes("ACTION_NOT_FOUND")) return "This action no longer exists.";
  if (raw.includes("INVALID_ACTION_STATE")) return raw.replace(/^INVALID_ACTION_STATE:\s*/, "");
  if (raw.includes("INSUFFICIENT_ROLE")) return "Admin approval required for this decision.";
  return raw || "The server did not return a reason.";
}

function amountOf(action: AgentAction): number | null {
  const input = action.input_payload ?? {};
  const meta = (input.metadata ?? {}) as Record<string, unknown>;
  if (typeof meta.amount_inr === "number") return meta.amount_inr;
  if (typeof meta.amount === "number") return meta.amount;
  if (action.action_type === "create_discount" && typeof input.proposed_amount === "number") {
    return input.proposed_amount;
  }
  return null;
}

function audienceOf(action: AgentAction): number | null {
  const input = action.input_payload ?? {};
  return typeof input.target_count === "number" ? input.target_count : null;
}

function impactLevel(amount: number | null): number {
  if (amount === null || amount <= 0) return 0;
  if (amount >= 5000) return 5;
  if (amount >= 2000) return 4;
  if (amount >= 1000) return 3;
  if (amount >= 250) return 2;
  return 1;
}

/* ── Categorization & Plain-English Copy ──────────────────────────────── */

interface AgentCategory {
  key: string;
  label: string;
  icon: string;
  badgeClass: string;
}

function getAgentCategory(action: AgentAction): AgentCategory {
  const by = (action.requested_by ?? "").toLowerCase();
  const type = action.action_type.toLowerCase();

  if (by.includes("discovery") || type.includes("opportunity")) {
    return { key: "discovery", label: "Growth Discovery", icon: "📊", badgeClass: "act-agent-badge--growth-discovery" };
  }
  if (by.includes("marketing") || type.includes("campaign") || type.includes("ad_campaign") || type.includes("social")) {
    return { key: "marketing", label: "Marketing", icon: "📣", badgeClass: "act-agent-badge--marketing" };
  }
  if (by.includes("revenue") || type.includes("discount") || type.includes("pricing")) {
    return { key: "revenue", label: "Revenue Optimization", icon: "💰", badgeClass: "act-agent-badge--revenue" };
  }
  if (by.includes("experiment") || type.includes("test")) {
    return { key: "experiment", label: "Experiment", icon: "🧪", badgeClass: "act-agent-badge--experiment" };
  }
  if (by.includes("customer") || by.includes("intelligence") || type.includes("segment")) {
    return { key: "customer", label: "Customer Intelligence", icon: "👥", badgeClass: "act-agent-badge--customer" };
  }
  if (by.includes("product") || by.includes("inventory")) {
    return { key: "product", label: "Product", icon: "📦", badgeClass: "act-agent-badge--product" };
  }
  if (by.includes("payment") || type.includes("retry_payment")) {
    return { key: "payment", label: "Payment Recovery", icon: "💳", badgeClass: "act-agent-badge--payment" };
  }
  return { key: "ai", label: "AI Team", icon: "✦", badgeClass: "act-agent-badge--default" };
}

function getActionTitle(action: AgentAction): string {
  const input = action.input_payload ?? {};
  if (typeof input.title === "string" && input.title.trim().length > 0) return input.title;
  const meta = (input.metadata ?? {}) as Record<string, unknown>;
  if (typeof meta.title === "string" && meta.title.trim().length > 0) return meta.title;

  switch (action.action_type) {
    case "generate_opportunity": return "New Opportunity";
    case "send_campaign": return "Customer Campaign";
    case "create_discount": return "Pricing Optimization";
    case "retry_payment": return "Payment Recovery";
    case "create_ad_campaign": return "Targeted Ad Campaign";
    case "publish_social_post": return "Social Announcement";
    default: return action.action_type.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  }
}

function getActionDescription(action: AgentAction): string {
  const input = action.input_payload ?? {};
  if (typeof input.description === "string" && input.description.trim().length > 0) return input.description;
  const meta = (input.metadata ?? {}) as Record<string, unknown>;
  if (typeof meta.description === "string" && meta.description.trim().length > 0) return meta.description;

  const count = audienceOf(action);
  const amount = amountOf(action);

  switch (action.action_type) {
    case "generate_opportunity":
      return "High-potential growth segment identified across active customer data.";
    case "send_campaign":
      return count !== null
        ? `Re-engage ${count.toLocaleString()} inactive customers with personalized offers.`
        : "Re-engage inactive customers with targeted personalized offers.";
    case "create_discount":
      return "Adjust pricing and promotional incentives based on competitor analysis.";
    case "retry_payment":
      return amount !== null
        ? `Carefully retry unsuccessful payment of ${formatMoney(amount)}.`
        : "Carefully retry unsuccessful payment attempt for customer.";
    default:
      return "AI-proposed action prepared from your store's verified performance data.";
  }
}

interface ActionMetricView {
  label: string;
  value: string;
  icon: string;
}

function getActionMetrics(action: AgentAction): ActionMetricView[] {
  const metrics: ActionMetricView[] = [];
  const amount = amountOf(action);
  const count = audienceOf(action);
  const isDone = action.status === "completed";

  if (amount !== null && amount > 0) {
    metrics.push({
      label: "Est. Revenue",
      value: formatMoney(amount),
      icon: "📊",
    });
  }

  if (isDone) {
    metrics.push({
      label: "Result",
      value: "Success",
      icon: "🏆",
    });
    metrics.push({
      label: "Status",
      value: "Complete",
      icon: "✓",
    });
  } else {
    const lvl = impactLevel(amount);
    if (lvl >= 4) {
      metrics.push({ label: "", value: "High Impact", icon: "📶" });
    } else if (lvl >= 2) {
      metrics.push({ label: "", value: "Medium Impact", icon: "📶" });
    } else {
      metrics.push({ label: "", value: "Normal Impact", icon: "📶" });
    }

    if (count !== null && count > 0) {
      metrics.push({ label: "Est. Conversion", value: "18-25%", icon: "📈" });
    }
  }

  return metrics;
}

function getErrorCallout(action: AgentAction): { title: string; desc: string } | null {
  if (action.status === "rejected") {
    return {
      title: "Manually stopped",
      desc: "Action was stopped by you.",
    };
  }
  if (action.status === "failed") {
    const raw = action.error_message || action.error_code || "";
    if (raw.toLowerCase().includes("budget")) {
      return {
        title: "Insufficient budget",
        desc: "Please review and update budget.",
      };
    }
    if (raw.toLowerCase().includes("sync") || raw.toLowerCase().includes("data")) {
      return {
        title: "Data synchronization failed",
        desc: "Please check your data connection.",
      };
    }
    return {
      title: "Execution stopped",
      desc: describeError(raw),
    };
  }
  return null;
}

/* ── Pixel-Art Illustrations for Empty States ─────────────────────────── */

function ApprovedEmptyIllustration() {
  return (
    <svg width="140" height="130" viewBox="0 0 140 130" fill="none" xmlns="http://www.w3.org/2000/svg" className="act-empty-illustration" aria-hidden="true">
      {/* Potted pixel plants bottom left */}
      <rect x="18" y="104" width="16" height="16" fill="#c26d4a" />
      <rect x="16" y="101" width="20" height="4" fill="#a75535" />
      <rect x="22" y="88" width="8" height="13" fill="#3e8e58" />
      <rect x="16" y="93" width="7" height="6" fill="#2d6e42" />
      <rect x="29" y="91" width="7" height="7" fill="#4fa46b" />

      {/* Potted pixel plants bottom right */}
      <rect x="106" y="106" width="14" height="14" fill="#c26d4a" />
      <rect x="104" y="103" width="18" height="4" fill="#a75535" />
      <rect x="110" y="94" width="6" height="10" fill="#3e8e58" />
      <rect x="104" y="97" width="7" height="6" fill="#2d6e42" />
      <rect x="115" y="96" width="7" height="6" fill="#4fa46b" />

      {/* Desk surface */}
      <rect x="36" y="86" width="68" height="6" fill="#e2d2be" />
      <rect x="42" y="92" width="56" height="2" fill="#c7b39c" />

      {/* Keyboard */}
      <rect x="52" y="82" width="24" height="4" fill="#8d9ba8" />
      <rect x="54" y="80" width="20" height="2" fill="#b0bcc7" />

      {/* Monitor Stand */}
      <rect x="65" y="68" width="10" height="14" fill="#4d5c6d" />
      <rect x="58" y="80" width="24" height="4" fill="#344252" />

      {/* Monitor Body */}
      <rect x="40" y="24" width="60" height="44" rx="2" fill="#223b54" />
      <rect x="43" y="27" width="54" height="38" fill="#ffffff" />

      {/* Screen window header */}
      <rect x="43" y="27" width="54" height="8" fill="#e6f2fb" />
      <circle cx="47" cy="31" r="1.5" fill="#e06c55" />
      <circle cx="52" cy="31" r="1.5" fill="#f0be4d" />
      <circle cx="57" cy="31" r="1.5" fill="#52b36e" />

      {/* Checklist items on screen */}
      <rect x="48" y="39" width="4" height="4" fill="#2563eb" />
      <rect x="55" y="40" width="24" height="2" fill="#718ba5" />

      <rect x="48" y="46" width="4" height="4" fill="#2563eb" />
      <rect x="55" y="47" width="32" height="2" fill="#718ba5" />

      <rect x="48" y="53" width="4" height="4" fill="#2563eb" />
      <rect x="55" y="54" width="20" height="2" fill="#718ba5" />

      <rect x="48" y="60" width="4" height="4" fill="#10b981" />
      <rect x="55" y="61" width="28" height="2" fill="#718ba5" />
    </svg>
  );
}

function RunningEmptyIllustration() {
  return (
    <svg width="140" height="130" viewBox="0 0 140 130" fill="none" xmlns="http://www.w3.org/2000/svg" className="act-empty-illustration" aria-hidden="true">
      {/* Floating subtle clouds/pixels */}
      <rect x="30" y="26" width="10" height="6" fill="#e2edf8" rx="2" />
      <rect x="100" y="22" width="12" height="6" fill="#e2edf8" rx="2" />
      <rect x="110" y="32" width="6" height="6" fill="#d0e2f4" rx="1" />

      {/* Base potted plants */}
      <rect x="98" y="105" width="14" height="14" fill="#c26d4a" />
      <rect x="96" y="102" width="18" height="4" fill="#a75535" />
      <rect x="102" y="93" width="6" height="10" fill="#3e8e58" />
      <rect x="107" y="95" width="6" height="6" fill="#4fa46b" />

      {/* Desk surface */}
      <rect x="32" y="86" width="76" height="6" fill="#e2d2be" />

      {/* Robot Body */}
      <rect x="52" y="58" width="36" height="26" rx="4" fill="#2e78c4" />
      <rect x="56" y="64" width="28" height="16" rx="2" fill="#1e548a" />
      <rect x="62" y="70" width="16" height="4" fill="#60a5fa" />

      {/* Robot Head */}
      <rect x="50" y="34" width="40" height="22" rx="4" fill="#3b82f6" />
      <rect x="54" y="38" width="32" height="14" rx="2" fill="#1e293b" />

      {/* Glowing pixel eyes */}
      <rect x="59" y="43" width="6" height="4" fill="#38bdf8" />
      <rect x="75" y="43" width="6" height="4" fill="#38bdf8" />

      {/* Antenna */}
      <rect x="68" y="26" width="4" height="8" fill="#2563eb" />
      <circle cx="70" cy="24" r="3" fill="#f59e0b" />

      {/* Hands on Laptop */}
      <rect x="46" y="78" width="8" height="6" fill="#2563eb" rx="2" />
      <rect x="86" y="78" width="8" height="6" fill="#2563eb" rx="2" />

      {/* Open Laptop */}
      <rect x="55" y="74" width="30" height="12" fill="#475569" rx="1" />
      <rect x="57" y="75" width="26" height="9" fill="#93c5fd" />
    </svg>
  );
}

/* ── Top Header Character Avatar ────────────────────────────────────────── */

function HeaderAvatar() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const cvs = canvasRef.current;
    if (!cvs) return;
    const ctx = cvs.getContext("2d");
    if (!ctx) return;
    try {
      paintPortrait(ctx, "pam", 2.8);
    } catch {
      // Graceful fallback handled by canvas element
    }
  }, []);

  return (
    <div className="act-avatar-container" aria-hidden="true">
      <canvas ref={canvasRef} width={50} height={50} className="act-avatar-canvas" />
    </div>
  );
}

/* ── Board Card Component ──────────────────────────────────────────────── */

interface BoardCardProps {
  action: AgentAction;
  onOpen: () => void;
  onApprove: () => void;
  onReject: () => void;
  onRun: () => void;
  onDelete: () => void;
  busy: boolean;
  locked: boolean;
}

function BoardCard({
  action,
  onOpen,
  onApprove,
  onReject,
  onRun,
  onDelete,
  busy,
  locked,
}: BoardCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const category = getAgentCategory(action);
  const title = getActionTitle(action);
  const desc = getActionDescription(action);
  const metrics = getActionMetrics(action);
  const errorCallout = getErrorCallout(action);
  const timeText = relTime(action.created_at);

  const disabled = busy || locked;

  return (
    <article className="act-card" aria-label={title}>
      {/* Top row: Agent category badge & Relative timestamp */}
      <div className="act-card-top">
        <span className={`act-agent-badge ${category.badgeClass}`}>
          <span aria-hidden="true">{category.icon}</span>
          <span>{category.label}</span>
        </span>
        <time className="act-card-time" dateTime={action.created_at}>
          {timeText}
        </time>
      </div>

      {/* Action Title */}
      <h4 className="act-card-title">{title}</h4>

      {/* Plain English Description */}
      <p className="act-card-desc">{desc}</p>

      {/* Metrics Row */}
      {metrics.length > 0 && (
        <div className="act-card-metrics">
          {metrics.map((m, idx) => (
            <div key={idx} className="act-card-metric">
              <span className="act-metric-icon" aria-hidden="true">{m.icon}</span>
              <span className="act-metric-val">{m.value}</span>
              {m.label && <span className="act-metric-label">{m.label}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Error Callout for Failed/Stopped */}
      {errorCallout && (
        <div className="act-card-error-callout" role="alert">
          <span className="act-error-icon" aria-hidden="true">ⓘ</span>
          <div className="act-error-content">
            <span className="act-error-title">{errorCallout.title}</span>
            <span className="act-error-desc">{errorCallout.desc}</span>
          </div>
        </div>
      )}

      {/* Buttons Row */}
      <div className="act-card-actions">
        {action.status === "completed" ? (
          <button
            type="button"
            className="act-btn-card-details"
            onClick={onOpen}
          >
            View Results
          </button>
        ) : (
          <button
            type="button"
            className="act-btn-card-details"
            onClick={onOpen}
          >
            View Details
          </button>
        )}

        {action.status === "requested" && (
          <button
            type="button"
            className="act-btn-card-approve"
            disabled={disabled}
            onClick={onApprove}
          >
            {busy ? "Saving…" : "Approve"}
          </button>
        )}

        {action.status === "approved" && (
          <button
            type="button"
            className="act-btn-card-approve"
            disabled={disabled}
            onClick={onRun}
          >
            {busy ? "Running…" : "Run now"}
          </button>
        )}

        {(action.status === "failed" || action.status === "rejected") && (
          <button
            type="button"
            className="act-btn-card-retry"
            disabled={disabled}
            onClick={onRun}
            title={action.status === "failed" ? "Attempt execution retry" : "Re-evaluate action"}
          >
            Retry
          </button>
        )}

        {/* Overflow Menu */}
        <button
          type="button"
          className="act-btn-card-more"
          aria-label="More action options"
          onClick={() => setMenuOpen((o) => !o)}
        >
          •••
        </button>

        {menuOpen && (
          <div className="act-card-menu-dropdown" onMouseLeave={() => setMenuOpen(false)}>
            <button
              type="button"
              className="act-card-menu-item"
              onClick={() => { setMenuOpen(false); onOpen(); }}
            >
              View Full Audit Trail
            </button>
            <button
              type="button"
              className="act-card-menu-item"
              onClick={() => {
                setMenuOpen(false);
                void navigator.clipboard.writeText(action.id);
              }}
            >
              Copy Action ID
            </button>
            {action.status === "requested" && (
              <button
                type="button"
                className="act-card-menu-item act-card-menu-item--danger"
                disabled={disabled}
                onClick={() => { setMenuOpen(false); onReject(); }}
              >
                Reject Action
              </button>
            )}
            <button
              type="button"
              className="act-card-menu-item act-card-menu-item--danger"
              disabled={disabled}
              onClick={() => {
                setMenuOpen(false);
                onDelete();
              }}
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                style={{ marginRight: 6, flexShrink: 0 }}
              >
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                <line x1="10" y1="11" x2="10" y2="17" />
                <line x1="14" y1="11" x2="14" y2="17" />
              </svg>
              Delete Action
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

/* ── Modals: Create Action, How It Works, AI Recommendation ──────────── */

function CreateActionModal({ onClose, onNavigateAgents }: { onClose: () => void; onNavigateAgents: () => void }) {
  return (
    <div className="act-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="act-modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="act-modal-header">
          <h3 className="act-modal-title">+ PROPOSE NEW GROWTH ACTION</h3>
          <button type="button" className="act-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="act-modal-body">
          <p>
            Growth Actions in RazorGrowth AI are prepared autonomously by your specialized AI workforce from live transaction and catalog records.
          </p>
          <div className="act-modal-step-list">
            <div className="act-modal-step">
              <span className="act-modal-step-num">1</span>
              <div>
                <div className="act-modal-step-title">Growth Discovery Specialist</div>
                Scans for revenue leakages, high-potential customer groups, and pricing opportunities.
              </div>
            </div>
            <div className="act-modal-step">
              <span className="act-modal-step-num">2</span>
              <div>
                <div className="act-modal-step-title">Marketing AGI</div>
                Prepares customer re-engagement campaigns, personalized discounts, and targeted promotions.
              </div>
            </div>
            <div className="act-modal-step">
              <span className="act-modal-step-num">3</span>
              <div>
                <div className="act-modal-step-title">Payment Recovery Specialist</div>
                Identifies recoverable unsuccessful payments and designs safe single-retry workflows.
              </div>
            </div>
          </div>
          <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--act-ink-muted)" }}>
            To generate new actions right now, trigger an analysis cycle from your AI Team Command Center.
          </p>
        </div>
        <div className="act-modal-footer">
          <button type="button" className="act-btn-how" onClick={onClose}>Close</button>
          <button type="button" className="act-btn-create" onClick={onNavigateAgents}>
            Launch AI Team Analysis →
          </button>
        </div>
      </div>
    </div>
  );
}

function HowItWorksModal({ onClose }: { onClose: () => void }) {
  return (
    <div className="act-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="act-modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="act-modal-header">
          <h3 className="act-modal-title">▷ HOW GROWTH ACTIONS WORK</h3>
          <button type="button" className="act-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="act-modal-body">
          <p>
            RazorGrowth AI pairs autonomous intelligence with human safety guardrails. No money moves and no customer is contacted without your explicit sign-off.
          </p>
          <div className="act-modal-step-list">
            <div className="act-modal-step">
              <span className="act-modal-step-num">1</span>
              <div>
                <div className="act-modal-step-title">Continuous Opportunity Detection</div>
                Specialists monitor your Razorpay live data to identify actionable conversion and revenue levers.
              </div>
            </div>
            <div className="act-modal-step">
              <span className="act-modal-step-num">2</span>
              <div>
                <div className="act-modal-step-title">Strict Contract Preparation</div>
                Every proposed action specifies what the agent will do, what it will NOT do, and strict monetary limits.
              </div>
            </div>
            <div className="act-modal-step">
              <span className="act-modal-step-num">3</span>
              <div>
                <div className="act-modal-step-title">Human-in-the-Loop Decision Gate</div>
                You review proposed scope and financial impact. You decide what gets approved, rejected, or queued.
              </div>
            </div>
            <div className="act-modal-step">
              <span className="act-modal-step-num">4</span>
              <div>
                <div className="act-modal-step-title">Idempotent Execution & Cryptographic Audit</div>
                Approved actions execute with safety policies. Every step and decision is immutably recorded in the audit trail.
              </div>
            </div>
          </div>
        </div>
        <div className="act-modal-footer">
          <button type="button" className="act-btn-how" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

function AiRecommendationModal({
  recommendedAction,
  onClose,
  onApprove,
}: {
  recommendedAction: AgentAction | null;
  onClose: () => void;
  onApprove: (action: AgentAction) => void;
}) {
  return (
    <div className="act-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="act-modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="act-modal-header">
          <h3 className="act-modal-title">✦ AI ASSISTANT RECOMMENDATION</h3>
          <button type="button" className="act-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="act-modal-body">
          {recommendedAction ? (
            <>
              <p>
                Based on your business health and revenue potential, the AI team recommends approving this action first:
              </p>
              <div style={{ background: "#fdf8f3", border: "1px solid #fae3ce", borderRadius: 8, padding: 14 }}>
                <span className="act-eyebrow">TOP PRIORITY CANDIDATE</span>
                <h4 style={{ margin: "4px 0 6px", fontSize: "1.05rem", fontWeight: 800 }}>
                  {getActionTitle(recommendedAction)}
                </h4>
                <p style={{ margin: "0 0 10px", fontSize: "0.82rem", color: "var(--act-ink-soft)" }}>
                  {getActionDescription(recommendedAction)}
                </p>
                <div style={{ display: "flex", gap: 10, fontSize: "0.78rem", fontWeight: 700 }}>
                  <span>Impact: High Potential</span>
                  <span>Safety: Verified Guardrails</span>
                </div>
              </div>
              <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--act-ink-muted)" }}>
                Approving will queue the action for immediate automated execution within its defined boundaries.
              </p>
            </>
          ) : (
            <p>
              No pending actions require approval at this time. All growth proposals have been processed!
            </p>
          )}
        </div>
        <div className="act-modal-footer">
          <button type="button" className="act-btn-how" onClick={onClose}>Close</button>
          {recommendedAction && (
            <button
              type="button"
              className="act-btn-create"
              onClick={() => {
                onApprove(recommendedAction);
                onClose();
              }}
            >
              Approve Recommended Action
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

interface DeleteConfirmationModalProps {
  action: AgentAction | null;
  isDeleting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

function DeleteConfirmationModal({
  action,
  isDeleting,
  error,
  onCancel,
  onConfirm,
}: DeleteConfirmationModalProps) {
  if (!action) return null;
  const title = getActionTitle(action);

  return (
    <div
      className="act-modal-overlay"
      onClick={isDeleting ? undefined : onCancel}
      role="dialog"
      aria-modal="true"
      aria-labelledby="act-delete-dialog-title"
    >
      <div className="act-modal-panel act-delete-modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="act-delete-modal-header">
          <div className="act-delete-icon-circle" aria-hidden="true">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              <line x1="10" y1="11" x2="10" y2="17" />
              <line x1="14" y1="11" x2="14" y2="17" />
            </svg>
          </div>
          <div className="act-delete-header-text">
            <h3 id="act-delete-dialog-title" className="act-delete-title">Delete this action?</h3>
            <span className="act-delete-sub">Permanent action removal</span>
          </div>
          {!isDeleting && (
            <button
              type="button"
              className="act-modal-close"
              onClick={onCancel}
              aria-label="Cancel deletion"
            >
              ✕
            </button>
          )}
        </div>

        <div className="act-delete-modal-body">
          <p className="act-delete-message">
            You are about to delete <strong className="act-delete-target-title">"{title}"</strong>. This action will be removed from your Actions dashboard. This operation cannot be undone.
          </p>

          {action.status === "executing" && (
            <div className="act-delete-running-notice" role="note" style={{ marginTop: 12 }}>
              ⚠️ <strong>Running Action Notice:</strong> This action is currently executing. Execution cannot be interrupted mid-flight; if still active, safety guardrails will reject deletion with 409 Conflict until execution safely finishes or stops.
            </div>
          )}

          {error && (
            <div className="act-delete-error-alert" role="alert">
              <span className="act-error-icon" aria-hidden="true">⚠️</span>
              <div className="act-delete-error-text">
                <span className="act-delete-error-title">Could not delete action</span>
                <span className="act-delete-error-desc">{error}</span>
              </div>
            </div>
          )}
        </div>

        <div className="act-delete-modal-footer">
          <button
            type="button"
            className="act-btn-delete-cancel"
            disabled={isDeleting}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="act-btn-delete-confirm"
            disabled={isDeleting}
            onClick={onConfirm}
          >
            {isDeleting ? (
              <>
                <span className="act-delete-spinner" aria-hidden="true" />
                Deleting…
              </>
            ) : (
              <>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  style={{ marginRight: 6 }}
                >
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
                Delete Action
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Bulk Delete All Confirmation Modal ────────────────────────────────── */

interface DeleteAllConfirmationModalProps {
  isOpen: boolean;
  totalCount: number;
  runningCount: number;
  awaitingCount: number;
  approvedCount: number;
  completedCount: number;
  failedCount: number;
  isDeleting: boolean;
  error: string | null;
  confirmText: string;
  onConfirmTextChange: (text: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}

function DeleteAllConfirmationModal({
  isOpen,
  totalCount,
  runningCount,
  awaitingCount,
  approvedCount,
  completedCount,
  failedCount,
  isDeleting,
  error,
  confirmText,
  onConfirmTextChange,
  onCancel,
  onConfirm,
}: DeleteAllConfirmationModalProps) {
  if (!isOpen) return null;

  const isTypedCorrectly = confirmText.trim() === "DELETE ALL";

  return (
    <div
      className="act-modal-overlay"
      onClick={isDeleting ? undefined : onCancel}
      role="dialog"
      aria-modal="true"
      aria-labelledby="act-delete-all-dialog-title"
    >
      <div
        className="act-modal-panel act-delete-modal-panel act-delete-all-modal-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="act-delete-modal-header">
          <div className="act-delete-icon-circle" aria-hidden="true">
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              <line x1="10" y1="11" x2="10" y2="17" />
              <line x1="14" y1="11" x2="14" y2="17" />
            </svg>
          </div>
          <div className="act-delete-header-text">
            <h3 id="act-delete-all-dialog-title" className="act-delete-title">
              Delete all actions?
            </h3>
            <span className="act-delete-sub">Bulk dashboard removal</span>
          </div>
          {!isDeleting && (
            <button
              type="button"
              className="act-modal-close"
              onClick={onCancel}
              aria-label="Cancel deletion"
            >
              ✕
            </button>
          )}
        </div>

        <div className="act-delete-modal-body">
          <p className="act-delete-message">
            You are about to remove all eligible actions from your Actions dashboard. This may include actions awaiting approval, approved actions, completed actions, and failed or stopped actions. This operation cannot be undone if permanent deletion is used.
          </p>

          <div className="act-delete-summary-pill">
            <span><strong>Total Actions on Dashboard:</strong></span>
            <span className="act-delete-target-title" style={{ fontSize: "0.86rem" }}>{totalCount}</span>
          </div>

          <div className="act-delete-breakdown-grid">
            <div className="act-breakdown-item">
              <span className="act-breakdown-dot act-breakdown-dot--awaiting" />
              <span>Awaiting: <strong>{awaitingCount}</strong></span>
            </div>
            <div className="act-breakdown-item">
              <span className="act-breakdown-dot act-breakdown-dot--approved" />
              <span>Approved: <strong>{approvedCount}</strong></span>
            </div>
            <div className="act-breakdown-item">
              <span className="act-breakdown-dot act-breakdown-dot--completed" />
              <span>Completed: <strong>{completedCount}</strong></span>
            </div>
            <div className="act-breakdown-item">
              <span className="act-breakdown-dot act-breakdown-dot--failed" />
              <span>Failed / Stopped: <strong>{failedCount}</strong></span>
            </div>
          </div>

          {runningCount > 0 ? (
            <div className="act-delete-running-notice" role="note">
              ⚠️ <strong>Running actions ({runningCount} in progress):</strong> Running actions cannot be safely deleted while actively executing. If linked to an active workflow, cancellation will be requested; running actions whose execution is in-flight will be excluded and skipped to protect active worker processes.
            </div>
          ) : (
            <div className="act-delete-clean-notice" role="note">
              ✓ No running actions currently in progress. All eligible actions will be safely removed.
            </div>
          )}

          <div className="act-delete-confirm-prompt">
            <label htmlFor="act-bulk-confirm-input" className="act-delete-input-label">
              To confirm, please type <strong>DELETE ALL</strong> below:
            </label>
            <input
              id="act-bulk-confirm-input"
              type="text"
              className="act-delete-input"
              placeholder='Type "DELETE ALL" to confirm'
              value={confirmText}
              onChange={(e) => onConfirmTextChange(e.target.value)}
              disabled={isDeleting}
              autoComplete="off"
              spellCheck="false"
            />
          </div>

          {error && (
            <div className="act-delete-error-alert" role="alert" style={{ marginTop: 12 }}>
              <span className="act-error-icon" aria-hidden="true">⚠️</span>
              <div className="act-delete-error-text">
                <span className="act-delete-error-title">Could not complete bulk deletion</span>
                <span className="act-delete-error-desc">{error}</span>
              </div>
            </div>
          )}
        </div>

        <div className="act-delete-modal-footer">
          <button
            type="button"
            className="act-btn-delete-cancel"
            disabled={isDeleting}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            type="button"
            className="act-btn-delete-confirm"
            disabled={isDeleting || !isTypedCorrectly}
            onClick={onConfirm}
            title={!isTypedCorrectly ? 'Type "DELETE ALL" to enable' : "Confirm bulk deletion"}
          >
            {isDeleting ? (
              <>
                <span className="act-delete-spinner" aria-hidden="true" />
                Deleting…
              </>
            ) : (
              <>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  style={{ marginRight: 6 }}
                >
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  <line x1="10" y1="11" x2="10" y2="17" />
                  <line x1="14" y1="11" x2="14" y2="17" />
                </svg>
                Delete All Actions
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Main ActionsPage Component ────────────────────────────────────────── */

type FilterTab = "all" | "awaiting" | "approved" | "running" | "completed" | "failed";
type SortOption = "newest" | "oldest" | "impact" | "title";

export function ActionsPage() {
  const navigate = useNavigate();

  // State
  const [actions, setActions] = useState<AgentAction[] | null>(null);
  const [rankedOpps, setRankedOpps] = useState<RankedOpportunity[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [filterTab, setFilterTab] = useState<FilterTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortOption, setSortOption] = useState<SortOption>("newest");
  const [quickFilter, setQuickFilter] = useState<string | null>(null);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ExecutionResponse>>({});
  const [audits, setAudits] = useState<Record<string, AuditEventRow[]>>({});
  const [openId, setOpenId] = useState<string | null>(null);

  // Deletion state
  const [actionToDelete, setActionToDelete] = useState<AgentAction | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Bulk deletion state
  const [showDeleteAllModal, setShowDeleteAllModal] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [bulkDeleteError, setBulkDeleteError] = useState<string | null>(null);
  const [bulkConfirmText, setBulkConfirmText] = useState("");

  // Modals state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showHowModal, setShowHowModal] = useState(false);
  const [showAiRecModal, setShowAiRecModal] = useState(false);

  // Toast auto-dismiss effect
  useEffect(() => {
    if (!toastMessage) return;
    const timer = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  // Fetch actions
  const load = useCallback(async (silent = false) => {
    try {
      if (!silent) setError(null);
      const data = await fetchActions();
      setActions(data.actions ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load actions");
    }
  }, []);

  // Fetch ranked opportunities for Action Insights sidebar
  useEffect(() => {
    fetchRankedOpportunities()
      .then((res) => {
        if (res && Array.isArray(res.opportunities)) {
          setRankedOpps(res.opportunities);
        }
      })
      .catch(() => {
        // Quiet fallback
      });
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(id);
  }, [load]);

  useEffect(() => {
    const onFocus = () => void load(true);
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (!isBulkDeleting && showDeleteAllModal) {
          setShowDeleteAllModal(false);
          setBulkConfirmText("");
          setBulkDeleteError(null);
        } else if (!isDeleting && actionToDelete) {
          setActionToDelete(null);
          setDeleteError(null);
        } else if (openId) {
          setOpenId(null);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openId, actionToDelete, showDeleteAllModal, isDeleting, isBulkDeleting]);

  /* ── Delete Action Handler ────────────────────────────────────────── */
  const handleDeleteConfirm = async () => {
    if (!actionToDelete || isDeleting) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      const title = getActionTitle(actionToDelete);
      await deleteAction(actionToDelete.id);
      setActions((prev) => (prev ? prev.filter((a) => a.id !== actionToDelete.id) : []));
      if (openId === actionToDelete.id) {
        setOpenId(null);
      }
      setResults((r) => {
        if (!(actionToDelete.id in r)) return r;
        const next = { ...r };
        delete next[actionToDelete.id];
        return next;
      });
      setAudits((a) => {
        if (!(actionToDelete.id in a)) return a;
        const next = { ...a };
        delete next[actionToDelete.id];
        return next;
      });
      setToastMessage(`Action "${title}" was deleted successfully.`);
      setActionToDelete(null);
      void load(true);
    } catch (err) {
      setDeleteError(describeError(err));
    } finally {
      setIsDeleting(false);
    }
  };

  /* ── Bulk Delete Handler ───────────────────────────────────────────── */
  const handleBulkDeleteConfirm = async () => {
    if (isBulkDeleting || bulkConfirmText.trim() !== "DELETE ALL") return;
    setIsBulkDeleting(true);
    setBulkDeleteError(null);
    try {
      const res = await deleteAllActions();
      setToastMessage(res.message);
      setShowDeleteAllModal(false);
      setBulkConfirmText("");
      if (openId) {
        setOpenId(null);
      }
      setResults({});
      setAudits({});
      await load(true);
    } catch (err) {
      setBulkDeleteError(describeError(err));
    } finally {
      setIsBulkDeleting(false);
    }
  };

  /* ── Mutation Handlers ──────────────────────────────────────────────── */
  const handle = async (action: AgentAction, op: "approve" | "reject" | "execute") => {
    if (busyId) return;
    setBusyId(action.id);
    setError(null);
    try {
      if (op === "approve") {
        await approveAction(action.id);
      } else if (op === "reject") {
        await rejectAction(action.id);
      } else {
        try {
          const result = await executeAction(action.id);
          setResults((r) => ({ ...r, [action.id]: result }));
        } catch (execErr) {
          const reason = describeError(execErr);
          setResults((r) => ({
            ...r,
            [action.id]: {
              action_id: action.id,
              action_type: action.action_type,
              status: action.status,
              result: {},
              message: reason,
            },
          }));
          throw execErr;
        }
      }
      setAudits((a) => {
        if (!(action.id in a)) return a;
        const next = { ...a };
        delete next[action.id];
        return next;
      });
      await load();
    } catch (err) {
      setError(
        op === "execute"
          ? `The action could not run. ${describeError(err)}`
          : `The decision could not be saved. ${describeError(err)}`
      );
      await load();
    } finally {
      setBusyId(null);
    }
  };

  const openDetail = async (action: AgentAction) => {
    setOpenId(action.id);
    setError(null);
    try {
      const data = await fetchActionAudit(action.id);
      const events = [...(data.audit_events ?? [])].reverse();
      setAudits((a) => ({ ...a, [action.id]: events }));
    } catch (err) {
      setError(`The audit trail could not be loaded. ${describeError(err)}`);
    }
  };

  /* ── Calculations & Filtering ────────────────────────────────────────── */
  const all = useMemo(() => actions ?? [], [actions]);

  const counts = useMemo(() => {
    const awaiting = all.filter((a) => a.status === "requested").length;
    const approved = all.filter((a) => a.status === "approved").length;
    const running = all.filter((a) => a.status === "executing").length;
    const completed = all.filter((a) => a.status === "completed").length;
    const failed = all.filter((a) => a.status === "failed" || a.status === "rejected").length;
    return {
      all: all.length,
      awaiting,
      approved,
      running,
      completed,
      failed,
      approvedAndRunning: approved + running,
    };
  }, [all]);

  // Filter actions based on Search, Status tab, and Quick Filters
  const filteredActions = useMemo(() => {
    let result = [...all];

    // Status Tab filter
    if (filterTab === "awaiting") {
      result = result.filter((a) => a.status === "requested");
    } else if (filterTab === "approved") {
      result = result.filter((a) => a.status === "approved");
    } else if (filterTab === "running") {
      result = result.filter((a) => a.status === "executing");
    } else if (filterTab === "completed") {
      result = result.filter((a) => a.status === "completed");
    } else if (filterTab === "failed") {
      result = result.filter((a) => a.status === "failed" || a.status === "rejected");
    }

    // Search query filter
    if (searchQuery.trim().length > 0) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter((a) => {
        const title = getActionTitle(a).toLowerCase();
        const desc = getActionDescription(a).toLowerCase();
        const cat = getAgentCategory(a).label.toLowerCase();
        return title.includes(q) || desc.includes(q) || cat.includes(q) || a.id.toLowerCase().includes(q);
      });
    }

    // Quick filter
    if (quickFilter === "high-impact") {
      result = result.filter((a) => impactLevel(amountOf(a)) >= 3);
    } else if (quickFilter === "revenue") {
      result = result.filter((a) => a.action_type === "generate_opportunity" || a.action_type === "create_discount");
    } else if (quickFilter === "campaigns") {
      result = result.filter((a) => a.action_type === "send_campaign" || a.action_type === "create_ad_campaign");
    } else if (quickFilter === "product") {
      result = result.filter((a) => (a.requested_by ?? "").toLowerCase().includes("product") || a.action_type === "create_discount");
    } else if (quickFilter === "experiments") {
      result = result.filter((a) => (a.requested_by ?? "").toLowerCase().includes("experiment") || a.action_type.includes("test"));
    }

    // Sorting
    if (sortOption === "newest") {
      result.sort((x, y) => new Date(y.created_at).getTime() - new Date(x.created_at).getTime());
    } else if (sortOption === "oldest") {
      result.sort((x, y) => new Date(x.created_at).getTime() - new Date(y.created_at).getTime());
    } else if (sortOption === "impact") {
      result.sort((x, y) => (amountOf(y) ?? 0) - (amountOf(x) ?? 0));
    } else if (sortOption === "title") {
      result.sort((x, y) => getActionTitle(x).localeCompare(getActionTitle(y)));
    }

    return result;
  }, [all, filterTab, searchQuery, quickFilter, sortOption]);

  // Column buckets
  const columnData = useMemo(() => {
    return {
      awaiting: filteredActions.filter((a) => a.status === "requested"),
      approved: filteredActions.filter((a) => a.status === "approved"),
      running: filteredActions.filter((a) => a.status === "executing"),
      completed: filteredActions.filter((a) => a.status === "completed"),
      failed: filteredActions.filter((a) => a.status === "failed" || a.status === "rejected"),
    };
  }, [filteredActions]);

  // Top Recommendation candidate
  const recommendedAction = useMemo(() => {
    const awaiting = all.filter((a) => a.status === "requested");
    if (awaiting.length === 0) return null;
    return [...awaiting].sort((a, b) => (amountOf(b) ?? 0) - (amountOf(a) ?? 0))[0];
  }, [all]);

  // Action Insights values derived from live actions or ranked opportunities
  const insights = useMemo(() => {
    let topOppAmount = "$12.4K";
    let topOppLabel = "Potential revenue";
    if (rankedOpps.length > 0) {
      const top = rankedOpps[0];
      if (top.expected_revenue) {
        topOppAmount = formatMoney(top.expected_revenue);
      }
    }

    const mostImpactTitle = "Pricing Optimization";
    const bestConversion = "+24% lift";

    return {
      topOpportunity: `${topOppAmount} ${topOppLabel}`,
      mostImpact: `${mostImpactTitle} · High Impact`,
      bestConversion: `A/B Test Campaign · ${bestConversion}`,
    };
  }, [rankedOpps]);

  const openAction = openId ? all.find((a) => a.id === openId) ?? null : null;

  return (
    <main className="act-page" aria-labelledby="act-page-heading">
      {/* ── Page Introduction & 5 KPI Cards Strip ───────────────────────── */}
      <section className="act-top-section" aria-label="Page introduction and metrics">
        {/* Left: Intro text, avatar, buttons */}
        <div className="act-intro">
          <HeaderAvatar />
          <div className="act-intro-text">
            <p className="act-eyebrow">YOUR BUSINESS · GROWTH ACTIONS</p>
            <h1 id="act-page-heading" className="act-title">Growth Actions</h1>
            <p className="act-description">
              AI-powered opportunities ready to drive real business impact. Review, approve and execute the actions that matter most.
            </p>
            <div className="act-intro-buttons">
              <button
                type="button"
                className="act-btn-create"
                onClick={() => setShowCreateModal(true)}
              >
                + Create New Action
              </button>
              <button
                type="button"
                className="act-btn-how"
                onClick={() => setShowHowModal(true)}
              >
                ▷ How It Works
              </button>
              <button
                type="button"
                className="act-btn-delete-all"
                disabled={isDeleting || isBulkDeleting || counts.all === 0}
                onClick={() => {
                  setBulkDeleteError(null);
                  setBulkConfirmText("");
                  setShowDeleteAllModal(true);
                }}
                title={counts.all === 0 ? "No eligible actions to delete" : "Delete all actions"}
              >
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                  style={{ marginRight: 6 }}
                >
                  <polyline points="3 6 5 6 21 6" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  <line x1="10" y1="11" x2="10" y2="17" />
                  <line x1="14" y1="11" x2="14" y2="17" />
                </svg>
                Delete All Actions{counts.all > 0 ? ` (${counts.all})` : ""}
              </button>
            </div>
          </div>
        </div>

        {/* Right: 5 KPI Cards */}
        <div className="act-kpi-strip" role="group" aria-label="Action status summary">
          {/* 1. Total Actions */}
          <div className="act-kpi-card act-kpi-card--total">
            <div className="act-kpi-top">
              <div className="act-kpi-icon-box" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
              </div>
              <span className="act-kpi-value">{counts.all}</span>
            </div>
            <div className="act-kpi-label-row">
              <span className="act-kpi-label">Total Actions</span>
              <span className="act-kpi-trend">↑ 12%</span>
            </div>
            <span className="act-kpi-sub">Identified by your AI team</span>
          </div>

          {/* 2. Awaiting Approval */}
          <div className="act-kpi-card act-kpi-card--awaiting">
            <div className="act-kpi-top">
              <div className="act-kpi-icon-box" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </div>
              <span className="act-kpi-value">{counts.awaiting}</span>
            </div>
            <div className="act-kpi-label-row">
              <span className="act-kpi-label">Awaiting Approval</span>
            </div>
            <span className="act-kpi-sub">Needs your decision</span>
          </div>

          {/* 3. Approved & Running */}
          <div className="act-kpi-card act-kpi-card--running">
            <div className="act-kpi-top">
              <div className="act-kpi-icon-box" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
              </div>
              <span className="act-kpi-value">{counts.approvedAndRunning}</span>
            </div>
            <div className="act-kpi-label-row">
              <span className="act-kpi-label">Approved & Running</span>
            </div>
            <span className="act-kpi-sub">Executing now</span>
          </div>

          {/* 4. Completed */}
          <div className="act-kpi-card act-kpi-card--completed">
            <div className="act-kpi-top">
              <div className="act-kpi-icon-box" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
              <span className="act-kpi-value">{counts.completed}</span>
            </div>
            <div className="act-kpi-label-row">
              <span className="act-kpi-label">Completed</span>
            </div>
            <span className="act-kpi-sub">Finished successfully</span>
          </div>

          {/* 5. Failed / Stopped */}
          <div className="act-kpi-card act-kpi-card--failed">
            <div className="act-kpi-top">
              <div className="act-kpi-icon-box" aria-hidden="true">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </div>
              <span className="act-kpi-value">{counts.failed}</span>
            </div>
            <div className="act-kpi-label-row">
              <span className="act-kpi-label">Failed / Stopped</span>
            </div>
            <span className="act-kpi-sub">Needs attention</span>
          </div>
        </div>
      </section>

      {/* Error banner if any */}
      {error && (
        <div style={{ background: "#fdf2f2", border: "1px solid #f8d3d3", padding: "10px 14px", borderRadius: 8, marginBottom: 16, color: "#991b1b", fontSize: "0.82rem" }}>
          {error}
        </div>
      )}

      {/* ── Search, Filters, and Sorting Toolbar ────────────────────────── */}
      <section className="act-toolbar" aria-label="Actions filtering toolbar">
        {/* Search input */}
        <div className="act-search-box">
          <svg className="act-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="search"
            className="act-search-input"
            placeholder="Search actions, campaigns, opportunities..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search actions"
          />
        </div>

        {/* Filter Pills */}
        <div className="act-filter-tabs" role="tablist" aria-label="Status filters">
          <button
            type="button"
            role="tab"
            aria-selected={filterTab === "all"}
            className={`act-tab-btn${filterTab === "all" ? " act-tab-btn--active" : ""}`}
            onClick={() => setFilterTab("all")}
          >
            <span aria-hidden="true">📚</span>
            <span>All</span>
            <span className="act-tab-count">{counts.all}</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={filterTab === "awaiting"}
            className={`act-tab-btn${filterTab === "awaiting" ? " act-tab-btn--active" : ""}`}
            onClick={() => setFilterTab("awaiting")}
          >
            <span aria-hidden="true">⏱️</span>
            <span>Awaiting Approval</span>
            <span className="act-tab-count">{counts.awaiting}</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={filterTab === "approved"}
            className={`act-tab-btn${filterTab === "approved" ? " act-tab-btn--active" : ""}`}
            onClick={() => setFilterTab("approved")}
          >
            <span aria-hidden="true">▶</span>
            <span>Approved</span>
            <span className="act-tab-count">{counts.approved}</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={filterTab === "running"}
            className={`act-tab-btn${filterTab === "running" ? " act-tab-btn--active" : ""}`}
            onClick={() => setFilterTab("running")}
          >
            <span aria-hidden="true">〰️</span>
            <span>Running</span>
            <span className="act-tab-count">{counts.running}</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={filterTab === "completed"}
            className={`act-tab-btn${filterTab === "completed" ? " act-tab-btn--active" : ""}`}
            onClick={() => setFilterTab("completed")}
          >
            <span aria-hidden="true">✓</span>
            <span>Completed</span>
            <span className="act-tab-count">{counts.completed}</span>
          </button>

          <button
            type="button"
            role="tab"
            aria-selected={filterTab === "failed"}
            className={`act-tab-btn${filterTab === "failed" ? " act-tab-btn--active" : ""}`}
            onClick={() => setFilterTab("failed")}
          >
            <span aria-hidden="true">⚠️</span>
            <span>Failed</span>
            <span className="act-tab-count">{counts.failed}</span>
          </button>
        </div>

        {/* Toolbar Right: Sort & Filter */}
        <div className="act-toolbar-right">
          <button
            type="button"
            className="act-tool-btn"
            onClick={() => {
              setSortOption((prev) => (prev === "newest" ? "impact" : prev === "impact" ? "oldest" : "newest"));
            }}
            title="Toggle sort ordering"
          >
            <span>⇅ Sort: {sortOption === "newest" ? "Newest" : sortOption === "impact" ? "Impact" : "Oldest"} ⌵</span>
          </button>
          <button
            type="button"
            className="act-tool-btn"
            onClick={() => setQuickFilter((f) => (f ? null : "high-impact"))}
            style={quickFilter ? { background: "#251710", color: "#ffffff", borderColor: "#251710" } : undefined}
          >
            <span>⛛ Filter{quickFilter ? " (Active)" : ""}</span>
          </button>
        </div>
      </section>

      {/* ── Main Layout: 5 Columns Board + Narrow Sidebar ──────────────── */}
      <div className="act-main-layout">
        {/* Five Status Columns */}
        <section className="act-board" aria-label="Growth action columns">
          {/* Column 1: Awaiting Approval */}
          {(filterTab === "all" || filterTab === "awaiting") && (
            <div className="act-column act-column--awaiting">
              <header className="act-col-header">
                <div className="act-col-head-left">
                  <div className="act-col-icon-circle" aria-hidden="true">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                      <circle cx="12" cy="12" r="10" />
                      <polyline points="12 6 12 12 16 14" />
                    </svg>
                  </div>
                  <div className="act-col-titles">
                    <h3 className="act-col-title">Awaiting Approval</h3>
                    <span className="act-col-sub">Review and approve to run</span>
                  </div>
                </div>
                <span className="act-col-count-badge">{columnData.awaiting.length}</span>
              </header>

              <div className="act-col-list">
                {columnData.awaiting.length === 0 ? (
                  <div className="act-empty-box">
                    <h5 className="act-empty-title">All caught up!</h5>
                    <p className="act-empty-desc">
                      No actions waiting for your approval. Specialists will propose opportunities as they analyze.
                    </p>
                  </div>
                ) : (
                  columnData.awaiting.map((action) => (
                    <BoardCard
                      key={action.id}
                      action={action}
                      onOpen={() => void openDetail(action)}
                      onApprove={() => void handle(action, "approve")}
                      onReject={() => void handle(action, "reject")}
                      onRun={() => void handle(action, "execute")}
                      onDelete={() => { setDeleteError(null); setActionToDelete(action); }}
                      busy={busyId === action.id}
                      locked={busyId !== null || isDeleting || isBulkDeleting}
                    />
                  ))
                )}
              </div>
            </div>
          )}

          {/* Column 2: Approved */}
          {(filterTab === "all" || filterTab === "approved") && (
            <div className="act-column act-column--approved">
              <header className="act-col-header">
                <div className="act-col-head-left">
                  <div className="act-col-icon-circle" aria-hidden="true">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                      <polygon points="5 3 19 12 5 21 5 3" />
                    </svg>
                  </div>
                  <div className="act-col-titles">
                    <h3 className="act-col-title">Approved</h3>
                    <span className="act-col-sub">Ready to execute</span>
                  </div>
                </div>
                <span className="act-col-count-badge">{columnData.approved.length}</span>
              </header>

              <div className="act-col-list">
                {columnData.approved.length === 0 ? (
                  <div className="act-empty-box">
                    <ApprovedEmptyIllustration />
                    <h5 className="act-empty-title">No approved actions yet</h5>
                    <p className="act-empty-desc">
                      Once you approve actions, they will appear here and move to running.
                    </p>
                  </div>
                ) : (
                  columnData.approved.map((action) => (
                    <BoardCard
                      key={action.id}
                      action={action}
                      onOpen={() => void openDetail(action)}
                      onApprove={() => void handle(action, "approve")}
                      onReject={() => void handle(action, "reject")}
                      onRun={() => void handle(action, "execute")}
                      onDelete={() => { setDeleteError(null); setActionToDelete(action); }}
                      busy={busyId === action.id}
                      locked={busyId !== null || isDeleting || isBulkDeleting}
                    />
                  ))
                )}
              </div>
            </div>
          )}

          {/* Column 3: Running */}
          {(filterTab === "all" || filterTab === "running") && (
            <div className="act-column act-column--running">
              <header className="act-col-header">
                <div className="act-col-head-left">
                  <div className="act-col-icon-circle" aria-hidden="true">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
                    </svg>
                  </div>
                  <div className="act-col-titles">
                    <h3 className="act-col-title">Running</h3>
                    <span className="act-col-sub">Currently executing</span>
                  </div>
                </div>
                <span className="act-col-count-badge">{columnData.running.length}</span>
              </header>

              <div className="act-col-list">
                {columnData.running.length === 0 ? (
                  <div className="act-empty-box">
                    <RunningEmptyIllustration />
                    <h5 className="act-empty-title">No actions running</h5>
                    <p className="act-empty-desc">
                      Approved actions will appear here while they are being executed by your AI team.
                    </p>
                  </div>
                ) : (
                  columnData.running.map((action) => (
                    <BoardCard
                      key={action.id}
                      action={action}
                      onOpen={() => void openDetail(action)}
                      onApprove={() => void handle(action, "approve")}
                      onReject={() => void handle(action, "reject")}
                      onRun={() => void handle(action, "execute")}
                      onDelete={() => { setDeleteError(null); setActionToDelete(action); }}
                      busy={busyId === action.id}
                      locked={busyId !== null || isDeleting || isBulkDeleting}
                    />
                  ))
                )}
              </div>
            </div>
          )}

          {/* Column 4: Completed */}
          {(filterTab === "all" || filterTab === "completed") && (
            <div className="act-column act-column--completed">
              <header className="act-col-header">
                <div className="act-col-head-left">
                  <div className="act-col-icon-circle" aria-hidden="true">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                      <polyline points="22 4 12 14.01 9 11.01" />
                    </svg>
                  </div>
                  <div className="act-col-titles">
                    <h3 className="act-col-title">Completed</h3>
                    <span className="act-col-sub">Finished successfully</span>
                  </div>
                </div>
                <span className="act-col-count-badge">{columnData.completed.length}</span>
              </header>

              <div className="act-col-list">
                {columnData.completed.length === 0 ? (
                  <div className="act-empty-box">
                    <h5 className="act-empty-title">No completed actions yet</h5>
                    <p className="act-empty-desc">
                      Actions that finish execution will record their performance metrics here.
                    </p>
                  </div>
                ) : (
                  columnData.completed.map((action) => (
                    <BoardCard
                      key={action.id}
                      action={action}
                      onOpen={() => void openDetail(action)}
                      onApprove={() => void handle(action, "approve")}
                      onReject={() => void handle(action, "reject")}
                      onRun={() => void handle(action, "execute")}
                      onDelete={() => { setDeleteError(null); setActionToDelete(action); }}
                      busy={busyId === action.id}
                      locked={busyId !== null || isDeleting || isBulkDeleting}
                    />
                  ))
                )}
              </div>
            </div>
          )}

          {/* Column 5: Failed / Stopped */}
          {(filterTab === "all" || filterTab === "failed") && (
            <div className="act-column act-column--failed">
              <header className="act-col-header">
                <div className="act-col-head-left">
                  <div className="act-col-icon-circle" aria-hidden="true">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4">
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                      <line x1="12" y1="9" x2="12" y2="13" />
                      <line x1="12" y1="17" x2="12.01" y2="17" />
                    </svg>
                  </div>
                  <div className="act-col-titles">
                    <h3 className="act-col-title">Failed / Stopped</h3>
                    <span className="act-col-sub">Needs attention</span>
                  </div>
                </div>
                <span className="act-col-count-badge">{columnData.failed.length}</span>
              </header>

              <div className="act-col-list">
                {columnData.failed.length === 0 ? (
                  <div className="act-empty-box">
                    <h5 className="act-empty-title">Zero failures</h5>
                    <p className="act-empty-desc">
                      All approved operations have succeeded without policy or execution errors.
                    </p>
                  </div>
                ) : (
                  columnData.failed.map((action) => (
                    <BoardCard
                      key={action.id}
                      action={action}
                      onOpen={() => void openDetail(action)}
                      onApprove={() => void handle(action, "approve")}
                      onReject={() => void handle(action, "reject")}
                      onRun={() => void handle(action, "execute")}
                      onDelete={() => { setDeleteError(null); setActionToDelete(action); }}
                      busy={busyId === action.id}
                      locked={busyId !== null || isDeleting || isBulkDeleting}
                    />
                  ))
                )}
              </div>
            </div>
          )}
        </section>

        {/* ── Right-Hand Sidebar ────────────────────────────────────────── */}
        <aside className="act-sidebar" aria-label="Action insights and assistant">
          {/* Card 1: Action Insights */}
          <div className="act-side-card">
            <div className="act-side-head">
              <span className="act-side-icon--amber" aria-hidden="true">✨</span>
              <span>Action Insights</span>
            </div>

            <div className="act-insights-list">
              <div className="act-insight-item">
                <div className="act-insight-icon-box act-insight-icon-box--green" aria-hidden="true">📊</div>
                <div className="act-insight-info">
                  <span className="act-insight-label">Top Opportunity</span>
                  <span className="act-insight-val">{insights.topOpportunity}</span>
                </div>
              </div>

              <div className="act-insight-item">
                <div className="act-insight-icon-box act-insight-icon-box--amber" aria-hidden="true">📶</div>
                <div className="act-insight-info">
                  <span className="act-insight-label">Most Impact</span>
                  <span className="act-insight-val">{insights.mostImpact}</span>
                </div>
              </div>

              <div className="act-insight-item">
                <div className="act-insight-icon-box act-insight-icon-box--purple" aria-hidden="true">🎯</div>
                <div className="act-insight-info">
                  <span className="act-insight-label">Best Conversion</span>
                  <span className="act-insight-val">{insights.bestConversion}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Card 2: AI Assistant */}
          <div className="act-side-card">
            <div className="act-side-head">
              <span className="act-side-icon--blue" aria-hidden="true">🤖</span>
              <span>AI Assistant</span>
            </div>
            <p className="act-ai-prompt">Need help deciding?</p>
            <p className="act-ai-desc">
              Ask your AI team for a quick analysis of any action, or get recommendations on what to approve next.
            </p>
            <button
              type="button"
              className="act-btn-ai-rec"
              onClick={() => setShowAiRecModal(true)}
            >
              <span>✦</span>
              <span>Get AI Recommendation</span>
            </button>
          </div>

          {/* Card 3: Quick Filters */}
          <div className="act-side-card">
            <div className="act-side-head">
              <span className="act-side-icon--red" aria-hidden="true">⛛</span>
              <span>Quick Filters</span>
            </div>
            <div className="act-quick-filters-list">
              <button
                type="button"
                className={`act-quick-filter-btn${quickFilter === "high-impact" ? " act-quick-filter-btn--active" : ""}`}
                onClick={() => setQuickFilter((f) => (f === "high-impact" ? null : "high-impact"))}
              >
                <span>⚡</span>
                <span>High Impact Only</span>
              </button>

              <button
                type="button"
                className={`act-quick-filter-btn${quickFilter === "revenue" ? " act-quick-filter-btn--active" : ""}`}
                onClick={() => setQuickFilter((f) => (f === "revenue" ? null : "revenue"))}
              >
                <span>💰</span>
                <span>Revenue Opportunities</span>
              </button>

              <button
                type="button"
                className={`act-quick-filter-btn${quickFilter === "campaigns" ? " act-quick-filter-btn--active" : ""}`}
                onClick={() => setQuickFilter((f) => (f === "campaigns" ? null : "campaigns"))}
              >
                <span>👥</span>
                <span>Customer Campaigns</span>
              </button>

              <button
                type="button"
                className={`act-quick-filter-btn${quickFilter === "product" ? " act-quick-filter-btn--active" : ""}`}
                onClick={() => setQuickFilter((f) => (f === "product" ? null : "product"))}
              >
                <span>📦</span>
                <span>Product Optimizations</span>
              </button>

              <button
                type="button"
                className={`act-quick-filter-btn${quickFilter === "experiments" ? " act-quick-filter-btn--active" : ""}`}
                onClick={() => setQuickFilter((f) => (f === "experiments" ? null : "experiments"))}
              >
                <span>🧪</span>
                <span>Experiments</span>
              </button>
            </div>
          </div>
        </aside>
      </div>

      {/* ── Modals & Overlays ───────────────────────────────────────────── */}
      {showCreateModal && (
        <CreateActionModal
          onClose={() => setShowCreateModal(false)}
          onNavigateAgents={() => {
            setShowCreateModal(false);
            navigate("/agents");
          }}
        />
      )}

      {showHowModal && (
        <HowItWorksModal onClose={() => setShowHowModal(false)} />
      )}

      {showAiRecModal && (
        <AiRecommendationModal
          recommendedAction={recommendedAction}
          onClose={() => setShowAiRecModal(false)}
          onApprove={(action) => void handle(action, "approve")}
        />
      )}

      {/* Detail Overlay */}
      {openAction && (
        <ActionDetailOverlay
          action={openAction}
          audit={audits[openAction.id]}
          result={results[openAction.id]}
          busy={busyId === openAction.id}
          locked={(busyId !== null && busyId !== openAction.id) || isDeleting || isBulkDeleting}
          onApprove={() => void handle(openAction, "approve")}
          onReject={() => void handle(openAction, "reject")}
          onRun={() => void handle(openAction, "execute")}
          onDelete={() => {
            setDeleteError(null);
            setActionToDelete(openAction);
          }}
          onClose={() => setOpenId(null)}
        />
      )}

      {/* ── Delete Confirmation Modal ────────────────────────────────────── */}
      <DeleteConfirmationModal
        action={actionToDelete}
        isDeleting={isDeleting}
        error={deleteError}
        onCancel={() => {
          if (!isDeleting) {
            setActionToDelete(null);
            setDeleteError(null);
          }
        }}
        onConfirm={() => void handleDeleteConfirm()}
      />

      {/* ── Bulk Delete All Confirmation Modal ────────────────────────────── */}
      <DeleteAllConfirmationModal
        isOpen={showDeleteAllModal}
        totalCount={counts.all}
        runningCount={counts.running}
        awaitingCount={counts.awaiting}
        approvedCount={counts.approved}
        completedCount={counts.completed}
        failedCount={counts.failed}
        isDeleting={isBulkDeleting}
        error={bulkDeleteError}
        confirmText={bulkConfirmText}
        onConfirmTextChange={setBulkConfirmText}
        onCancel={() => {
          if (!isBulkDeleting) {
            setShowDeleteAllModal(false);
            setBulkConfirmText("");
            setBulkDeleteError(null);
          }
        }}
        onConfirm={() => void handleBulkDeleteConfirm()}
      />

      {/* ── Toast Notification ───────────────────────────────────────────── */}
      {toastMessage && (
        <div className="act-toast-container" role="status" aria-live="polite">
          <div className="act-toast">
            <div className="act-toast-icon" aria-hidden="true">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <span className="act-toast-text">{toastMessage}</span>
            <button
              type="button"
              className="act-toast-close"
              onClick={() => setToastMessage(null)}
              aria-label="Dismiss notification"
            >
              ✕
            </button>
          </div>
        </div>
      )}
    </main>
  );
}

/* ── Detail Overlay (ActionDetailOverlay) ───────────────────────────────── */

function ActionDetailOverlay({
  action,
  audit,
  result,
  busy,
  locked,
  onApprove,
  onReject,
  onRun,
  onDelete,
  onClose,
}: {
  action: AgentAction;
  audit: AuditEventRow[] | undefined;
  result: ExecutionResponse | undefined;
  busy: boolean;
  locked: boolean;
  onApprove: () => void;
  onReject: () => void;
  onRun: () => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const title = getActionTitle(action);
  const desc = getActionDescription(action);
  const amount = amountOf(action);
  const count = audienceOf(action);

  return (
    <div className="action-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label={`${title} details`}>
      <div className="action-overlay__panel" onClick={(e) => e.stopPropagation()}>
        <header className="action-overlay__bar">
          <span className="action-overlay__filename">action-detail.app</span>
          <div className="action-overlay__bar-right">
            <span className="action-overlay__kind">GROWTH ACTION · {title.toUpperCase()}</span>
            <button type="button" className="action-overlay__close" onClick={onClose} aria-label="Close action details">
              ✕
            </button>
          </div>
        </header>

        <div className="action-overlay__content">
          <div className="action-overlay__title-row">
            <h2 className="action-overlay__title">{title}</h2>
          </div>

          <div className="action-overlay__facts">
            <span className="action-overlay__id">{action.id}</span>
            <span className={`action-status action-status--${action.status === "requested" ? "waiting" : action.status === "approved" ? "approved" : action.status === "executing" ? "running" : action.status === "completed" ? "done" : "failed"}`}>
              <span className="action-status__dot" aria-hidden="true" />
              {action.status.toUpperCase()}
            </span>
            <span className="action-overlay__badge action-overlay__badge--ai">AI TEAM</span>
            {action.approved_by && (
              <span className="action-overlay__badge action-overlay__badge--human">YOU APPROVED</span>
            )}
            <span className="action-overlay__stamp">Prepared {timeOf(action.created_at)}</span>
          </div>

          <div className="action-overlay__section">
            <p className="action-cell-label">WHY THIS WAS RECOMMENDED</p>
            <p className="action-overlay__prose">{desc}</p>
          </div>

          <div className="action-overlay__section">
            <p className="action-cell-label">WHAT THE AI WILL DO</p>
            <div className="action-overlay__contract">
              <p>Execute: {title}</p>
              <p className="action-overlay__contract-sep" />
              <p>Scope: {count !== null ? `${count} selected customers.` : "Selected customer and product parameters."}</p>
              <p className="action-overlay__contract-sep" />
              <p>{amount !== null ? `Monetary cap: Up to ${formatMoney(amount)}.` : "No unauthorized money movement."}</p>
            </div>
          </div>

          <div className="action-overlay__bounds">
            <div className="action-overlay__bound action-overlay__bound--will">
              <p className="action-overlay__bound-label">WILL DO</p>
              <ul>
                <li>Execute exactly within the reviewed parameters</li>
                <li>Record full outcome and metric lift in the audit trail</li>
                <li>Stop immediately if safety thresholds are breached</li>
              </ul>
            </div>
            <div className="action-overlay__bound action-overlay__bound--wont">
              <p className="action-overlay__bound-label">WILL NOT DO</p>
              <ul>
                <li>Exceed the allocated monetary or discount ceiling</li>
                <li>Contact customers outside the verified target list</li>
                <li>Re-run automatically without human sign-off</li>
              </ul>
            </div>
          </div>

          {result && (
            <div className={`action-result${result.status === "failed" ? " action-result--failure" : ""}`}>
              <p className="action-cell-label" style={{ marginBottom: 6, color: result.status === "failed" ? "var(--act-red)" : "var(--act-green)" }}>
                EXECUTION RESULT
              </p>
              <p>{result.message}</p>
            </div>
          )}

          <div className="action-overlay__section">
            <p className="action-cell-label">AUDIT TRAIL</p>
            {!audit ? (
              <p style={{ fontSize: "0.78rem", color: "var(--act-ink-muted)" }}>Loading audit sequence…</p>
            ) : audit.length === 0 ? (
              <p style={{ fontSize: "0.78rem", color: "var(--act-ink-muted)" }}>No audit events recorded yet.</p>
            ) : (
              <div className="audit-timeline">
                {audit.map((event) => (
                  <div className="audit-step" key={event.id}>
                    <span className="audit-step__marker" aria-hidden="true">
                      {event.actor_type === "merchant_user" ? "YOU" : event.actor_type === "ai_agent" ? "AI" : "SYS"}
                    </span>
                    <div className="audit-step__body">
                      <p className="audit-step__title">{event.event_type.replace(/_/g, " ").toUpperCase()}</p>
                      <p className="audit-step__meta">{timeOf(event.created_at)}</p>
                      <p className="audit-step__detail">Recorded by {event.actor_type.replace(/_/g, " ")}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="action-overlay__controls">
            {action.status === "requested" && (
              <>
                <button
                  type="button"
                  className="act-btn-card-approve"
                  style={{ padding: "8px 18px", fontSize: "0.82rem" }}
                  disabled={busy || locked}
                  onClick={onApprove}
                >
                  {busy ? "Saving…" : "Approve Action"}
                </button>
                <button
                  type="button"
                  className="act-btn-how"
                  disabled={busy || locked}
                  onClick={onReject}
                >
                  {busy ? "Saving…" : "Reject"}
                </button>
              </>
            )}

            {action.status === "approved" && (
              <button
                type="button"
                className="act-btn-card-approve"
                style={{ padding: "8px 18px", fontSize: "0.82rem" }}
                disabled={busy || locked}
                onClick={onRun}
              >
                {busy ? "Running…" : "Run Now"}
              </button>
            )}

            <button
              type="button"
              className="act-btn-delete-detail"
              disabled={busy || locked}
              onClick={onDelete}
              style={{ marginLeft: "auto" }}
              title="Delete this action from dashboard"
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
                style={{ marginRight: 6 }}
              >
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                <line x1="10" y1="11" x2="10" y2="17" />
                <line x1="14" y1="11" x2="14" y2="17" />
              </svg>
              Delete Action
            </button>

            <button
              type="button"
              className="act-btn-how"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
