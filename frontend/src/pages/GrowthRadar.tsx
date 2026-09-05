/**
 * /growth-radar — RazorGrowth's intelligent business command center.
 *
 * Reads real commerce data only. Every number shown is measured from
 * actual payments, orders, and customers — never invented.
 *
 * Reading flow: BUSINESS HEALTH → WHAT THE RADAR FOUND → WHY IT MATTERS
 * → WHAT OPPORTUNITY EXISTS → WHAT TO DO NEXT.
 *
 * MERCHANT LANGUAGE ONLY — no API endpoints, no database terms.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchGrowthRadar } from "../lib/api";
import type { GrowthRadarResponse } from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import "./GrowthRadar.css";

/* ── Formatting helpers ─────────────────────────────────────────────────── */

/** ₹700, ₹12,500.50 — no hardcoded money anywhere. */
function rupees(value: number, decimals = false): string {
  const n = decimals ? value.toFixed(2) : Math.round(value).toLocaleString("en-IN");
  return `₹${n}`;
}

function pct(confidence: number): number {
  return Math.round(confidence * 100);
}

/** "2 payments", "1 payment" */
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

/* ── Plain-English translations of internal signal names ────────────────── */

const SIGNAL_BLURBS: Record<string, string> = {
  revenue_drop:
    "Revenue moved lower than the previous period. Comparing recent payments with the period before shows a drop worth attention.",
  emerging_growth:
    "Revenue moved higher than the previous period. Comparing recent payments with the period before shows momentum worth building on.",
  declining_repeat_purchases:
    "Customers who used to buy again are buying less. Repeat orders from returning customers have fallen compared with the previous period.",
  unusual_order_behavior:
    "Order activity shifted noticeably compared with the previous period — either much higher or much lower than usual.",
  payment_failures:
    "Customers attempted purchases that did not complete successfully. Each failed payment is a customer who wanted to buy.",
  payment_recovery_opportunity:
    "Money was left on the table by unsuccessful payments. A portion of this value can often be recovered with a careful follow-up.",
  abandoned_customers:
    "Previously-active customers have gone quiet. They have a purchase history with your business but have not returned recently.",
};

function signalBlurb(signalKey: string): string {
  return (
    SIGNAL_BLURBS[signalKey] ??
    "The radar compares recent business activity to identify patterns that may deserve attention."
  );
}

/** Human label for what was measured, replacing internal field names. */
const METRIC_LABELS: Record<string, string> = {
  captured_revenue_inr: "revenue received",
  repeat_customer_orders: "repeat purchases",
  order_count: "orders placed",
  failed_payment_value_inr: "unsuccessful payment value",
  recoverable_revenue_inr: "potentially recoverable revenue",
  dormant_customer_count: "quiet returning customers",
};

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? "business activity";
}

/* ── Derived view-model: turn raw metrics into story pieces ─────────────── */

interface HealthStory {
  headline: string;
  needs: boolean; // a warning-worthy signal exists (failed payments etc.)
  failedValue: number | null;
  failedCount: number;
}

function buildHealthStory(radar: GrowthRadarResponse): HealthStory {
  const m = radar.metrics;
  const parts: string[] = [];

  parts.push(
    `Your business has completed ${count(m.captured_transactions, "successful transaction")}` +
      (m.captured_transactions === 1 ? "" : "s") +
      ` and received ${rupees(m.captured_revenue, true)} in revenue,` +
      ` at an average of ${rupees(m.average_order_value, true)} per purchase.` +
      ` ${count(m.total_customers, "customer")}${m.total_customers === 1 ? " has" : "s have"} ordered,` +
      ` across ${count(m.total_orders, "order")} in total.`
  );

  const failureSignal = radar.signals.find(
    (s) => s.signal === "payment_recovery_opportunity" || s.signal === "payment_failures"
  ) ?? null;
  const failedCount = m.failed_payments;
  const failedSignalCount =
    failureSignal && typeof (failureSignal.observed_data as Record<string, unknown>).failed_count === "number"
      ? ((failureSignal.observed_data as Record<string, unknown>).failed_count as number)
      : failedCount;
  const failedValue =
    failureSignal !== null ? signalValue(failureSignal) : null;

  let needs = false;
  if (failedCount > 0) {
    needs = true;
    const valueText = failedValue !== null ? ` totalling ${rupees(failedValue, true)}` : "";
    parts.push(
      ` The main area requiring attention is unsuccessful payments — ${count(failedSignalCount, "payment attempt")}${valueText} that did not complete.`
    );
  }
  if (m.failed_payments === 0 && radar.signals.length === 0) {
    parts.push(" No problem areas were flagged by the radar in this period.");
  }

  return {
    headline: parts.join(""),
    needs,
    failedValue,
    failedCount: failedSignalCount,
  };
}

