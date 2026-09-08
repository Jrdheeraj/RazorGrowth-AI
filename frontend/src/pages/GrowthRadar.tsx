/**
 * /growth-radar — RazorGrowth premium SaaS dashboard
 * Neo-brutalist editorial: warm cream, dark brown ink, terracotta, thin borders, hard shadows.
 * Every value is real merchant data from GrowthRadar + Analytics APIs — never hard-coded.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchAnalyticsOverview,
  fetchCustomersTrend,
  fetchGrowthRadar,
  fetchOrdersTrend,
  fetchRevenueSeries,
} from "../lib/api";
import type {
  AnalyticsOverviewResponse,
  GrowthRadarResponse,
} from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import "./GrowthRadar.css";

/* ── Formatting ───────────────────────────────────────────────────────── */

function toNum(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function rupees(v: number | string, decimals = false): string {
  const num = toNum(v, 0);
  const n = decimals ? num.toFixed(2) : Math.round(num).toLocaleString("en-IN");
  return `₹${n}`;
}
function pct(v: number): number {
  return Math.round(v * 100);
}
function count(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}
function fmtDateShort(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
  } catch {
    return iso.slice(0, 10);
  }
}

/* ── Signal helpers ───────────────────────────────────────────────────── */

const METRIC_LABELS: Record<string, string> = {
  captured_revenue_inr: "revenue received",
  repeat_customer_orders: "repeat purchases",
  order_count: "orders placed",
  failed_payment_value_inr: "unsuccessful payment value",
  recoverable_revenue_inr: "potentially recoverable revenue",
  dormant_customer_count: "quiet returning customers",
};
function metricLabel(k: string): string {
  return METRIC_LABELS[k] ?? "business activity";
}
function opportunityWhy(key: string): string {
  const m: Record<string, string> = {
    payment_failures:
      "Failed payments represent customers who attempted to complete a purchase but were unsuccessful — real buying intent that did not convert.",
    payment_recovery_opportunity:
      "Recent payment activity shows attempted purchases that did not complete successfully. That value may represent revenue worth recovering.",
    revenue_drop:
      "Revenue softened compared with the previous period. Understanding why is the first step to reversing it.",
    emerging_growth: "Revenue is accelerating. Doubling down on what is working can compound the gains.",
    declining_repeat_purchases: "Returning customers are buying less. Retention is usually cheaper than acquisition.",
    unusual_order_behavior: "Order volume shifted noticeably. Confirming whether this is growth or friction protects future revenue.",
    abandoned_customers:
      "Customers with purchase history have gone quiet. They already trust your business — winning them back is often highest-leverage.",
  };
  return m[key] ?? "The radar detected a pattern in your business activity that may deserve attention.";
}
function numberField(od: Record<string, unknown>, path: string): number | null {
  const [head, tail] = path.split(".");
  const top = od[head];
  if (tail === undefined) return typeof top === "number" ? top : null;
  if (top && typeof top === "object") {
    const v = (top as Record<string, unknown>)[tail];
    return typeof v === "number" ? v : null;
  }
  return null;
}
function signalValue(s: GrowthRadarResponse["signals"][number]): number {
  const od = (s.observed_data ?? {}) as Record<string, unknown>;
  for (const k of ["failed_payment_value_inr", "recoverable_revenue_inr", "value"]) {
    const v = od[k];
    if (typeof v === "number") return v;
  }
  return 0;
}
function potentialImpact(s: GrowthRadarResponse["signals"][number]): number | null {
  if (s.calculated_metric.includes("revenue") || s.calculated_metric.includes("value")) {
    const v = signalValue(s);
    return v > 0 ? v : null;
  }
  return null;
}
function signalEvidence(s: GrowthRadarResponse["signals"][number]): string {
  const od = (s.observed_data ?? {}) as Record<string, unknown>;
  const failedCount = typeof od.failed_count === "number" ? od.failed_count : null;
  if (failedCount !== null) {
    const valueText = s.calculated_metric.includes("recoverable") ? ` worth ${rupees(signalValue(s), true)}` : "";
    return `Observed from recent payment activity — ${count(failedCount, "unsuccessful attempt")}${valueText}.`;
  }
  const cur = numberField(od, "current_window.captured_payments");
  const cmp = numberField(od, "previous_window.captured_payments");
  if (cur !== null && cmp !== null) {
    const diff = cmp > 0 ? ((cur - cmp) / cmp) * 100 : null;
    const dir = diff === null ? "" : diff >= 0 ? "up" : "down";
    return diff === null
      ? `Measured from your recent ${metricLabel(s.calculated_metric)} — ${cur} recent versus ${cmp} in the previous period.`
      : `Recent ${metricLabel(s.calculated_metric)} moved ${dir} ${Math.abs(diff).toFixed(1)}% versus the previous period (${cmp} → ${cur}).`;
  }
  const dormant = numberField(od, "recency_cutoff_days");
  if (dormant !== null) return `Measured from your customer order history — customers who had bought before but not in the last ${dormant} days.`;
  return `Measured from your recent ${metricLabel(s.calculated_metric)} activity compared with the previous period.`;
}
function rankSignals(radar: GrowthRadarResponse) {
  return [...radar.signals].sort((a, b) => b.confidence - a.confidence || a.signal.localeCompare(b.signal));
}
function buildHealthStory(radar: GrowthRadarResponse): string {
  const m = radar.metrics;
  const parts: string[] = [];
  parts.push(
    `Your business completed ${count(m.captured_transactions, "successful transaction")}s and captured ${rupees(m.captured_revenue, true)} in revenue, at an average of ${rupees(m.average_order_value, true)} per purchase. ${count(m.total_customers, "customer")}s have ordered, across ${count(m.total_orders, "order")} in total.`,
  );
  const failureSignal = radar.signals.find((s) => s.signal === "payment_recovery_opportunity" || s.signal === "payment_failures") ?? null;
  const failedCount = m.failed_payments;
  const failedSignalCount =
    failureSignal && typeof (failureSignal.observed_data as Record<string, unknown>).failed_count === "number"
      ? ((failureSignal.observed_data as Record<string, unknown>).failed_count as number)
      : failedCount;
  const failedValue = failureSignal ? signalValue(failureSignal) : null;
  if (failedCount > 0) {
    const vt = failedValue !== null && failedValue > 0 ? ` totalling ${rupees(failedValue, true)}` : "";
    parts.push(` The main attention area is unsuccessful payments — ${count(failedSignalCount, "payment attempt")}${vt} that did not complete.`);
  }
  if (m.failed_payments === 0 && radar.signals.length === 0) parts.push(" No problem areas were flagged by the radar in this period.");
  return parts.join("");
}
function deriveHealth(radar: GrowthRadarResponse): { label: string; tone: string; desc: string } {
  const m = radar.metrics;
  const suff = radar.data_sufficiency;
  const hasFailure = m.failed_payments > 0;
  const hasRiskSignals = radar.signals.some((s) => ["revenue_drop", "declining_repeat_purchases", "payment_failures", "payment_recovery_opportunity", "abandoned_customers"].includes(s.signal));
  if (suff.status === "insufficient_data" && m.captured_transactions === 0 && m.total_customers === 0) {
    return { label: "WATCH", tone: "watch", desc: "Your workspace is still building transaction history. The radar will unlock stronger signals as data grows." };
  }
  if (hasFailure || hasRiskSignals) {
    if (hasFailure && m.failed_payments >= 3) return { label: "ATTENTION", tone: "attention", desc: "Payment failures and flagged signals require review — recovery and retention merit immediate attention." };
    return { label: "ATTENTION", tone: "attention", desc: "One or more signals point to recoverable revenue or softening repeat behavior. Worth investigating this period." };
  }
  if (suff.status === "insufficient_data") return { label: "WATCH", tone: "watch", desc: "Limited history — early signals are emerging but need more transactions for high confidence." };
  return { label: "HEALTHY", tone: "healthy", desc: "Revenue captured, orders flowing, and no high-risk signals flagged this period." };
}
function priorityBadge(conf: number): { text: string; cls: string } {
  if (conf >= 0.6) return { text: "HIGH PRIORITY", cls: "rg-prio--high" };
  if (conf >= 0.38) return { text: "MEDIUM PRIORITY", cls: "rg-prio--med" };
  return { text: "LOW PRIORITY", cls: "rg-prio--low" };
}

