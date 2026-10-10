/**
 * /product-agent — Product Agent workstation, backed by the real backend.
 *
 * This page renders the backend's read model (GET /api/product-agi/status)
 * and polls a run's state while it executes. There is NO sample data here:
 * every number, product row, finding, recommendation, activity line and
 * platform state on this page came from the Product Agent's MCP tools and
 * its persisted run. When the backend cannot be reached the page says so
 * instead of filling the space.
 *
 * Run lifecycle:
 *   1. load the latest PERSISTED run's read model on mount (state survives
 *      a browser refresh, and viewing the page never creates a run)
 *   2. poll /status on the existing interval while that run executes
 *   3. show the live stage, findings and recommendations as they arrive
 *   4. show approval status straight from the existing Action system
 *
 * This page is a MONITOR, not a trigger. The Product Agent is dispatched
 * by the shared AI Team analysis cycle — Start Analysis on the AI Team
 * page runs the Marketing Agent and the Product Agent together under one
 * cycle id — so there is intentionally no run button here and no way for
 * this page to start a second analysis.
 *
 * Visual system: unchanged. Same illustrated RazorGrowth world, same
 * WindowPanel windows, same cream paper / thin dark borders / terracotta
 * actions / dark green growth language. Only the data source changed.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../components/WindowPanel";
import { Button, ButtonLink } from "../components/Button";
import { GlobalEnvironment } from "../features/public/Environment/GlobalEnvironment";
import {
  DEFAULT_WINDOW_DAYS,
  PREVIEW_TABS,
  UNAVAILABLE,
  confidence,
  count,
  delta,
  duration,
  impactText,
  loadProductAgentDashboard,
  performanceCells,
  previewRows,
  productImage,
  productInitials,
  relativeTime,
  rupees,
  rupeesExact,
  snapshotCells,
  statusLabel,
  categoryLabel,
  type PerfCell,
  type PreviewTab,
  type SnapshotCell,
} from "../lib/productAgent";
import {
  approvalPanelView,
  detectStatusMismatch,
  learningText,
  pollIntervalMs,
  progressSteps,
  recommendationState,
  resolveActionCounts,
  resolveViewState,
  shouldPollRun,
  statusCardView,
  workRowView,
  type ApprovalPanelView,
  type ProgressView,
  type StatusCardView,
  type StatusMismatch,
} from "../lib/productAgentStatus";
import shopifyLogo from "../assets/brands/shopify.svg";
import googleMerchantLogo from "../assets/brands/google-merchant.svg";
import wooLogo from "../assets/brands/woocommerce.svg";
import razorpayLogo from "../assets/brands/razorpay.svg";
import type {
  ProductAgentActivityItem,
  ProductAgentPlatform,
  ProductAgentRecommendation,
  ProductAgentStatusResponse,
} from "../types/api";
import "./ProductAgentPage.css";

/* ── Dashboard UI icons (one stroke family, no new dependency) ────────── */

type UiIconName =
  | "search"
  | "spark"
  | "alert"
  | "bot"
  | "users"
  | "chart"
  | "target"
  | "clock"
  | "check"
  | "box"
  | "doc"
  | "branch";