/** Rank signals so the strongest opportunity leads. */
function rankSignals(radar: GrowthRadarResponse) {
  return [...radar.signals].sort(
    (a, b) => b.confidence - a.confidence || a.signal.localeCompare(b.signal)
  );
}

/** Evidence line for a signal, in merchant language. */
function signalEvidence(signal: GrowthRadarResponse["signals"][number]): string {
  const od = (signal.observed_data ?? {}) as Record<string, unknown>;
  const failedCount = typeof od.failed_count === "number" ? od.failed_count : null;

  if (failedCount !== null) {
    const valueText = signal.calculated_metric.includes("recoverable")
      ? ` worth ${rupees(signalValue(signal), true)}`
      : "";
    return `Observed from recent payment activity — ${count(failedCount, "unsuccessful attempt")}${valueText}.`;
  }

  const cur = numberField(od, "current_window.captured_payments");
  const cmp = numberField(od, "previous_window.captured_payments");
  if (cur !== null && cmp !== null) {
    const diff = cmp > 0 ? ((cur - cmp) / cmp) * 100 : null;
    const dir = diff === null ? "" : diff >= 0 ? "up" : "down";
    return diff === null
      ? `Measured from your recent ${metricLabel(signal.calculated_metric)} — ${cur} recent versus ${cmp} in the previous period.`
      : `Recent ${metricLabel(signal.calculated_metric)} moved ${dir} ${Math.abs(diff).toFixed(1)}% versus the previous period (${cmp} → ${cur}).`;
  }

  const dormant = numberField(od, "recency_cutoff_days");
  if (dormant !== null) {
    return `Measured from your customer order history — customers who had bought before but not in the last ${dormant} days.`;
  }

  return `Measured from your recent ${metricLabel(signal.calculated_metric)} activity compared with the previous period.`;
}

/** Safely pull a numeric value out of observed data (single level or nested). */
function numberField(od: Record<string, unknown>, path: string): number | null {
  const [head, tail] = path.split(".");
  const top = od[head];
  if (tail === undefined) {
    return typeof top === "number" ? top : null;
  }
  if (top && typeof top === "object") {
    const v = (top as Record<string, unknown>)[tail];
    return typeof v === "number" ? v : null;
  }
  return null;
}

/** Numeric evidence carried on a signal (0 when the backend sent none). */
function signalValue(signal: GrowthRadarResponse["signals"][number]): number {
  const od = (signal.observed_data ?? {}) as Record<string, unknown>;
  for (const key of ["failed_payment_value_inr", "recoverable_revenue_inr", "value"]) {
    const v = od[key];
    if (typeof v === "number") return v;
  }
  return 0;
}