/* ── SVG Charts — neo-brutalist palette ───────────────────────────────── */

function RevenueTrendChart({ data, loading }: { data: Array<{ date: string; value: number }>; loading?: boolean }) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  if (loading) return <div className="rg-skeleton rg-skeleton--chart" />;
  if (!data.length) {
    return (
      <div className="rg-emptyChart">
        <p className="meta-label" style={{ color: "var(--ink-faint)" }}>REVENUE TREND</p>
        <p className="rg-emptyChart__msg">No transaction history yet.</p>
        <p className="rg-emptyChart__hint">Create orders via Checkout to see revenue over time.</p>
      </div>
    );
  }
  const W = 640, H = 220, PAD_L = 52, PAD_R = 18, PAD_T = 16, PAD_B = 34;
  const vals = data.map((d) => d.value);
  const maxV = Math.max(...vals, 1);
  const minV = Math.min(...vals, 0);
  const range = maxV - minV || 1;
  // Expand slightly for visual breathing room
  const yMax = maxV * 1.18;
  const points = data.map((d, i) => {
    const x = PAD_L + (i / Math.max(1, data.length - 1)) * (W - PAD_L - PAD_R);
    const y = PAD_T + (1 - (d.value - 0) / (yMax - 0 || 1)) * (H - PAD_T - PAD_B);
    return { x, y, d };
  });
  const lineD = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const areaD = `${lineD} L ${points[points.length - 1].x.toFixed(1)} ${(H - PAD_B).toFixed(1)} L ${points[0].x.toFixed(1)} ${(H - PAD_B).toFixed(1)} Z`;
  const gridYs = [0.25, 0.5, 0.75].map((t) => PAD_T + t * (H - PAD_T - PAD_B));
  const hover = hoverIdx !== null ? points[hoverIdx] : null;
  return (
    <div className="rg-revenueWrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Revenue over time" className="rg-svgChart" preserveAspectRatio="xMidYMid meet">
        {/* grid */}
        {gridYs.map((gy, i) => (
          <line key={i} x1={PAD_L} x2={W - PAD_R} y1={gy} y2={gy} stroke="rgba(42,24,16,0.09)" strokeWidth={1} />
        ))}
        {/* y labels */}
        {[yMax, yMax / 2, 0].map((v, i) => {
          const y = PAD_T + (1 - v / yMax) * (H - PAD_T - PAD_B);
          return (
            <text key={i} x={PAD_L - 8} y={y + 4} textAnchor="end" fontFamily="IBM Plex Mono, monospace" fontSize={9} letterSpacing="0.04em" fill="#8a6f5c">
              {v >= 1000 ? `₹${Math.round(v / 1000)}k` : `₹${Math.round(v)}`}
            </text>
          );
        })}
        {/* area */}
        <path d={areaD} fill="rgba(217,119,87,0.13)" stroke="none" />
        {/* line */}
        <path d={lineD} fill="none" stroke="#c85f43" strokeWidth={2.4} strokeLinejoin="round" strokeLinecap="round" />
        {/* points */}
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={hoverIdx === i ? 5 : 3.2} fill="#c85f43" stroke="#fff3df" strokeWidth={1.2} style={{ transition: "r 120ms" }} />
            <rect
              x={p.x - (W / data.length) / 2}
              y={PAD_T}
              width={W / data.length}
              height={H - PAD_T - PAD_B}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx(null)}
            />
          </g>
        ))}
        {/* hover guide */}
        {hover && <line x1={hover.x} x2={hover.x} y1={PAD_T} y2={H - PAD_B} stroke="rgba(42,24,16,0.18)" strokeWidth={1} strokeDasharray="4 4" />}
        {/* x labels — show ~5 evenly */}
        {data.map((d, i) => {
          const step = Math.max(1, Math.ceil(data.length / 5));
          if (i % step !== 0 && i !== data.length - 1) return null;
          const x = points[i].x;
          return (
            <text key={i} x={x} y={H - 10} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={9} letterSpacing="0.06em" fill="#8a6f5c">
              {fmtDateShort(d.date)}
            </text>
          );
        })}
        {/* axis baseline */}
        <line x1={PAD_L} x2={W - PAD_R} y1={H - PAD_B} y2={H - PAD_B} stroke="#2a1810" strokeWidth={1} opacity={0.28} />
      </svg>
      {hover && (
        <div className="rg-tooltip" style={{ left: `${Math.min(94, Math.max(6, (hover.x / W) * 100))}%` }}>
          <span className="rg-tooltip__label">{fmtDateShort(hover.d.date)}</span>
          <span className="rg-tooltip__value">{rupees(hover.d.value, true)}</span>
        </div>
      )}
    </div>
  );
}