function UiIcon({ name, size = 20 }: { name: UiIconName; size?: number }) {
  let body: React.ReactNode;
  switch (name) {
    case "search":
      body = (<><circle cx="9" cy="9" r="5.5" /><line x1="13.2" y1="13.2" x2="17" y2="17" /></>);
      break;
    case "spark":
      body = (<path d="M10 2l1.9 5.6 5.6 1.9-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9z" fill="currentColor" stroke="none" />);
      break;
    case "alert":
      body = (<><path d="M10 2.5L18 16.5H2z" /><line x1="10" y1="7.5" x2="10" y2="11.5" /><circle cx="10" cy="14" r="0.7" fill="currentColor" stroke="none" /></>);
      break;
    case "bot":
      body = (<><rect x="4" y="7" width="12" height="9" rx="2.5" /><line x1="10" y1="7" x2="10" y2="3.5" /><circle cx="10" cy="2.8" r="1" fill="currentColor" stroke="none" /><circle cx="7.5" cy="11" r="1" fill="currentColor" stroke="none" /><circle cx="12.5" cy="11" r="1" fill="currentColor" stroke="none" /><line x1="7.5" y1="13.8" x2="12.5" y2="13.8" /></>);
      break;
    case "users":
      body = (<><circle cx="7" cy="7" r="3" /><path d="M1.8 16.5c.8-2.8 2.8-4.2 5.2-4.2s4.4 1.4 5.2 4.2" /><circle cx="14.2" cy="8" r="2.3" /><path d="M14.8 12.6c1.9.3 3.2 1.5 3.7 3.6" /></>);
      break;
    case "chart":
      body = (<><line x1="3" y1="3" x2="3" y2="17" /><line x1="3" y1="17" x2="17" y2="17" /><line x1="7.2" y1="12" x2="7.2" y2="15" strokeWidth={2.2} /><line x1="11.2" y1="8.5" x2="11.2" y2="15" strokeWidth={2.2} /><line x1="15.2" y1="5.5" x2="15.2" y2="15" strokeWidth={2.2} /></>);
      break;
    case "target":
      body = (<><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3.5" /><circle cx="10" cy="10" r="0.8" fill="currentColor" stroke="none" /></>);
      break;
    case "clock":
      body = (<><circle cx="10" cy="10" r="7" /><path d="M10 6.5V10l2.5 1.5" /></>);
      break;
    case "box":
      body = (<><path d="M10 2.5l7 3.5v8l-7 3.5-7-3.5v-8z" /><path d="M3 6l7 3.5L17 6" /><line x1="10" y1="9.5" x2="10" y2="17.5" /></>);
      break;
    case "branch":
      body = (<><line x1="5" y1="2.5" x2="5" y2="12.5" /><circle cx="15" cy="5" r="2.5" /><circle cx="5" cy="15" r="2.5" /><path d="M15 7.5a7.5 7.5 0 0 1-7.5 7.5" /></>);
      break;
    case "doc":
      body = (<><path d="M5 2.5h6.5L15 6v11.5H5z" /><path d="M11.5 2.5V6H15" /><line x1="7.5" y1="10.5" x2="12.5" y2="10.5" /><line x1="7.5" y1="13.5" x2="12.5" y2="13.5" /></>);
      break;
    case "check":
    default:
      body = (<path d="M3.5 10.5l4 4L16.5 5.5" strokeWidth={2.2} />);
      break;
  }
  return (
    <svg
      className="prod-uiicon"
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

/* ── Product office illustration (flat RazorGrowth language) ──────────── */

function ProductOfficeArt() {
  return (
    <svg
      className="prod-art"
      viewBox="0 0 520 360"
      role="img"
      aria-label="Illustrated Product Agent workspace analysing a catalog"
    >
      <rect x="24" y="300" width="472" height="26" fill="#EBD9AE" stroke="#2a1810" strokeWidth="3" />
      <rect x="70" y="96" width="330" height="208" fill="#FFF3DF" stroke="#2a1810" strokeWidth="3" />
      <rect x="70" y="96" width="330" height="40" fill="#21130e" stroke="#2a1810" strokeWidth="3" />
      <text x="235" y="122" textAnchor="middle" fontFamily="'IBM Plex Mono',monospace" fontSize="17" letterSpacing="3" fill="#F7EBD7">
        PRODUCT AGENT
      </text>
      <g stroke="#2a1810" strokeWidth="3">
        <rect x="70" y="136" width="47" height="26" fill="#3E7D58" />
        <rect x="117" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="164" y="136" width="47" height="26" fill="#3E7D58" />
        <rect x="211" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="258" y="136" width="47" height="26" fill="#3E7D58" />
        <rect x="305" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="352" y="136" width="48" height="26" fill="#3E7D58" />
      </g>
      <rect x="96" y="182" width="130" height="102" fill="#F5E6CF" stroke="#2a1810" strokeWidth="3" />
      <line x1="96" y1="210" x2="226" y2="210" stroke="#2a1810" strokeWidth="2.5" />
      <line x1="96" y1="238" x2="226" y2="238" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="104" y="188" width="26" height="20" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="134" y="192" width="22" height="16" fill="#7BA57F" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="160" y="186" width="30" height="22" fill="#E8936B" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="104" y="216" width="30" height="20" fill="#70B88A" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="138" y="220" width="24" height="16" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="166" y="214" width="28" height="22" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="106" y="248" width="40" height="28" rx="5" fill="#EBD9AE" stroke="#2a1810" strokeWidth="2.5" />
      <circle cx="118" cy="260" r="3.5" fill="#2a1810" />
      <circle cx="134" cy="260" r="3.5" fill="#2a1810" />
      <rect x="119" y="267" width="13" height="3" fill="#2a1810" />
      <rect x="242" y="182" width="132" height="122" fill="#F0BC92" stroke="#2a1810" strokeWidth="3" />
      <rect x="252" y="194" width="112" height="64" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="262" y="232" width="12" height="18" fill="#3E7D58" />
      <rect x="280" y="222" width="12" height="28" fill="#3E7D58" />
      <rect x="298" y="212" width="12" height="38" fill="#D97757" />
      <rect x="316" y="226" width="12" height="24" fill="#3E7D58" />
      <polyline points="262,228 286,218 304,222 328,206" fill="none" stroke="#2a1810" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="328" cy="206" r="4" fill="#D97757" stroke="#2a1810" strokeWidth="2" />
      <rect x="252" y="266" width="112" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <text x="308" y="284" textAnchor="middle" fontFamily="'IBM Plex Mono',monospace" fontSize="13" letterSpacing="1" fill="#2a1810">REAL DATA</text>
      <rect x="428" y="230" width="16" height="74" fill="#8C7A66" stroke="#2a1810" strokeWidth="3" />
      <circle cx="436" cy="200" r="34" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      <circle cx="414" cy="216" r="18" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      <g fontFamily="'IBM Plex Mono',monospace" fontSize="12" letterSpacing="2">
        <rect x="34" y="150" width="86" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="77" y="167" textAnchor="middle" fill="#2a1810">CATALOG</text>
        <rect x="404" y="120" width="102" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="455" y="137" textAnchor="middle" fill="#2a1810">ANALYTICS</text>
        <rect x="404" y="262" width="86" height="26" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
        <text x="447" y="279" textAnchor="middle" fill="#21130e">PRICING</text>
        <rect x="34" y="230" width="88" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="78" y="247" textAnchor="middle" fill="#2a1810">INVENTORY</text>
      </g>
      <circle cx="466" cy="52" r="24" fill="#E8936B" stroke="#2a1810" strokeWidth="3" />
    </svg>
  );
}

/**
 * Connected-platform brand marks. Shopify / Google Merchant Center /
 * WooCommerce / Razorpay use their official recognizable brand assets
 * stored locally under src/assets/brands/. Website / Store has no external
 * brand, so it keeps a clean inline storefront glyph.
 *
 * Connection status is rendered from the backend, never from this file.
 */
const CHANNEL_LOGOS: Record<string, string> = {
  shopify: shopifyLogo,
  google_merchant: googleMerchantLogo,
  woocommerce: wooLogo,
  razorpay: razorpayLogo,
};

function ChannelGlyph({ channelKey, channelName }: { channelKey: string; channelName: string }) {
  const ink = "#2a1810";
  const logo = CHANNEL_LOGOS[channelKey];
  if (logo) {
    return (
      <img
        className="prod-channel__logo"
        src={logo}
        alt={`${channelName} logo`}
        width={36}
        height={36}
        loading="lazy"
      />
    );
  }
  return (
    <svg className="prod-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Store icon">
      <path d="M7 15l3-7h20l3 7" fill="none" stroke={ink} strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="9" y="15" width="22" height="16" fill="#FFF3DF" stroke={ink} strokeWidth="2.8" />
      <rect x="17" y="22" width="6" height="9" fill="none" stroke={ink} strokeWidth="2.2" />
    </svg>
  );
}

/* ── Section subcomponents ───────────────────────────────────────────── */

function ProductAgentHero({ live }: { live: boolean }) {
  return (
    <WindowPanel title="product.agent" className="prod-hero">
      <div className="prod-hero__inner">
        <div className="prod-hero__copy">
          <p className="prod-eyebrow">
            PRODUCT AGENT · {live ? "AUTONOMOUS EMPLOYEE" : "AWAITING SHARED ANALYSIS"}
          </p>
          <h1 className="prod-hero__title">
            Your autonomous
            <br />
            <span className="prod-hero__accent">product growth employee.</span>
          </h1>
          <p className="prod-hero__sub">
            Analyses your real product catalog, demand and inventory through the
            shared MCP layer, researches supporting evidence, and prepares
            approval-gated recommendations. Nothing executes without you.
          </p>
        </div>
        <div className="prod-hero__art">
          <ProductOfficeArt />
          <p className="prod-hero__caption">
            <span className="prod-hero__tick" aria-hidden="true" />
            <span>
              Better products
              <br />
              happier customers
              <br />
              higher revenue
            </span>
          </p>
        </div>
      </div>
    </WindowPanel>
  );
}

function AgentStatusCard({
  status,
  card,
  progress,
  onReview,
  onDetails,
}: {
  status: ProductAgentStatusResponse | null;
  card: StatusCardView;
  progress: ProgressView;
  onReview: () => void;
  onDetails: () => void;
}) {
  const m = status?.metrics ?? {};
  const checklist = progress.steps.map((s) => ({
    label: s.label,
    done: s.state === "done",
    now: s.state === "now",
    stopped: s.stopped,
  }));
  const windowDays = status?.catalog?.summary?.window_days ?? DEFAULT_WINDOW_DAYS;

  return (
    <WindowPanel title="agent.status" className="prod-span-status">
      <div className="prod-status__top">
        <span className={`prod-live prod-live--${card.indicator}`}>
          <UiIcon name="bot" size={22} />
          <span
            className={`prod-live__dot prod-live__dot--${card.indicator}`}
            aria-hidden="true"
          />
          {card.pill}
        </span>
        <span className="prod-status__meta">
          {status?.has_run
            ? `Last ${status.llm?.provider ?? "no"}${status.llm?.model ? ` · ${status.llm.model}` : ""} · last ${windowDays} days` +
              (status.analysis_cycle_id
                ? ` · cycle ${status.analysis_cycle_id.slice(0, 8)}…`
                : "")
            : "No run yet"}
        </span>
      </div>
      <div className="prod-status__main">
        <div>
          <h2 className="prod-status__headline">{card.headline}</h2>
          <p className="prod-status__support">{card.support}</p>
          <div className="prod-sec__actions">
            <Button variant="primary" mono onClick={onReview}>
              View Analysis Status →
            </Button>
            <Button variant="secondary" mono onClick={onReview}>
              Review Opportunities →
            </Button>
            <Button variant="secondary" mono onClick={onDetails}>
              View Details
            </Button>
          </div>
        </div>
        <div className="prod-status__check">
          <p className="prod-status__checktitle">{card.hasRun ? card.pill : "NO RUN"}</p>
          <ul className="prod-checklist">
            {checklist.map((c) => (
              <li
                key={c.label}
                className={
                  c.done
                    ? "is-done"
                    : c.stopped
                      ? "is-stopped"
                      : c.now
                        ? "is-now"
                        : undefined
                }
              >
                <span aria-hidden="true">
                  {c.done ? "✓" : c.stopped ? "✕" : c.now ? "○" : "·"}
                </span>{" "}
                {c.label}
              </li>
            ))}
            {checklist.length === 0 && (
              <li>
                <span aria-hidden="true">·</span> No run yet
              </li>
            )}
          </ul>
          <p className="prod-panel__sub">
            {count(m.products_analyzed ?? null)} product(s) analysed ·{" "}
            {count(m.opportunity_count ?? null)} opportunit(ies) ·{" "}
            {count(m.recommendation_count ?? null)} recommendation(s) ·{" "}
            {duration(status?.duration_seconds ?? null)} elapsed
          </p>
        </div>
      </div>
    </WindowPanel>
  );
}

function BusinessSnapshot({ cells }: { cells: SnapshotCell[] }) {
  const icons: UiIconName[] = ["box", "chart", "branch", "target", "alert", "spark"];
  if (cells.length === 0) {
    return (
      <WindowPanel title="business.snapshot" className="prod-span-snapshot">
        <p className="prod-panel__sub">No catalog facts available yet.</p>
      </WindowPanel>
    );
  }
  return (
    <WindowPanel title="business.snapshot" className="prod-span-snapshot">
      <div className="prod-snap">
        {cells.map((m, i) => (
          <div key={m.key} className="prod-snap__cell">
            <span className="prod-snap__value">
              <UiIcon name={icons[i % icons.length]} size={18} />
              {m.value}
            </span>
            <span className="prod-snap__label">{m.label}</span>
            <span className="prod-snap__delta">{m.delta}</span>
          </div>
        ))}
      </div>
      <p className="prod-panel__sub">
        Every figure above is computed from this workspace's own products and
        orders. Nothing is estimated.
      </p>
    </WindowPanel>
  );
}

function AgentProgress({ progress }: { progress: ProgressView }) {
  return (
    <WindowPanel title="agent.progress" className="prod-span-full">
      <ol className="prod-steps" aria-label="Product agent progress">
        {progress.steps.map((s) => (
          <li
            key={s.label}
            className={`prod-steps__step${s.state === "done" ? " is-done" : ""}${
              s.state === "now" ? " is-now" : ""
            }${s.stopped ? " is-stopped" : ""}`}
            aria-current={s.state === "now" ? "step" : undefined}
          >
            <span className="prod-steps__node" aria-hidden="true">
              {s.state === "done" ? (
                <svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true">
                  <path
                    d="M3 8.5l3.5 3.5L13 4.5"
                    fill="none"
                    stroke="#FFF3DF"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              ) : s.stopped ? (
                "✕"
              ) : (
                s.index + 1
              )}
            </span>
            <span className="prod-steps__words">
              <span>{s.top}</span>
              {s.bottom && <span>{s.bottom}</span>}
            </span>
          </li>
        ))}
      </ol>
      <p className="prod-steps__caption">{progress.caption}</p>
    </WindowPanel>
  );
}

function ProductPerformanceSnapshot({ cells, status }: { cells: PerfCell[]; status: ProductAgentStatusResponse | null }) {
  const metrics = status?.metrics ?? {};
  const windowDays = status?.catalog?.summary?.window_days ?? DEFAULT_WINDOW_DAYS;
  return (
    <WindowPanel title="product.performance" className="prod-span-perf">
      <div className="prod-perf">
        {cells.map((c) => (
          <div key={c.key} className="prod-perf__cell">
            <span className="prod-perf__value">{c.value}</span>
            <span className="prod-perf__label">{c.label}</span>
          </div>
        ))}
      </div>
      <p className="prod-perf__insight">
        Demand measured over the last {windowDays} days ·{" "}
        {count(metrics.average_order_value_inr ?? null) !== UNAVAILABLE
          ? `Average order value ${rupees(metrics.average_order_value_inr ?? null)}`
          : "Average order value unavailable — no settled orders in this window"}
        . Competitor pricing and conversion rate are unavailable on this
        platform and are reported as such rather than estimated.
      </p>
    </WindowPanel>
  );
}

function ApprovalRequired({
  recommendations,
  approval,
  onReview,
  onApprove,
}: {
  recommendations: ProductAgentRecommendation[];
  approval: ApprovalPanelView;
  onReview: () => void;
  onApprove: () => void;
}) {
  if (recommendations.length === 0) {
    return (
      <WindowPanel title="approval.required" className="prod-span-perf">
        <div className="prod-sec__head">
          <span className="prod-sec__icon" aria-hidden="true"><UiIcon name="check" size={15} /></span>
          <div>
            <h2 className="prod-sec__title">No recommendations yet</h2>
            <p className="prod-panel__sub">
              Run an analysis. Any recommendation that needs your approval will
              appear here with an explicit status.
            </p>
          </div>
        </div>
      </WindowPanel>
    );
  }
  return (
    <div className="prod-span-approval">
      <WindowPanel
        title="approval.required"
        className={`prod-approval${approval.variant === "hot" ? " prod-approval--hot" : ""}`}
      >
        <div className="prod-approval__head">
          <span className="prod-approval__icon" aria-hidden="true">
            <UiIcon name={approval.icon} size={15} />
          </span>
          <h2 className="prod-approval__title">{approval.title}</h2>
        </div>
        <p className="prod-approval__campaign">{approval.line}</p>
        <p className="prod-approval__meta">{approval.meta}</p>
        <p className="prod-approval__note">
          AI investigates. AI recommends. You approve. Nothing executes without
          your approval.
        </p>
        <div className="prod-approval__actions">
          <Button variant="primary" mono onClick={onReview}>
            Review Actions →
          </Button>
          <Button variant="secondary" mono onClick={onApprove}>
            {approval.actionable ? "Open Approvals" : "Open Actions"}
          </Button>
        </div>
      </WindowPanel>
    </div>
  );
}

function ProductInsights({ insights }: { insights: ProductAgentStatusResponse["insights"] }) {
  const iconFor: Record<string, UiIconName> = {
    top_sellers: "chart",
    never_sold: "alert",
    low_stock: "box",
    content: "doc",
    opportunities: "branch",
    underperforming: "search",
    pricing: "target",
    bundles: "branch",
  };
  if (insights.length === 0) {
    return (
      <WindowPanel title="what.i.found" className="prod-span-third">
        <p className="prod-panel__sub">No findings recorded yet.</p>
      </WindowPanel>
    );
  }
  return (
    <WindowPanel title="what.i.found" className="prod-span-third">
      <div className="prod-sec__head">
        <span className="prod-sec__icon" aria-hidden="true"><UiIcon name="search" size={15} /></span>
        <div>
          <h2 className="prod-sec__title">Top Product Insights</h2>
          <p className="prod-panel__sub">
            Computed from this workspace's catalog, orders and inventory.
          </p>
        </div>
      </div>
      <ul className="prod-found">
        {insights.map((f) => (
          <li key={f.id} className="prod-found__row">
            <span className="prod-found__icon" aria-hidden="true">
              <UiIcon name={iconFor[f.id] ?? "search"} size={15} />
            </span>
            <div>
              <p className="prod-found__value">{f.value}</p>
              <p className="prod-found__label">{f.detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </WindowPanel>
  );
}

function ProductRecommendations({
  recommendations,
  onReview,
  onStrategy,
}: {
  recommendations: ProductAgentRecommendation[];
  onReview: () => void;
  onStrategy: () => void;
}) {
  return (
    <WindowPanel title="my.recommendations" className="prod-span-third">
      {recommendations.length > 0 && <span className="prod-badge">Evidence-backed</span>}
      <div className="prod-sec__head">
        <span className="prod-sec__icon" aria-hidden="true"><UiIcon name="spark" size={15} /></span>
        <div>
          <h2 className="prod-sec__title">
            {recommendations.length > 0
              ? `${recommendations.length} recommendation(s) from the last run`
              : "My recommendations"}
          </h2>
          <p className="prod-panel__sub">
            Each card states its evidence, confidence, risk and approval state.
          </p>
        </div>
      </div>
      {recommendations.length === 0 ? (
        <p className="prod-panel__sub">
          No recommendation could be supported by the available data. Run an
          analysis to produce one, or approve more of them below.
        </p>
      ) : (
        <div className="prod-recs">
          {recommendations.map((r, i) => {
            const recState = recommendationState(r);
            return (
            <div key={r.id} className="prod-rec">
              <span className="prod-rec__label">
                RECOMMENDATION {i + 1} · {r.type.toUpperCase()}
              </span>
              <h3 className="prod-rec__title">{r.title}</h3>
              <p className="prod-rec__text">{r.recommendation}</p>
              <p className="prod-sec__text"><strong>Problem:</strong> {r.problem}</p>
              <p className="prod-sec__text"><strong>Why now:</strong> {r.why_now}</p>
              <div className="prod-rec__meta">
                <span>
                  Impact: <strong>{impactText(r)}</strong>
                </span>
                <span>
                  Confidence: <strong>{confidence(r.confidence)}</strong>
                </span>
              </div>
              <div className="prod-rec__meta">
                <span>
                  Products:{" "}
                  <strong>
                    {r.affected_products.length > 0
                      ? r.affected_products.join(", ")
                      : "Not product-specific"}
                  </strong>
                </span>
                <span>
                  Status:{" "}
                  <strong className={`prod-rec__state prod-rec__state--${recState.tone}`}>
                    {recState.label}
                  </strong>
                </span>
              </div>
              {r.evidence.length > 0 && (
                <details className="prod-sec__block">
                  <summary className="prod-sec__h">
                    Evidence ({r.evidence.length})
                  </summary>
                  <ul className="prod-evidence">
                    {r.evidence.slice(0, 6).map((e, idx) => (
                      <li key={`${r.id}-ev-${idx}`}>
                        {e.statement}
                        {e.tool ? <span className="prod-evidence__tool"> · {e.tool}</span> : null}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {r.risk && (
                <p className="prod-sec__text"><strong>Risk:</strong> {r.risk}</p>
              )}
            </div>
            );
          })}
        </div>
      )}
      <div className="prod-sec__actions">
        <Button variant="primary" mono onClick={onReview}>
          Review Opportunities →
        </Button>
        <Button variant="secondary" mono onClick={onStrategy}>
          View Evidence
        </Button>
      </div>
    </WindowPanel>
  );
}

function ProductPreview({ status }: { status: ProductAgentStatusResponse | null }) {
  const [tab, setTab] = useState<PreviewTab>("Top Products");
  const result = previewRows(status, tab);
  const windowDays = status?.catalog?.summary?.window_days ?? DEFAULT_WINDOW_DAYS;
  return (
    <WindowPanel title="product.preview" className="prod-span-third prod-span-preview">
      <div className="prod-prev__tabs" role="tablist" aria-label="Product preview tabs">
        {PREVIEW_TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`prod-prev__tab${tab === t ? " is-active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {result.rows.length === 0 ? (
        <p className="prod-panel__sub">{result.emptyReason}</p>
      ) : (
        <div className="prod-tablewrap">
          <table className="prod-table">
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Price</th>
                <th scope="col">Stock</th>
                <th scope="col">Units</th>
                <th scope="col">Revenue</th>
                <th scope="col">Trend</th>
              </tr>
            </thead>
            <tbody>
              {result.rows.map((p) => {
                const image = productImage(p);
                return (
                  <tr key={`${tab}-${p.product_id}`}>
                    <td>
                      <span className="prod-table__product">
                        <span className="prod-thumb" aria-hidden="true">
                          {productInitials(p.name)}
                          {image ? (
                            <img
                              src={image}
                              alt=""
                              width={48}
                              height={48}
                              loading="lazy"
                              onError={(e) => {
                                e.currentTarget.style.display = "none";
                              }}
                            />
                          ) : null}
                        </span>
                        <span className="prod-table__name">
                          <span>{p.name}</span>
                          <span className="prod-table__cat">
                            {categoryLabel(p.category)} · {statusLabel(p.status)}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td>{rupeesExact(p.price_inr)}</td>
                    <td>{count(p.stock_quantity)}</td>
                    <td>{count(p.units_sold)}</td>
                    <td>{rupees(p.revenue_inr)}</td>
                    <td>
                      <span className={p.trend_pct != null && p.trend_pct < 0 ? "prod-trend--down" : "prod-trend--up"}>
                        {delta(p.trend_pct)}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="prod-panel__sub">
        {count(status?.catalog?.summary?.product_count ?? null)} real products from
        this workspace · demand measured over the last {windowDays} days.
      </p>
    </WindowPanel>
  );
}

function ProductChannels({ platforms }: { platforms: ProductAgentPlatform[] }) {
  return (
    <WindowPanel title="product.channels" className="prod-span-full">
      <div className="prod-sec__head">
        <div>
          <h2 className="prod-sec__title">Connected Platforms</h2>
          <p className="prod-panel__sub">
            Status is read from real connection and payment records. A platform
            with no integration is reported as not connected.
          </p>
        </div>
      </div>
      <div className="prod-channels">
        {platforms.map((c) => (
          <div key={c.key} className="prod-channel">
            <div className="prod-channel__logozone">
              <ChannelGlyph channelKey={c.key} channelName={c.name} />
            </div>
            <h3 className="prod-channel__name">{c.name}</h3>
            <span className={`prod-channel__pill${c.status === "connected" ? " is-on" : ""}`}>
              {c.status === "connected" ? "Connected" : "Not connected"}
            </span>
            <p className="prod-channel__blurb">{c.blurb}</p>
            <p className="prod-channel__meta">{c.meta}</p>
            <div className="prod-channel__actions">
              {c.status === "connected" ? (
                <span className="prod-stackbtn" aria-disabled="true">
                  Active
                </span>
              ) : (
                <span className="prod-stackbtn" aria-disabled="true">
                  {c.integration_implemented ? "Not connected" : "Not available"}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>
      <p className="prod-panel__sub">
        Shopify, WooCommerce and Google Merchant have no integration in this
        platform yet, so they can never report a connection.
      </p>
    </WindowPanel>
  );
}

function RecentWork({ work }: { work: ProductAgentStatusResponse["work"] }) {
  return (
    <WindowPanel title="recent.work" className="prod-span-half">
      <div className="prod-sec__head prod-sec__head--split">
        <h2 className="prod-sec__title">Run Summary</h2>
        <span className="prod-panel__sub">From the latest run</span>
      </div>
      {work.length === 0 ? (
        <p className="prod-panel__sub">No run recorded yet.</p>
      ) : (
        <ul className="prod-work">
          {work.map((w) => {
            const row = workRowView(w);
            return (
              <li key={row.id}>
                <div className="prod-work__item">
                  <span className="prod-work__icon" aria-hidden="true">
                    <UiIcon name={row.icon} size={17} />
                  </span>
                  <span className="prod-work__title">{row.title}</span>
                  <span className={`prod-work__state prod-work__state--${row.tone}`}>
                    {row.stateLabel}
                  </span>
                  <span className="prod-work__meta">{row.meta}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </WindowPanel>
  );
}

function AgentActivity({ activity }: { activity: ProductAgentActivityItem[] }) {
  return (
    <WindowPanel title="agent.activity" className="prod-span-half">
      <div className="prod-sec__head">
        <span className="prod-live__dot" aria-hidden="true" />
        <h2 className="prod-sec__title">Live activity</h2>
      </div>
      {activity.length === 0 ? (
        <p className="prod-panel__sub">
          No events yet. Activity is emitted by the backend as the run executes.
        </p>
      ) : (
        <ol className="prod-activity">
          {activity.map((a) => (
            <li
              key={a.id}
              className={`prod-activity__row prod-activity__row--${a.state}`}
            >
              <span className="prod-activity__dot" aria-hidden="true" />
              <div>
                <p className="prod-activity__title">{a.title}</p>
                <p className="prod-activity__time">
                  {relativeTime(a.time)} · {a.stage}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </WindowPanel>
  );
}

function LearningCard({ learning, gaps }: { learning: string; gaps: string[] }) {
  return (
    <WindowPanel title="what.im.learning" className="prod-span-full">
      <div className="prod-learnempty">
        <div className="prod-learnempty__copy">
          <h2 className="prod-sec__title prod-ico-title">
            <UiIcon name="spark" size={19} />
            What I&apos;m learning
          </h2>
          <p className="prod-learn__insight">{learning}</p>
          {gaps.length > 0 && (
            <details className="prod-sec__block">
              <summary className="prod-sec__h">Data gaps ({gaps.length})</summary>
              <ul className="prod-evidence">
                {gaps.slice(0, 10).map((g, i) => (
                  <li key={`gap-${i}`}>{g}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <div className="prod-learnempty__visual" aria-hidden="true">
          <span className="prod-learnempty__ring" />
          <p>
            Outcome-driven learning.
            <br />
            <span>Nothing claimed before it is measured.</span>
          </p>
        </div>
      </div>
    </WindowPanel>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <WindowPanel title="agent.status" className="prod-span-full">
      <div className="prod-sec__head">
        <span className="prod-sec__icon" aria-hidden="true"><UiIcon name="alert" size={15} /></span>
        <div>
          <h2 className="prod-sec__title">Product Agent unreachable</h2>
          <p className="prod-panel__sub">{message}</p>
          <p className="prod-panel__sub">
            This page only ever renders backend results, so it shows nothing
            rather than sample data.
          </p>
        </div>
      </div>
      <div className="prod-sec__actions">
        <Button variant="primary" mono onClick={onRetry}>
          Retry →
        </Button>
      </div>
    </WindowPanel>
  );
}

/** A refresh failed while a payload is already on screen: keep the last
 *  known state, say it is not live, and offer a retry. */
function StaleBanner({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <WindowPanel title="refresh.state" className="prod-span-full prod-banner">
      <div className="prod-banner__inner">
        <span className="prod-banner__icon" aria-hidden="true">
          <UiIcon name="alert" size={15} />
        </span>
        <div className="prod-banner__copy">
          <h2 className="prod-sec__title">Could not refresh — showing the last known state</h2>
          <p className="prod-panel__sub">{message}</p>
        </div>
        <Button variant="secondary" mono onClick={onRetry}>
          Retry →
        </Button>
      </div>
    </WindowPanel>
  );
}

/** §11 self-check: fields of one payload that disagree with each other are
 *  reported, never silently reconciled in the browser. */
function MismatchBanner({ items }: { items: StatusMismatch[] }) {
  if (items.length === 0) return null;
  return (
    <WindowPanel title="state.selfcheck" className="prod-span-full prod-banner prod-banner--warn">
      <div className="prod-banner__inner">
        <span className="prod-banner__icon" aria-hidden="true">
          <UiIcon name="alert" size={15} />
        </span>
        <div className="prod-banner__copy">
          <h2 className="prod-sec__title">
            Backend state report — {items.length} contradictory field(s)
          </h2>
          <p className="prod-panel__sub">
            The Product Agent API answered with fields that describe different
            states. Nothing is corrected here: the backend owns the fix, and
            the values below are shown exactly as they arrived.
          </p>
          <ul className="prod-banner__list">
            {items.map((m) => (
              <li key={`${m.field}-${m.found}`}>
                <code>{m.field}</code>: {m.message}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </WindowPanel>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */

export function ProductAgentPage() {
  const navigate = useNavigate();
  const recommendationsRef = useRef<HTMLDivElement | null>(null);
  const detailsRef = useRef<HTMLDivElement | null>(null);

  const [status, setStatus] = useState<ProductAgentStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await loadProductAgentDashboard(DEFAULT_WINDOW_DAYS);
      setStatus(next);
      setError(null);
    } catch (e) {
      setError((e as Error)?.message || "Could not reach the Product Agent API.");
    } finally {
      setLoading(false);
    }
  }, []);

  // 1. Load the latest run on mount. This resolves the PERSISTED run for
  // the shared analysis cycle, so a browser refresh restores real state
  // and no run is ever created by viewing this page.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 2. Poll while the run can still change. Approval, execution and every
  // intermediate state keep the page live; only a terminal run status stops
  // the interval (waiting for a human polls slower than active work).
  useEffect(() => {
    if (!shouldPollRun(status?.status)) return undefined;
    const timer = window.setInterval(() => {
      void refresh();
    }, pollIntervalMs(status?.status));
    return () => window.clearInterval(timer);
  }, [status?.status, refresh]);

  // 3. Coming back to the tab (or another tab approving an action) must not
  // leave this page showing a state that no longer exists.
  useEffect(() => {
    const onFocus = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener("focus", onFocus);
    return () => {
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  // NOTE: this page has no run-triggering handler of any kind. The Product
  // Agent is dispatched by the shared AI Team analysis cycle (AI Team →
  // Start Analysis); this page only reads back that persisted run.

  // One model for every section below: counts → card, tracker, approval
  // panel, recommendation chips, run summary, learning card and footer.
  const counts = useMemo(() => resolveActionCounts(status), [status]);
  const card = useMemo(() => statusCardView(status, counts), [status, counts]);
  const progress = useMemo(() => progressSteps(status, counts), [status, counts]);
  const approval = useMemo(
    () => approvalPanelView(status?.recommendations, counts, card.status),
    [status, counts, card.status],
  );
  const mismatches = useMemo(() => detectStatusMismatch(status, counts), [status, counts]);
  const viewState = resolveViewState({ loading, error, status });

  // Report a contradictory payload (§11) instead of hiding or fixing it.
  useEffect(() => {
    if (mismatches.length > 0) {
      console.warn(
        "[product-agent] status payload disagrees with itself",
        mismatches,
      );
    }
  }, [mismatches]);

  const scrollToRecommendations = () =>
    recommendationsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  const scrollToDetails = () =>
    detailsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const snapshot = snapshotCells(status);
  const perf = performanceCells(status);

  return (
    <div className="prod-world">
      <GlobalEnvironment />
      <div className="prod-shell">
        <ProductAgentHero live={Boolean(status?.has_run)} />

        {viewState === "error" ? (
          <ErrorState
            message={error ?? "Could not reach the Product Agent API."}
            onRetry={() => void refresh()}
          />
        ) : viewState === "loading" ? (
          <WindowPanel title="agent.status" className="prod-span-full">
            <p className="prod-panel__sub">Loading the Product Agent&apos;s real run state…</p>
          </WindowPanel>
        ) : (
          <div className="prod-grid">
            {viewState === "stale" && (
              <StaleBanner message={error ?? "Refresh failed."} onRetry={() => void refresh()} />
            )}
            <MismatchBanner items={mismatches} />

            <AgentStatusCard
              status={status}
              card={card}
              progress={progress}
              onReview={scrollToRecommendations}
              onDetails={scrollToDetails}
            />
            <BusinessSnapshot cells={snapshot} />

            <AgentProgress progress={progress} />
            <ProductPerformanceSnapshot cells={perf} status={status} />
            <ApprovalRequired
              recommendations={status?.recommendations ?? []}
              approval={approval}
              onReview={scrollToRecommendations}
              onApprove={() => navigate("/actions")}
            />

            <div ref={detailsRef} style={{ display: "contents" }} />
            <ProductInsights insights={status?.insights ?? []} />
            <div ref={recommendationsRef} style={{ display: "contents" }} />
            <ProductRecommendations
              recommendations={status?.recommendations ?? []}
              onReview={scrollToRecommendations}
              onStrategy={scrollToDetails}
            />
            <ProductPreview status={status} />

            <ProductChannels platforms={status?.platforms ?? []} />

            <RecentWork work={status?.work ?? []} />
            <AgentActivity activity={status?.activity ?? []} />

            <LearningCard
              learning={learningText(status, counts)}
              gaps={status?.knowledge_gaps ?? []}
            />
          </div>
        )}

        <div className="prod-signoff" aria-label="Product agent footer">
          <span>
            PRODUCT AGENT · {card.footerToken} · HUMAN APPROVAL REQUIRED
          </span>
          <ButtonLink variant="secondary" size="sm" mono to="/agents">
            ← Back to AI Team
          </ButtonLink>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Button variant="secondary" mono onClick={() => navigate("/agents")}>
            Start / View Shared Analysis →
          </Button>
          <Button variant="primary" mono onClick={() => navigate("/actions")}>
            Review &amp; Approve Actions →
          </Button>
        </div>
      </div>
    </div>
  );
}