/** Potential-impact value for a signal, or null when the evidence carries no rupee value. */
function potentialImpact(signal: GrowthRadarResponse["signals"][number]): number | null {
  const metric = signal.calculated_metric;
  if (metric.includes("revenue") || metric.includes("value")) {
    const v = signalValue(signal);
    return v > 0 ? v : null;
  }
  return null;
}
/** Plain-English display of "why this matters" for an opportunity. */
function opportunityWhy(signalKey: string): string {
  const map: Record<string, string> = {
    payment_failures:
      "Failed payments represent customers who attempted to complete a purchase but were unsuccessful — real buying intent that did not convert.",
    payment_recovery_opportunity:
      "Recent payment activity shows attempted purchases that did not complete successfully. That value may represent revenue worth recovering.",
    revenue_drop:
      "Revenue softened compared with the previous period. Understanding why is the first step to reversing it.",
    emerging_growth:
      "Revenue is accelerating. Doubling down on what is working can compound the gains.",
    declining_repeat_purchases:
      "Returning customers are buying less. Retention is usually cheaper than acquisition.",
    unusual_order_behavior:
      "Order volume shifted noticeably. Confirming whether this is growth or friction protects future revenue.",
    abandoned_customers:
      "Customers with purchase history have gone quiet. They already trust your business — winning them back is often the highest-leverage move.",
  };
  return map[signalKey] ?? "The radar detected a pattern in your business activity that may deserve attention.";
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export function GrowthRadar() {
  const navigate = useNavigate();
  const [radar, setRadar] = useState<GrowthRadarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGrowthRadar()
      .then(setRadar)
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load";
        if (msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403")) {
          setError("no_workspace");
        } else {
          setError(msg);
        }
      });
  }, []);

  const handleInvestigate = (signalTitle: string, opportunity: string) => {
    const objective = `Investigate opportunity: ${opportunity}. Signal: ${signalTitle}`;
    navigate(`/agents?objective=${encodeURIComponent(objective)}`);
  };

  if (error === "no_workspace") {
    return (
      <section className="shell section" aria-labelledby="radar-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">YOUR BUSINESS · GROWTH RADAR</p>
          <h1 id="radar-heading" className="display-lg" style={{ marginTop: 10 }}>
            Growth Radar
          </h1>
        </div>
        <WindowPanel title="workspace-required.app">
          <p className="meta-label" style={{ marginBottom: 12 }}>WORKSPACE NOT CONNECTED</p>
          <p style={{ fontSize: "var(--text-body)", lineHeight: "var(--leading-body)", color: "var(--ink-soft)" }}>
            Growth Radar reads your real business data — payments, orders, and customers.
            To access it, your account needs to be connected to a merchant workspace.
          </p>
          <div style={{ marginTop: 20, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Button variant="primary" mono onClick={() => navigate("/profile")}>
              View Profile &amp; Workspace
            </Button>
          </div>
        </WindowPanel>
      </section>
    );
  }

  if (error) {
    return (
      <section className="shell section">
        <WindowPanel title="growth-radar.app">
          <p style={{ color: "var(--coral-strong)" }}>{error}</p>
        </WindowPanel>
      </section>
    );
  }

  if (!radar) {
    return (
      <section className="shell section">
        <WindowPanel title="growth-radar.app">
          <p style={{ color: "var(--ink-soft)", fontFamily: "var(--font-mono)", fontSize: "var(--text-meta)", textTransform: "uppercase", letterSpacing: "var(--tracking-meta)" }}>
            Analysing your business…
          </p>
        </WindowPanel>
      </section>
    );
  }

  const { metrics, data_sufficiency: sufficiency } = radar;

  const story = buildHealthStory(radar);
  const ranked = rankSignals(radar);
  const priority = ranked[0];
  const rest = ranked.slice(1);

  const successPayments = metrics.successful_payments;
  const failedPayments = metrics.failed_payments;
  const totalPayments = successPayments + failedPayments;
  const successPctTotal = totalPayments > 0 ? (successPayments / totalPayments) * 100 : 0;
  const failedPctTotal = totalPayments > 0 ? (failedPayments / totalPayments) * 100 : 0;
  const repeatShare =
    metrics.total_customers > 0 ? Math.round((metrics.repeat_customers / metrics.total_customers) * 100) : 0;

  const coveragePct = Math.min(
    100,
    Math.round((sufficiency.available / Math.max(1, sufficiency.minimum_required)) * 100)
  );

  return (
    <section className="shell section" aria-labelledby="radar-heading">
      {/* ── 1. Header ─────────────────────────────────────────────────── */}
      <div className="radar-header">
        <div>
          <p className="meta-label">YOUR BUSINESS · GROWTH RADAR</p>
          <h1 id="radar-heading" className="display-lg" style={{ margin: "10px 0 0" }}>
            Growth Radar
          </h1>
          <p className="radar-header__lead">
            Your business health at a glance — measured from real payments, orders, and customers.
          </p>
        </div>
        <span className="radar-live">
          <span className="radar-live__dot" aria-hidden="true" />
          Live business data
        </span>
      </div>

      {/* ── 2. Business health metrics ─────────────────────────────────── */}
      <div className="radar-section">
        <div className="radar-section__head">
          <h2 className="meta-label" style={{ margin: 0 }}>BUSINESS HEALTH</h2>
          <span className="meta-label" style={{ color: "var(--ink-faint)" }}>
            {radar.overall_health.replace(/_/g, " ").toUpperCase()}
          </span>
        </div>
        <p className="radar-section__lede">
          These figures are measured directly from your recent business activity. Together they show how much
          revenue you captured, how many purchases completed, and where money may have slipped through.
        </p>

        <div className="radar-metrics">
          <div className="radar-metric">
            <p className="meta-label" style={{ marginBottom: 0 }}>REVENUE CAPTURED</p>
            <p className="radar-metric__value">{rupees(metrics.captured_revenue, true)}</p>
            <p className="radar-metric__note">Money successfully received through transactions.</p>
          </div>
          <div className="radar-metric">
            <p className="meta-label" style={{ marginBottom: 0 }}>TRANSACTIONS</p>
            <p className="radar-metric__value">{metrics.captured_transactions}</p>
            <p className="radar-metric__note">Successful purchases completed.</p>
          </div>
          <div className="radar-metric">
            <p className="meta-label" style={{ marginBottom: 0 }}>CUSTOMERS</p>
            <p className="radar-metric__value">{metrics.total_customers}</p>
            <p className="radar-metric__note">Unique customers who have transacted.</p>
          </div>
          <div className="radar-metric">
            <p className="meta-label" style={{ marginBottom: 0 }}>ORDERS</p>
            <p className="radar-metric__value">{metrics.total_orders}</p>
            <p className="radar-metric__note">Orders created across your channels.</p>
          </div>
          <div className="radar-metric">
            <p className="meta-label" style={{ marginBottom: 0 }}>AVERAGE ORDER VALUE</p>
            <p className="radar-metric__value">{rupees(metrics.average_order_value, true)}</p>
            <p className="radar-metric__note">Average spend per purchase.</p>
          </div>
          <div className="radar-metric">
            <p className="meta-label" style={{ marginBottom: 0 }}>FAILED PAYMENTS</p>
            <p className={`radar-metric__value${failedPayments > 0 ? " radar-metric__value--warn" : ""}`}>
              {failedPayments}
            </p>
            <p className="radar-metric__note">Unsuccessful payments that may hold recoverable revenue.</p>
            {totalPayments > 0 && (
              <p className="radar-metric__sub">{failedPctTotal.toFixed(0)}% of payment attempts</p>
            )}
          </div>
        </div>
      </div>

      {/* ── 3. Business health summary ─────────────────────────────────── */}
      <div className="radar-section">
        <div className="radar-summary">
          <p className="meta-label" style={{ marginBottom: 0, color: "var(--coral-strong)" }}>
            WHAT THIS MEANS FOR YOUR BUSINESS
          </p>
          <p className="radar-summary__text">{story.headline}</p>
        </div>
      </div>

      {/* Flow separator */}
      <div className="radar-flow" aria-hidden="true">
        <span>Business health</span>
        <span className="radar-flow__rule" />
        <span>What the radar found</span>
        <span className="radar-flow__rule" />
        <span>What to do next</span>
      </div>

      {/* ── 4. Detected growth signals ─────────────────────────────────── */}
      <div className="radar-section">
        <div className="radar-section__head">
          <h2 className="meta-label" style={{ margin: 0 }}>DETECTED GROWTH SIGNALS</h2>
          <span className="meta-label" style={{ color: "var(--ink-faint)" }}>
            {ranked.length} FOUND
          </span>
        </div>
        <p className="radar-section__lede">
          The radar compares your recent business activity against the previous period to identify patterns worth
          attention. These are not just activity numbers — they highlight where your business may recover revenue,
          increase order value, or win back customers.
        </p>

        {ranked.length === 0 ? (
          <WindowPanel title="no-signals.app">
            <p style={{ color: "var(--ink-soft)", lineHeight: "var(--leading-body)" }}>
              No growth signals detected yet. This usually means your account is still building transaction
              history. Add more real orders and payments to unlock AI growth analysis.
            </p>
            {sufficiency.available < sufficiency.minimum_required && (
              <p style={{
                marginTop: 12,
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                textTransform: "uppercase",
                letterSpacing: "var(--tracking-meta)",
                color: "var(--ink-faint)",
              }}>
                {sufficiency.minimum_required - sufficiency.available} more transactions needed to unlock AI analysis.
              </p>
            )}
          </WindowPanel>
        ) : (
          <div className="radar-signals">
            {ranked.map((signal, i) => (
              <article className="radar-signal" key={`${signal.signal}-${i}`}>
                <div className="radar-signal__bar">
                  <span>DETECTED SIGNAL · {String(i + 1).padStart(2, "0")}</span>
                  <span>{pct(signal.confidence)}% CONFIDENCE</span>
                </div>
                <div className="radar-signal__body">
                  <h3 className="radar-signal__title">{signal.title}</h3>
                  <p className="radar-signal__observed">{signalEvidence(signal)}</p>

                  <div className="radar-signal__grid">
                    <div className="radar-signal__cell">
                      <p className="radar-cell-label">WHY THIS MATTERS</p>
                      <p style={{ fontSize: "var(--text-small)", lineHeight: 1.5, color: "var(--ink-soft)" }}>
                        {opportunityWhy(signal.signal)}
                      </p>
                    </div>
                    <div className="radar-signal__cell">
                      <p className="radar-cell-label">OPPORTUNITY</p>
                      <p style={{ fontSize: "var(--text-small)", lineHeight: 1.5, color: "var(--ink)" }}>
                        {signal.opportunity}
                      </p>
                    </div>
                    <div className="radar-signal__cell radar-signal__cell--action">
                      <p className="radar-cell-label" style={{ color: "var(--coral-strong)" }}>SUGGESTED ACTION</p>
                      <p style={{ fontSize: "var(--text-small)", lineHeight: 1.5, color: "var(--ink)" }}>
                        {signal.recommended_action}
                      </p>
                    </div>
                  </div>

                  <div className="radar-signal__footer">
                    <p className="radar-signal__action">
                      Confidence reflects how much recent business activity backs this signal — higher means more
                      supporting evidence.
                    </p>
                    <Button
                      variant="primary"
                      mono
                      onClick={() => handleInvestigate(signal.title, signal.opportunity)}
                    >
                      Investigate with AI Team →
                    </Button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* ── 6. Business performance visualization ──────────────────────── */}
      {totalPayments > 0 && (
        <div className="radar-section">
          <div className="radar-section__head">
            <h2 className="meta-label" style={{ margin: 0 }}>PAYMENT PERFORMANCE</h2>
          </div>
          <p className="radar-section__lede">
            Every payment attempt your customers made, split by outcome. A tall successful bar is good news; any
            failed-payment bar represents customers who tried to buy but could not.
          </p>
          <div className="radar-chart">
            <p className="radar-chart__note">
              {failedPayments > 0
                ? `${count(successPayments, "payment")} went through and ${count(failedPayments, "payment")} did not — ${failedPctTotal.toFixed(0)}% of all attempts.`
                : `All ${count(successPayments, "payment")} attempt${successPayments === 1 ? "" : "s"} went through successfully.`}
            </p>
            <div className="radar-chart__rows">
              <div className="radar-chart__row">
                <span className="radar-chart__label">Successful</span>
                <div className="radar-chart__track">
                  <div
                    className="radar-chart__fill"
                    style={{ width: `${totalPayments > 0 ? (successPayments / totalPayments) * 100 : 0}%` }}
                  />
                </div>
                <span className="radar-chart__value">{successPayments}</span>
              </div>
              <div className="radar-chart__row">
                <span className="radar-chart__label">Unsuccessful</span>
                <div className="radar-chart__track">
                  <div
                    className="radar-chart__fill radar-chart__fill--warn"
                    style={{ width: `${failedPctTotal}%` }}
                  />
                </div>
                <span className="radar-chart__value">{failedPayments}</span>
              </div>
            </div>
            <div className="radar-chart__scale">
              <span>Scale: each bar = share of {totalPayments} total payment attempts</span>
              <span>
                {successPctTotal.toFixed(0)}% SUCCESS · {failedPctTotal.toFixed(0)}% FAILED
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Customer activity strip — only when real customer data exists */}
      {metrics.total_customers > 0 && (
        <div className="radar-section">
          <div className="radar-chart">
            <p className="meta-label" style={{ marginBottom: 0 }}>CUSTOMER ACTIVITY</p>
            <p className="radar-chart__note">
              {metrics.total_customers} unique customers have purchased from you.
              {metrics.repeat_customers > 0
                ? ` ${metrics.repeat_customers} of them have returned to buy again — a ${repeatShare}% repeat rate. Returning customers are typically cheaper to serve than new ones.`
                : " None have returned for a second purchase yet — a first repeat customer is often the earliest sign of a durable business."}
            </p>
            <div className="radar-chart__rows">
              <div className="radar-chart__row">
                <span className="radar-chart__label">All customers</span>
                <div className="radar-chart__track">
                  <div className="radar-chart__fill" style={{ width: "100%" }} />
                </div>
                <span className="radar-chart__value">{metrics.total_customers}</span>
              </div>
              <div className="radar-chart__row">
                <span className="radar-chart__label">Repeat customers</span>
                <div className="radar-chart__track">
                  <div className="radar-chart__fill" style={{ width: `${repeatShare}%` }} />
                </div>
                <span className="radar-chart__value">{metrics.repeat_customers}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── 7 + 9. Priority opportunity & other opportunities ───────────── */}
      {ranked.length > 0 && (
        <div className="radar-section">
          <div className="radar-section__head">
            <h2 className="meta-label" style={{ margin: 0 }}>GROWTH OPPORTUNITIES</h2>
            <span className="meta-label" style={{ color: "var(--ink-faint)" }}>
              RANKED BY STRENGTH OF EVIDENCE
            </span>
          </div>
          <p className="radar-section__lede">
            Each opportunity below comes from a signal the radar detected in your real business data — with the
            evidence behind it, what it could be worth, and the next practical step. Start with the priority; it
            has the strongest support.
          </p>

          {/* Priority opportunity — strongest signal */}
          {priority && (
            <div className="radar-priority">
              <div className="radar-priority__bar">
                <span>PRIORITY OPPORTUNITY · STRONGEST EVIDENCE</span>
                <span>{pct(priority.confidence)}% CONFIDENCE</span>
              </div>
              <div className="radar-priority__body">
                <h3 className="radar-priority__title">{priority.opportunity}</h3>
                {potentialImpact(priority) !== null && (
                  <p className="radar-priority__impact">
                    Potential impact · {rupees(potentialImpact(priority) as number, true)}
                  </p>
                )}
                <div className="radar-priority__grid">
                  <div className="radar-priority__cell">
                    <p className="radar-priority__cell-label">WHY IT MATTERS</p>
                    <p className="radar-priority__cell-text">{opportunityWhy(priority.signal)}</p>
                  </div>
                  <div className="radar-priority__cell">
                    <p className="radar-priority__cell-label">EVIDENCE</p>
                    <p className="radar-priority__cell-text">
                      {signalEvidence(priority)}
                      {" "}
                      Detected signal: “{priority.title}”.
                    </p>
                  </div>
                  <div className="radar-priority__cell">
                    <p className="radar-priority__cell-label">RECOMMENDED ACTION</p>
                    <p className="radar-priority__cell-text">{priority.recommended_action}</p>
                  </div>
                </div>
                <div className="radar-priority__cta">
                  <p className="radar-priority__cta-note">
                    This is the opportunity your AI Growth Team should look at first — it is ranked by how much
                    real evidence supports it.
                  </p>
                  <Button
                    variant="primary"
                    mono
                    onClick={() => handleInvestigate(priority.title, priority.opportunity)}
                  >
                    Investigate with AI Team →
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Remaining opportunities */}
          {rest.length > 0 && (
            <div className="radar-opps" style={{ marginTop: 18 }}>
              {rest.map((signal, i) => (
                <article className="radar-opp" key={`${signal.signal}-${i}`}>
                  <p className="radar-opp__rank">OPPORTUNITY {String(i + 2).padStart(2, "0")}</p>
                  <h3 className="radar-opp__title">{signal.opportunity}</h3>
                  {potentialImpact(signal) !== null && (
                    <p className="radar-opp__impact">Potential impact · {rupees(potentialImpact(signal) as number, true)}</p>
                  )}
                  <div className="radar-opp__row">
                    <p className="radar-cell-label" style={{ marginBottom: 4 }}>WHY IT MATTERS</p>
                    <p>{opportunityWhy(signal.signal)}</p>
                  </div>
                  <div className="radar-opp__row">
                    <p className="radar-cell-label" style={{ marginBottom: 4 }}>EVIDENCE</p>
                    <p>{signalEvidence(signal)}</p>
                  </div>
                  <div className="radar-opp__row">
                    <p className="radar-cell-label" style={{ marginBottom: 4 }}>RECOMMENDED ACTION</p>
                    <p>{signal.recommended_action}</p>
                  </div>
                  <div className="radar-opp__action">
                    <span className="meta-label" style={{ color: "var(--green-deep)" }}>
                      {pct(signal.confidence)}% CONFIDENCE
                    </span>
                    <Button
                      variant="secondary"
                      mono
                      onClick={() => handleInvestigate(signal.title, signal.opportunity)}
                    >
                      Investigate →
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── 10. Data coverage ───────────────────────────────────────────── */}
      <div className="radar-section">
        <div className="radar-coverage">
          <div>
            <p className="meta-label" style={{ marginBottom: 0 }}>
              DATA COVERAGE ·{" "}
              {sufficiency.status === "sufficient"
                ? "SUFFICIENT BUSINESS DATA AVAILABLE"
                : "BUILDING TRANSACTION HISTORY"}
            </p>
            <p className="radar-coverage__note">{sufficiency.message}</p>
          </div>
          <div className="radar-coverage__meter">
            <p className="meta-label" style={{ marginBottom: 0 }}>
              {sufficiency.available} / {sufficiency.minimum_required} TRANSACTIONS RECORDED
            </p>
            <div className="radar-coverage__track" role="progressbar"
              aria-valuenow={coveragePct} aria-valuemin={0} aria-valuemax={100}
              aria-label="Transaction history coverage"
            >
              <div
                className={`radar-coverage__fill${coveragePct < 100 ? " radar-coverage__fill--low" : ""}`}
                style={{ width: `${coveragePct}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <div className="radar-footer">
        <p>
          {ranked.length > 0
            ? "Investigate any opportunity above to have your AI Growth Team analyse it in depth."
            : "Your AI Growth Team is ready when you have sufficient data."}
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {ranked.length > 0 && (
            <Button variant="secondary" mono onClick={() => navigate("/agents")}>
              Meet the AI Growth Team →
            </Button>
          )}
          <Button variant="primary" mono onClick={() => navigate("/actions")}>
            Review Growth Actions →
          </Button>
        </div>
      </div>
    </section>
  );
}