function DonutChart({
  successful,
  failed,
  size = 148,
}: {
  successful: number;
  failed: number;
  size?: number;
}) {
  const total = successful + failed;
  const successPct = total > 0 ? Math.round((successful / total) * 100) : 0;
  const failedPct = 100 - successPct;
  const r = 58, stroke = 16, C = 2 * Math.PI * r;
  const successLen = total > 0 ? (successful / total) * C : 0;
  // SVG trick: two arcs using stroke-dasharray
  if (total === 0) {
    return (
      <div className="rg-donutWrap" style={{ width: size, height: size }}>
        <svg viewBox="0 0 140 140" width={size} height={size} className="rg-donut">
          <circle cx={70} cy={70} r={r} fill="none" stroke="rgba(42,24,16,0.09)" strokeWidth={stroke} />
          <text x={70} y={70} textAnchor="middle" dominantBaseline="central" fontFamily="IBM Plex Mono, monospace" fontSize={10} fill="#8a6f5c">NO DATA</text>
        </svg>
      </div>
    );
  }
  return (
    <div className="rg-donutWrap" style={{ width: size, height: size }}>
      <svg viewBox="0 0 140 140" width={size} height={size} className="rg-donut" role="img" aria-label={`Payment success ${successPct}%`}>
        <circle cx={70} cy={70} r={r} fill="none" stroke="#f5e6cf" strokeWidth={stroke} />
        {/* failed arc background then success on top — ensures visible */}
        <circle
          cx={70}
          cy={70}
          r={r}
          fill="none"
          stroke="#d97757"
          strokeWidth={stroke}
          strokeDasharray={`${C} ${C}`}
          strokeDashoffset={0}
          transform="rotate(-90 70 70)"
          opacity={0.95}
        />
        <circle
          cx={70}
          cy={70}
          r={r}
          fill="none"
          stroke="#70b88a"
          strokeWidth={stroke}
          strokeDasharray={`${successLen} ${C}`}
          strokeDashoffset={0}
          transform="rotate(-90 70 70)"
          strokeLinecap="round"
        />
        {/* center */}
        <text x={70} y={62} textAnchor="middle" fontFamily="Archivo Variable, sans-serif" fontWeight={800} fontSize={22} fill="#2a1810" letterSpacing="-0.02em">
          {successPct}%
        </text>
        <text x={70} y={78} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={8} letterSpacing="0.14em" fill="#8a6f5c">
          SUCCESS RATE
        </text>
      </svg>
      <div className="rg-donutLegend" aria-hidden="true">
        <span className="rg-donutLegend__item">
          <i className="rg-dot rg-dot--green" /> {successful} successful
        </span>
        <span className="rg-donutLegend__item">
          <i className="rg-dot rg-dot--coral" /> {failed} failed
        </span>
      </div>
      <div className="rg-donutCaption" style={{ display: "none" }}>{failedPct}% failed</div>
    </div>
  );
}

function CustomersDonut({ total, repeat }: { total: number; repeat: number }) {
  const first = Math.max(0, total - repeat);
  const pctRepeat = total > 0 ? Math.round((repeat / total) * 100) : 0;
  const r = 54, stroke = 14, C = 2 * Math.PI * r;
  const repeatLen = total > 0 ? (repeat / total) * C : 0;
  if (total === 0) {
    return (
      <div className="rg-donutWrap" style={{ width: 138, height: 138 }}>
        <svg viewBox="0 0 130 130" width={138} height={138}>
          <circle cx={65} cy={65} r={r} fill="none" stroke="rgba(42,24,16,0.09)" strokeWidth={stroke} />
          <text x={65} y={65} textAnchor="middle" dominantBaseline="central" fontFamily="IBM Plex Mono, monospace" fontSize={9} fill="#8a6f5c">NO DATA</text>
        </svg>
      </div>
    );
  }
  return (
    <div className="rg-donutWrap" style={{ width: 138, height: 138 }}>
      <svg viewBox="0 0 130 130" width={138} height={138} role="img" aria-label={`${pctRepeat}% repeat customers`}>
        <circle cx={65} cy={65} r={r} fill="none" stroke="#f5e6cf" strokeWidth={stroke} />
        <circle cx={65} cy={65} r={r} fill="none" stroke="#d97757" strokeWidth={stroke} strokeDasharray={`${C} ${C}`} transform="rotate(-90 65 65)" />
        <circle cx={65} cy={65} r={r} fill="none" stroke="#2a1810" strokeWidth={stroke} strokeDasharray={`${repeatLen} ${C}`} transform="rotate(-90 65 65)" strokeLinecap="round" />
        <text x={65} y={58} textAnchor="middle" fontFamily="Archivo Variable, sans-serif" fontWeight={800} fontSize={18} fill="#2a1810">{pctRepeat}%</text>
        <text x={65} y={72} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={7.5} letterSpacing="0.13em" fill="#8a6f5c">REPEAT</text>
      </svg>
      <div className="rg-donutLegend">
        <span className="rg-donutLegend__item"><i className="rg-dot rg-dot--ink" /> {repeat} repeat</span>
        <span className="rg-donutLegend__item"><i className="rg-dot rg-dot--coral" /> {first} first-time</span>
      </div>
    </div>
  );
}

function OrdersBarChart({ data, loading }: { data: Array<{ date: string; value: number }>; loading?: boolean }) {
  if (loading) return <div className="rg-skeleton rg-skeleton--chartSm" />;
  if (!data.length) {
    return (
      <div className="rg-emptyChart rg-emptyChart--sm">
        <p className="rg-emptyChart__msg">No order activity recorded.</p>
        <p className="rg-emptyChart__hint">Orders created in the selected window will appear here.</p>
      </div>
    );
  }
  const W = 520, H = 180, PL = 38, PR = 12, PT = 14, PB = 32;
  const maxV = Math.max(...data.map((d) => d.value), 1);
  const yMax = maxV * 1.25 || 1;
  const barW = (W - PL - PR) / data.length * 0.62;
  const gap = (W - PL - PR) / data.length;
  return (
    <div className="rg-barWrap">
      <svg viewBox={`0 0 ${W} ${H}`} className="rg-svgChart" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Orders over time">
        {[0.5, 1].map((t, i) => {
          const y = PT + (1 - t * 0.9) * (H - PT - PB);
          return <line key={i} x1={PL} x2={W - PR} y1={y} y2={y} stroke="rgba(42,24,16,0.08)" strokeWidth={1} />;
        })}
        {[yMax, 0].map((v, i) => {
          const y = PT + (1 - v / yMax) * (H - PT - PB);
          return <text key={i} x={PL - 8} y={y + 3} textAnchor="end" fontFamily="IBM Plex Mono, monospace" fontSize={8.5} fill="#8a6f5c">{Math.round(v)}</text>;
        })}
        {data.map((d, i) => {
          const x = PL + i * gap + (gap - barW) / 2;
          const h = (d.value / yMax) * (H - PT - PB);
          const y = H - PB - h;
          return (
            <g key={i}>
              <rect x={x} y={y} width={barW} height={h} rx={1.5} fill={i === data.length - 1 ? "#c85f43" : "#2a1810"} opacity={i === data.length - 1 ? 1 : 0.88} />
              <text x={x + barW / 2} y={y - 6} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={8} fill="#2a1810" fontWeight={700}>{d.value}</text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const step = Math.max(1, Math.ceil(data.length / 5));
          if (i % step !== 0 && i !== data.length - 1) return null;
          const x = PL + i * gap + gap / 2;
          return <text key={i} x={x} y={H - 10} textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize={8} letterSpacing="0.06em" fill="#8a6f5c">{fmtDateShort(d.date)}</text>;
        })}
        <line x1={PL} x2={W - PR} y1={H - PB} y2={H - PB} stroke="#2a1810" opacity={0.22} strokeWidth={1} />
      </svg>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */

export function GrowthRadar() {
  const navigate = useNavigate();
  const [windowDays, setWindowDays] = useState(30);
  const [compare, setCompare] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const [radar, setRadar] = useState<GrowthRadarResponse | null>(null);
  const [overview, setOverview] = useState<AnalyticsOverviewResponse | null>(null);
  const [revSeries, setRevSeries] = useState<Array<{ date: string; value: number }> | null>(null);
  const [orderSeries, setOrderSeries] = useState<Array<{ date: string; value: number }> | null>(null);
  const [custSeries, setCustSeries] = useState<Array<{ date: string; value: number }> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchGrowthRadar(windowDays)
      .then((r) => {
        if (!cancelled) setRadar(r);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Failed to load";
        if (msg.includes("NOT_AUTHENTICATED") || msg.includes("TOKEN_EXPIRED") || msg.includes("401")) setError("login_required");
        else if (msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403")) setError("no_workspace");
        else setError(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [windowDays, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    // Independent fetches — each chart resolves on its own so one hanging/failed request never blocks the others.
    // Reset to loading (null) on window change, then each fetch sets its own data or empty on failure.
    setOverview(null);
    setRevSeries(null);
    setOrderSeries(null);
    setCustSeries(null);

    const toSeries = (raw: Array<{ date: string; value: number | string }>) =>
      raw.map((d) => ({ date: String(d.date), value: toNum(d.value, 0) }));

    // Overview
    fetchAnalyticsOverview(windowDays)
      .then((v) => { if (!cancelled) setOverview(v); })
      .catch(() => { if (!cancelled) setOverview(null); });

    // Revenue series — use timeout so a hanging backend does not keep chart in skeleton forever
    const revPromise = fetchRevenueSeries(windowDays, windowDays <= 14 ? "day" : windowDays <= 31 ? "day" : "week");
    const revTimeout = new Promise<never>((_, rej) => setTimeout(() => rej(new Error("timeout")), 12000));
    Promise.race([revPromise, revTimeout])
      .then((r) => {
        if (cancelled) return;
        const raw = (r.data ?? []) as Array<{ date: string; value: number | string }>;
        setRevSeries(toSeries(raw));
      })
      .catch(() => { if (!cancelled) setRevSeries([]); });

    const ordPromise = fetchOrdersTrend(windowDays, windowDays <= 14 ? "day" : windowDays <= 31 ? "day" : "week");
    const ordTimeout = new Promise<never>((_, rej) => setTimeout(() => rej(new Error("timeout")), 12000));
    Promise.race([ordPromise, ordTimeout])
      .then((r) => {
        if (cancelled) return;
        const raw = (r.data ?? []) as Array<{ date: string; value: number | string }>;
        setOrderSeries(toSeries(raw));
      })
      .catch(() => { if (!cancelled) setOrderSeries([]); });

    const custPromise = fetchCustomersTrend(windowDays, windowDays <= 14 ? "day" : windowDays <= 31 ? "day" : "week");
    const custTimeout = new Promise<never>((_, rej) => setTimeout(() => rej(new Error("timeout")), 12000));
    Promise.race([custPromise, custTimeout])
      .then((r) => {
        if (cancelled) return;
        const raw = (r.data ?? []) as Array<{ date: string; value: number | string }>;
        setCustSeries(toSeries(raw));
      })
      .catch(() => { if (!cancelled) setCustSeries([]); });

    // Overview also needs timeout fallback to empty (null means loading, so set to empty object fallback? Keep null for revenue fallback to metrics)
    // If overview hangs, we still want dashboard to show without it — after timeout set to null (will fallback to metrics) but not keep loading.
    // So schedule a fallback to ensure overview pending does not block derived values indefinitely (it already falls back to metrics).

    return () => {
      cancelled = true;
    };
  }, [windowDays, refreshKey]);

  const handleInvestigate = (title: string, opp: string) => {
    const objective = `Investigate opportunity: ${opp}. Signal: ${title}`;
    navigate(`/agents?objective=${encodeURIComponent(objective)}`);
  };

  /* ——— derived ——— */
  const metrics = radar?.metrics ?? null;
  const sufficiency = radar?.data_sufficiency ?? null;
  const ranked = useMemo(() => (radar ? rankSignals(radar) : []), [radar]);
  const priority = ranked[0] ?? null;
  const rest = ranked.slice(1);
  const successPayments = metrics?.successful_payments ?? 0;
  const failedPayments = metrics?.failed_payments ?? 0;
  const totalPayments = successPayments + failedPayments;
  const successPct = totalPayments > 0 ? (successPayments / totalPayments) * 100 : 0;
  const failedPct = totalPayments > 0 ? (failedPayments / totalPayments) * 100 : 0;
  const repeatShare = metrics && metrics.total_customers > 0 ? Math.round((metrics.repeat_customers / metrics.total_customers) * 100) : 0;
  const coveragePct = sufficiency ? Math.min(100, Math.round((sufficiency.available / Math.max(1, sufficiency.minimum_required)) * 100)) : 0;
  const health = radar ? deriveHealth(radar) : { label: "—", tone: "watch", desc: "" };
  const story = radar ? buildHealthStory(radar) : "";
  const revenueCurrent = overview ? toNum((overview.revenue as unknown as Record<string, unknown>).current_period, toNum(metrics?.captured_revenue, 0)) : toNum(metrics?.captured_revenue, 0);
  const revenuePrev = overview ? toNum((overview.revenue as unknown as Record<string, unknown>).previous_period, 0) : null;
  const revenueChange = overview?.revenue.change_percentage ?? null;
  const isEmptyBusiness = metrics ? metrics.captured_transactions === 0 && metrics.total_customers === 0 && metrics.total_orders === 0 : false;

  /* ——— early returns ——— */
  if (error === "login_required") {
    return (
      <section className="shell rg-page" aria-labelledby="radar-heading">
        <div className="rg-topHead">
          <p className="meta-label">YOUR BUSINESS · GROWTH RADAR</p>
          <h1 id="radar-heading" className="display-lg">Growth Radar</h1>
        </div>
        <WindowPanel title="login-required.app">
          <p className="meta-label" style={{ marginBottom: 10 }}>SIGN IN REQUIRED</p>
          <p style={{ color: "var(--ink-soft)", lineHeight: "var(--leading-body)" }}>Growth Radar shows your live business data — payments, orders, and customers. Sign in to view your Razorpay TEST intelligence.</p>
          <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
            <Button variant="primary" mono onClick={() => navigate("/login")}>Sign in</Button>
          </div>
        </WindowPanel>
      </section>
    );
  }
  if (error === "no_workspace") {
    return (
      <section className="shell rg-page" aria-labelledby="radar-heading">
        <div className="rg-topHead">
          <p className="meta-label">YOUR BUSINESS · GROWTH RADAR</p>
          <h1 id="radar-heading" className="display-lg">Growth Radar</h1>
        </div>
        <WindowPanel title="workspace-required.app">
          <p className="meta-label" style={{ marginBottom: 10 }}>WORKSPACE NOT CONNECTED</p>
          <p style={{ color: "var(--ink-soft)", lineHeight: "var(--leading-body)" }}>Your account needs a merchant workspace to access Growth Radar.</p>
          <div style={{ marginTop: 18 }}><Button variant="primary" mono onClick={() => navigate("/profile")}>View Profile & Workspace</Button></div>
        </WindowPanel>
      </section>
    );
  }
  if (error) {
    return (
      <section className="shell rg-page">
        <WindowPanel title="growth-radar.app">
          <p className="meta-label" style={{ color: "var(--coral-strong)", marginBottom: 8 }}>RADAR DATA UNAVAILABLE</p>
          <p style={{ color: "var(--ink-soft)", lineHeight: "var(--leading-body)" }}>{error}</p>
          <p style={{ marginTop: 10, color: "var(--ink-faint)", fontSize: "var(--text-small)" }}>We couldn&apos;t retrieve the latest business activity. Your existing data has not been changed.</p>
          <div style={{ marginTop: 16 }}><Button variant="primary" mono onClick={() => setRefreshKey((k) => k + 1)}>Retry</Button></div>
        </WindowPanel>
      </section>
    );
  }
  if (loading && !radar) {
    return (
      <section className="shell rg-page">
        <div className="rg-topHead rg-topHead--skeleton">
          <div className="rg-skeleton rg-skeleton--title" />
          <div className="rg-skeleton rg-skeleton--line" />
        </div>
        <div className="rg-kpiGrid">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="rg-kpi rg-kpi--skeleton"><div className="rg-skeleton rg-skeleton--kpi" /></div>
          ))}
        </div>
        <div className="rg-grid12" style={{ marginTop: 22 }}>
          <div className="rg-span8"><div className="rg-skeleton rg-skeleton--chartLg" /></div>
          <div className="rg-span4"><div className="rg-skeleton rg-skeleton--chartLg" /></div>
        </div>
      </section>
    );
  }
  if (!radar || !metrics || !sufficiency) {
    return (
      <section className="shell rg-page"><WindowPanel title="growth-radar.app"><p className="meta-label">Analysing your business…</p></WindowPanel></section>
    );
  }

  return (
    <section className="shell rg-page" aria-labelledby="radar-heading">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header className="rg-header">
        <div className="rg-header__main">
          <p className="meta-label" style={{ letterSpacing: "0.14em" }}>YOUR BUSINESS · GROWTH RADAR</p>
          <h1 id="radar-heading" className="rg-display">Growth Radar</h1>
          <p className="rg-header__lede">Understand what is happening in your business — and where your AI Growth Team should look next.</p>
          <div className="rg-controls" role="toolbar" aria-label="Dashboard controls">
            <div className="rg-controls__group" aria-label="Date range">
              {[7, 14, 30, 90].map((d) => (
                <button
                  key={d}
                  type="button"
                  className={`rg-ctrl ${windowDays === d ? "rg-ctrl--active" : ""}`}
                  aria-pressed={windowDays === d}
                  onClick={() => setWindowDays(d)}
                >
                  {d}D
                </button>
              ))}
            </div>
            <span className="rg-controls__sep" aria-hidden="true" />
            <button type="button" className={`rg-ctrl rg-ctrl--toggle ${compare ? "rg-ctrl--on" : ""}`} aria-pressed={compare} onClick={() => setCompare((v) => !v)}>
              <span className="rg-ctrl__dot" aria-hidden="true" />
              Compare previous period
            </button>
            <button type="button" className="rg-ctrl rg-ctrl--refresh" onClick={() => setRefreshKey((k) => k + 1)}>
              ↻ Refresh data
            </button>
          </div>
          <p className="rg-header__meta">
            Last {windowDays} days · {new Date(radar.generated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })} · Merchant {radar.merchant_id.slice(0, 8)}…
          </p>
        </div>
        <div className="rg-header__side">
          <span className="rg-live">
            <span className="rg-live__dot" aria-hidden="true" />
            LIVE BUSINESS DATA
          </span>
          <div className="rg-sideCard">
            <p className="meta-label" style={{ marginBottom: 6 }}>DATA WINDOW</p>
            <p className="rg-sideCard__value">Last {windowDays} days</p>
            <p className="rg-sideCard__hint">{compare ? "Comparing to previous period" : "Single period view"}</p>
          </div>
        </div>
      </header>

      {/* Empty-business banner — premium not alarmist */}
      {isEmptyBusiness && (
        <div className="rg-emptyBanner">
          <p className="meta-label" style={{ color: "var(--choc-900)", marginBottom: 6 }}>YOUR BUSINESS DATA IS STILL BUILDING</p>
          <p>Connect your payment data or create transactions through Checkout to unlock business intelligence. Your dashboard is ready — it will populate as real activity arrives.</p>
          <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Button variant="primary" mono onClick={() => navigate("/checkout")}>Create test transaction →</Button>
            <Button variant="secondary" mono onClick={() => navigate("/agents")}>Meet the AI Team →</Button>
          </div>
        </div>
      )}

      {/* ── KPI Grid ───────────────────────────────────────────────────── */}
      <div className="rg-sectionHead" style={{ marginTop: isEmptyBusiness ? 22 : 28 }}>
        <h2 className="meta-label" style={{ margin: 0, color: "var(--ink)" }}>BUSINESS OVERVIEW</h2>
        <span className="meta-label" style={{ color: "var(--ink-faint)" }}>
          MEASURED FROM REAL ACTIVITY · {sufficiency.available} / {sufficiency.minimum_required} TXNS
        </span>
      </div>
      <div className="rg-kpiGrid">
        <article className="rg-kpi">
          <p className="rg-kpi__label">REVENUE CAPTURED</p>
          <p className="rg-kpi__value">{rupees(metrics.captured_revenue, true)}</p>
          <p className="rg-kpi__note">Money successfully received through completed transactions.</p>
          {compare && revenueChange !== null && (
            <p className={`rg-kpi__trend ${revenueChange >= 0 ? "rg-kpi__trend--up" : "rg-kpi__trend--down"}`}>
              {revenueChange >= 0 ? "↗" : "↘"} {Math.abs(revenueChange).toFixed(1)}% vs previous · {rupees(revenuePrev ?? 0, true)} before
            </p>
          )}
          {!compare && <p className="rg-kpi__sub">{count(metrics.captured_transactions, "transaction")} in window</p>}
        </article>
        <article className="rg-kpi">
          <p className="rg-kpi__label">TRANSACTIONS</p>
          <p className="rg-kpi__value">{metrics.captured_transactions}</p>
          <p className="rg-kpi__note">Successful purchases completed.</p>
          {totalPayments > 0 && <p className="rg-kpi__sub">{successPct.toFixed(0)}% of {totalPayments} payment attempts</p>}
        </article>
        <article className="rg-kpi">
          <p className="rg-kpi__label">CUSTOMERS</p>
          <p className="rg-kpi__value">{metrics.total_customers}</p>
          <p className="rg-kpi__note">Unique customers who have transacted.</p>
          {metrics.total_customers > 0 && <p className="rg-kpi__sub">{metrics.repeat_customers} repeat · {repeatShare}% return rate</p>}
        </article>
        <article className="rg-kpi">
          <p className="rg-kpi__label">ORDERS</p>
          <p className="rg-kpi__value">{metrics.total_orders}</p>
          <p className="rg-kpi__note">Orders created across your channels.</p>
          {overview && <p className="rg-kpi__sub">{overview.orders.completed_orders} completed · {overview.orders.cancelled_orders} cancelled</p>}
        </article>
        <article className="rg-kpi">
          <p className="rg-kpi__label">AVERAGE ORDER VALUE</p>
          <p className="rg-kpi__value">{rupees(metrics.average_order_value, true)}</p>
          <p className="rg-kpi__note">Average spend per purchase.</p>
          {metrics.captured_transactions > 0 && <p className="rg-kpi__sub">{rupees(metrics.captured_revenue / Math.max(1, metrics.captured_transactions), true)} realised</p>}
        </article>
        <article className={`rg-kpi ${failedPayments > 0 ? "rg-kpi--warn" : ""}`}>
          <p className="rg-kpi__label">FAILED PAYMENTS</p>
          <p className={`rg-kpi__value ${failedPayments > 0 ? "rg-kpi__value--warn" : ""}`}>{failedPayments}</p>
          <p className="rg-kpi__note">Unsuccessful payments that may hold recoverable revenue.</p>
          {totalPayments > 0 ? <p className="rg-kpi__sub">{failedPct.toFixed(0)}% of attempts · {successPct.toFixed(0)}% success</p> : <p className="rg-kpi__sub">No payment attempts in window</p>}
        </article>
      </div>

      {/* ── Business Health ────────────────────────────────────────────── */}
      <div className="rg-healthCard">
        <div className="rg-healthCard__left">
          <p className="meta-label" style={{ marginBottom: 8 }}>BUSINESS HEALTH</p>
          <div className="rg-healthBadgeRow">
            <span className={`rg-healthBadge rg-healthBadge--${health.tone}`}>{health.label}</span>
            <span className="meta-label" style={{ color: "var(--ink-faint)" }}>{radar.overall_health.replace(/_/g, " ").toUpperCase()}</span>
          </div>
          <p className="rg-healthCard__story">{story}</p>
          <p className="rg-healthCard__desc">{health.desc}</p>
        </div>
        <div className="rg-healthCard__right">
          <div className="rg-healthStats">
            <div className="rg-healthStat">
              <span className="rg-healthStat__k">Revenue</span>
              <span className="rg-healthStat__v">{rupees(revenueCurrent, true)}</span>
              {compare && revenueChange !== null && <span className={`rg-healthStat__delta ${revenueChange >= 0 ? "is-up" : "is-down"}`}>{revenueChange >= 0 ? "+" : ""}{revenueChange.toFixed(1)}%</span>}
            </div>
            <div className="rg-healthStat">
              <span className="rg-healthStat__k">Payments</span>
              <span className="rg-healthStat__v">{successPayments} / {totalPayments || "—"}</span>
              <span className="rg-healthStat__delta">{totalPayments > 0 ? `${successPct.toFixed(0)}% success` : "no attempts"}</span>
            </div>
            <div className="rg-healthStat">
              <span className="rg-healthStat__k">Signals</span>
              <span className="rg-healthStat__v">{ranked.length} found</span>
              <span className="rg-healthStat__delta">{ranked.length ? `${pct(ranked[0].confidence)}% top confidence` : "building history"}</span>
            </div>
          </div>
          <p className="rg-healthCard__foot">Health reflects payment success, signal risk, and data sufficiency — all measured from your workspace, never global data.</p>
        </div>
      </div>

      {/* ── Business Performance: Revenue Trend + Payment Performance ──── */}
      <div className="rg-sectionHead">
        <h2 className="meta-label" style={{ margin: 0, color: "var(--ink)" }}>BUSINESS PERFORMANCE</h2>
        <span className="meta-label" style={{ color: "var(--ink-faint)" }}>REVENUE · PAYMENTS · LAST {windowDays} DAYS</span>
      </div>
      <div className="rg-grid12">
        <div className="rg-span8">
          <div className="rg-panel">
            <div className="rg-panel__head">
              <div>
                <p className="meta-label" style={{ marginBottom: 4 }}>REVENUE TREND</p>
                <h3 className="rg-panel__title">Revenue over time</h3>
              </div>
              <span className="rg-chip">{rupees(revenueCurrent, true)} this period</span>
            </div>
            <p className="rg-panel__lede">
              Revenue captured from successful Razorpay payments. Each point is a day{windowDays > 31 ? " / week" : ""} in the selected window
              {compare && revenuePrev !== null ? ` — previous period was ${rupees(revenuePrev, true)}.` : "."}
            </p>
            <RevenueTrendChart data={revSeries ?? []} loading={revSeries === null} />
            <div className="rg-panel__foot">
              <span className="meta-label" style={{ color: "var(--ink-faint)" }}>{revSeries ? `${revSeries.length} data points` : "—"} · cream surface · terracotta trend</span>
              {compare && revenueChange !== null && <span className={`meta-label ${revenueChange >= 0 ? "rg-compare--up" : "rg-compare--down"}`}>{revenueChange >= 0 ? "▲" : "▼"} {Math.abs(revenueChange).toFixed(1)}% vs previous</span>}
            </div>
          </div>
        </div>
        <div className="rg-span4">
          <div className="rg-panel rg-panel--tall">
            <div className="rg-panel__head">
              <div>
                <p className="meta-label" style={{ marginBottom: 4 }}>PAYMENT PERFORMANCE</p>
                <h3 className="rg-panel__title">Success vs failed</h3>
              </div>
            </div>
            <p className="rg-panel__lede" style={{ marginBottom: 14 }}>
              {totalPayments > 0
                ? `${count(successPayments, "payment")} went through and ${count(failedPayments, "payment")} did not — ${failedPct.toFixed(0)}% of all attempts.`
                : "No payment attempts in this window."}
            </p>
            <div style={{ display: "flex", justifyContent: "center", padding: "8px 0 6px" }}>
              <DonutChart successful={successPayments} failed={failedPayments} />
            </div>
            <div className="rg-metricRow">
              <div className="rg-metricRow__item">
                <span className="meta-label">SUCCESSFUL</span>
                <strong>{successPayments}</strong>
                <span>{successPct.toFixed(0)}%</span>
              </div>
              <div className="rg-metricRow__item rg-metricRow__item--warn">
                <span className="meta-label">FAILED</span>
                <strong>{failedPayments}</strong>
                <span>{failedPct.toFixed(0)}%</span>
              </div>
              <div className="rg-metricRow__item">
                <span className="meta-label">SUCCESS RATE</span>
                <strong>{successPct.toFixed(0)}%</strong>
                <span>{totalPayments} total</span>
              </div>
            </div>
            <p className="rg-panel__explain">
              {failedPayments > 0
                ? `${successPayments} of ${totalPayments} payment attempts completed successfully. The remaining ${failedPayments} failure${failedPayments === 1 ? "" : "s"} indicate customers who attempted to purchase but did not complete payment.`
                : totalPayments > 0
                  ? `All ${count(successPayments, "payment")} went through successfully — no recovery backlog this period.`
                  : "Payment performance will populate as Checkout activity is recorded."}
            </p>
          </div>
        </div>
      </div>

      {/* ── Customer & Order Activity ───────────────────────────────────── */}
      <div className="rg-sectionHead">
        <h2 className="meta-label" style={{ margin: 0, color: "var(--ink)" }}>CUSTOMER & ORDER ACTIVITY</h2>
        <span className="meta-label" style={{ color: "var(--ink-faint)" }}>BEHAVIOR · REPEAT · VOLUME</span>
      </div>
      <div className="rg-grid12">
        <div className="rg-span6">
          <div className="rg-panel">
            <div className="rg-panel__head">
              <div>
                <p className="meta-label" style={{ marginBottom: 4 }}>CUSTOMER ACTIVITY</p>
                <h3 className="rg-panel__title">Who is buying</h3>
              </div>
              <span className="rg-chip rg-chip--muted">{metrics.total_customers} total</span>
            </div>
            <div className="rg-customerGrid">
              <div className="rg-customerStats">
                <div className="rg-cStat">
                  <span className="meta-label">TOTAL CUSTOMERS</span>
                  <strong>{metrics.total_customers}</strong>
                  <span>Unique customers who have transacted</span>
                </div>
                <div className="rg-cStat">
                  <span className="meta-label">REPEAT CUSTOMERS</span>
                  <strong>{metrics.repeat_customers}</strong>
                  <span>{repeatShare}% repeat rate</span>
                </div>
                <div className="rg-cStat">
                  <span className="meta-label">FIRST-TIME</span>
                  <strong>{Math.max(0, metrics.total_customers - metrics.repeat_customers)}</strong>
                  <span>New this window</span>
                </div>
              </div>
              <CustomersDonut total={metrics.total_customers} repeat={metrics.repeat_customers} />
            </div>
            {/* mini customer trend */}
            <div className="rg-miniTrend">
              <p className="meta-label" style={{ marginBottom: 8 }}>NEW CUSTOMERS OVER TIME</p>
              {custSeries && custSeries.length > 0 ? (
                <div className="rg-miniBars">
                  {custSeries.slice(-14).map((d, i) => {
                    const max = Math.max(...custSeries.map((x) => x.value), 1);
                    const h = Math.max(4, (d.value / max) * 36);
                    return <span key={i} className="rg-miniBar" style={{ height: h }} title={`${fmtDateShort(d.date)}: ${d.value}`} />;
                  })}
                </div>
              ) : (
                <p className="rg-emptyChart__hint">{custSeries === null ? "Loading…" : "No customer activity recorded."}</p>
              )}
            </div>
            <p className="rg-panel__explain">
              {metrics.total_customers === 0
                ? "No customer activity recorded yet. As transactions arrive, repeat vs first-time patterns will emerge here."
                : metrics.repeat_customers === 0
                  ? "Customer activity currently shows first-time purchasing behavior. As transaction history grows, the dashboard can identify repeat purchasing patterns."
                  : `${metrics.repeat_customers} of ${metrics.total_customers} customers have returned to buy again — a ${repeatShare}% repeat rate. Returning customers are typically cheaper to serve than new ones.`}
            </p>
          </div>
        </div>
        <div className="rg-span6">
          <div className="rg-panel">
            <div className="rg-panel__head">
              <div>
                <p className="meta-label" style={{ marginBottom: 4 }}>ORDER PERFORMANCE</p>
                <h3 className="rg-panel__title">Order activity</h3>
              </div>
              <span className="rg-chip rg-chip--muted">{metrics.total_orders} orders</span>
            </div>
            <p className="rg-panel__lede" style={{ marginBottom: 12 }}>
              {metrics.total_orders === 0 ? "No orders in this window." : `Orders created across your channels — ${overview?.orders.completed_orders ?? metrics.total_orders} completed.`}
            </p>
            <OrdersBarChart data={orderSeries ?? []} loading={orderSeries === null} />
            <div className="rg-orderStats">
              <span><strong>{overview?.orders.total_orders ?? metrics.total_orders}</strong> total</span>
              <span><strong>{overview?.orders.completed_orders ?? "—"}</strong> completed</span>
              <span><strong>{overview?.orders.cancelled_orders ?? "—"}</strong> cancelled</span>
              <span><strong>{rupees(overview ? toNum((overview.orders as unknown as Record<string, unknown>).average_order_value, metrics.average_order_value) : metrics.average_order_value, true)}</strong> AOV</span>
            </div>
          </div>
        </div>
      </div>

      {/* Flow */}
      <div className="rg-flow" aria-hidden="true">
        <span>Business health</span>
        <span className="rg-flow__rule" />
        <span>What the radar found</span>
        <span className="rg-flow__rule" />
        <span>What to do next</span>
      </div>

      {/* ── Detected Growth Signals ─────────────────────────────────────── */}
      <div className="rg-sectionHead">
        <h2 className="meta-label" style={{ margin: 0, color: "var(--ink)" }}>DETECTED GROWTH SIGNALS</h2>
        <span className="meta-label" style={{ color: "var(--ink-faint)" }}>{ranked.length} FOUND · CONFIDENCE RANKED</span>
      </div>
      <p className="rg-sectionLede">
        The radar compares your recent business activity against the previous period to identify patterns worth attention. These are not just activity numbers — they highlight where your business may recover revenue, increase order value, or win back customers.
      </p>
      {ranked.length === 0 ? (
        <WindowPanel title="no-signals.app">
          <p style={{ color: "var(--ink-soft)", lineHeight: "var(--leading-body)" }}>
            No growth signals detected yet. This usually means your account is still building transaction history. Add more real orders and payments to unlock AI growth analysis.
          </p>
          {sufficiency.available < sufficiency.minimum_required && (
            <p style={{ marginTop: 12, fontFamily: "var(--font-mono)", fontSize: "var(--text-meta)", textTransform: "uppercase", letterSpacing: "var(--tracking-meta)", color: "var(--ink-faint)" }}>
              {sufficiency.minimum_required - sufficiency.available} more transactions needed to unlock AI analysis.
            </p>
          )}
        </WindowPanel>
      ) : (
        <div className="rg-signals">
          {ranked.map((signal, i) => {
            const badge = priorityBadge(signal.confidence);
            return (
              <article className="rg-signal" key={`${signal.signal}-${i}`}>
                <div className="rg-signal__bar">
                  <span>SIGNAL {String(i + 1).padStart(2, "0")}</span>
                  <span className={`rg-prio ${badge.cls}`}>{badge.text}</span>
                  <span>{pct(signal.confidence)}% CONFIDENCE</span>
                </div>
                <div className="rg-signal__body">
                  <h3 className="rg-signal__title">{signal.title}</h3>
                  <p className="rg-signal__evidence">{signalEvidence(signal)}</p>
                  <div className="rg-signal__grid">
                    <div className="rg-signal__cell">
                      <p className="rg-cellLabel">WHY THIS MATTERS</p>
                      <p>{opportunityWhy(signal.signal)}</p>
                    </div>
                    <div className="rg-signal__cell">
                      <p className="rg-cellLabel">OPPORTUNITY</p>
                      <p className="rg-signal__opp">{signal.opportunity}</p>
                    </div>
                    <div className="rg-signal__cell rg-signal__cell--action">
                      <p className="rg-cellLabel" style={{ color: "var(--coral-strong)" }}>NEXT STEP</p>
                      <p>{signal.recommended_action}</p>
                    </div>
                  </div>
                  <div className="rg-signal__foot">
                    <div className="rg-signal__meta">
                      <span className="meta-label">EVIDENCE</span>
                      <span>{signal.calculated_metric}</span>
                      <span className="meta-label">·</span>
                      <span>“{signal.reason}”</span>
                    </div>
                    <Button variant="primary" mono onClick={() => handleInvestigate(signal.title, signal.opportunity)}>Investigate with AI Team →</Button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* ── Growth Opportunities ────────────────────────────────────────── */}
      {ranked.length > 0 && (
        <>
          <div className="rg-sectionHead">
            <h2 className="meta-label" style={{ margin: 0, color: "var(--ink)" }}>GROWTH OPPORTUNITIES</h2>
            <span className="meta-label" style={{ color: "var(--ink-faint)" }}>AI-RANKED · RANKED BY STRENGTH OF EVIDENCE</span>
          </div>
          <p className="rg-sectionLede">AI-ranked opportunities based on evidence from your business activity. Each comes from a real signal with verifiable evidence and a practical next step.</p>
          {priority && (
            <div className="rg-priority">
              <div className="rg-priority__bar">
                <span>PRIORITY OPPORTUNITY · STRONGEST EVIDENCE</span>
                <span>{pct(priority.confidence)}% CONFIDENCE</span>
              </div>
              <div className="rg-priority__body">
                <p className="rg-priority__kicker">01 · {priority.signal.replace(/_/g, " ").toUpperCase()}</p>
                <h3 className="rg-priority__title">{priority.opportunity}</h3>
                {potentialImpact(priority) !== null && <p className="rg-priority__impact">Potential impact · {rupees(potentialImpact(priority) as number, true)}</p>}
                <div className="rg-priority__grid">
                  <div className="rg-priority__cell">
                    <p className="rg-priority__label">WHY IT MATTERS</p>
                    <p>{opportunityWhy(priority.signal)}</p>
                  </div>
                  <div className="rg-priority__cell">
                    <p className="rg-priority__label">EVIDENCE</p>
                    <p>{signalEvidence(priority)} Detected signal: “{priority.title}”.</p>
                  </div>
                  <div className="rg-priority__cell">
                    <p className="rg-priority__label">RECOMMENDED ACTION</p>
                    <p>{priority.recommended_action}</p>
                  </div>
                </div>
                <div className="rg-priority__cta">
                  <p>Top-ranked by confidence and evidence strength — the AI Team should look here first.</p>
                  <Button variant="primary" mono onClick={() => handleInvestigate(priority.title, priority.opportunity)}>Investigate with AI Team →</Button>
                </div>
              </div>
            </div>
          )}
          {rest.length > 0 && (
            <div className="rg-opps">
              {rest.map((s, i) => (
                <article className="rg-opp" key={`${s.signal}-${i}`}>
                  <p className="meta-label" style={{ color: "var(--ink-faint)", marginBottom: 6 }}>{String(i + 2).padStart(2, "0")} · {priorityBadge(s.confidence).text}</p>
                  <h3 className="rg-opp__title">{s.opportunity}</h3>
                  {potentialImpact(s) !== null && <p className="rg-opp__impact">Potential impact · {rupees(potentialImpact(s) as number, true)}</p>}
                  <div className="rg-opp__block">
                    <p className="rg-cellLabel">WHY IT MATTERS</p>
                    <p>{opportunityWhy(s.signal)}</p>
                  </div>
                  <div className="rg-opp__block">
                    <p className="rg-cellLabel">EVIDENCE</p>
                    <p>{signalEvidence(s)}</p>
                  </div>
                  <div className="rg-opp__block">
                    <p className="rg-cellLabel">RECOMMENDED ACTION</p>
                    <p>{s.recommended_action}</p>
                  </div>
                  <div className="rg-opp__foot">
                    <span className="meta-label" style={{ color: "var(--green-deep)" }}>{pct(s.confidence)}% CONFIDENCE</span>
                    <Button variant="secondary" mono onClick={() => handleInvestigate(s.title, s.opportunity)}>Investigate →</Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── Radar → AI Team ─────────────────────────────────────────────── */}
      <div className="rg-bridge">
        <div className="rg-bridge__head">
          <p className="meta-label" style={{ color: "var(--coral)", marginBottom: 6 }}>RADAR → AI TEAM</p>
          <h2 className="rg-bridge__title">The Radar finds the signal. The AI Team investigates it.</h2>
          <p className="rg-bridge__lede">The Growth Radar detects business signals. Your AI Growth Team investigates them, debates the evidence, and proposes actions.</p>
        </div>
        <div className="rg-bridge__flow" aria-hidden="true">
          <span className="rg-bridge__node">Radar</span>
          <span className="rg-bridge__arrow">→</span>
          <span className="rg-bridge__node">Signals</span>
          <span className="rg-bridge__arrow">→</span>
          <span className="rg-bridge__node">AI investigation</span>
          <span className="rg-bridge__arrow">→</span>
          <span className="rg-bridge__node">Debate</span>
          <span className="rg-bridge__arrow">→</span>
          <span className="rg-bridge__node rg-bridge__node--accent">Action</span>
        </div>
        <div className="rg-bridge__cta">
          <Button variant="primary" mono onClick={() => navigate("/agents")}>Investigate with AI Team →</Button>
          <Button variant="secondary" mono onClick={() => navigate("/actions")}>Review Growth Actions →</Button>
        </div>
      </div>

      {/* ── Data Coverage ───────────────────────────────────────────────── */}
      <div className="rg-coverage">
        <div className="rg-coverage__left">
          <p className="meta-label" style={{ marginBottom: 6 }}>DATA COVERAGE · {sufficiency.status === "sufficient" ? "SUFFICIENT BUSINESS DATA AVAILABLE" : "BUILDING TRANSACTION HISTORY"}</p>
          <p className="rg-coverage__note">{sufficiency.message}</p>
          <p className="rg-coverage__hint">{sufficiency.available} of {sufficiency.minimum_required} required transactions · {coveragePct}% coverage · {totalPayments} payment attempts in window</p>
        </div>
        <div className="rg-coverage__meter">
          <p className="meta-label" style={{ marginBottom: 8 }}>{sufficiency.available} / {sufficiency.minimum_required} TRANSACTIONS RECORDED</p>
          <div className="rg-coverage__track" role="progressbar" aria-valuenow={coveragePct} aria-valuemin={0} aria-valuemax={100} aria-label="Transaction history coverage">
            <div className={`rg-coverage__fill ${coveragePct < 100 ? "rg-coverage__fill--low" : ""}`} style={{ width: `${coveragePct}%` }} />
          </div>
          <p className="rg-coverage__scale">
            <span>0</span>
            <span>{coveragePct}%</span>
            <span>100%</span>
          </p>
        </div>
      </div>

      {/* Footer */}
      <div className="rg-footer">
        <p>{ranked.length > 0 ? "Investigate any opportunity above to have your AI Growth Team analyse it in depth." : "Your AI Growth Team is ready when you have sufficient data."}</p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {ranked.length > 0 && <Button variant="secondary" mono onClick={() => navigate("/agents")}>Meet the AI Growth Team →</Button>}
          <Button variant="primary" mono onClick={() => navigate("/actions")}>Review Growth Actions →</Button>
        </div>
      </div>
    </section>
  );
}
