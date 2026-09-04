/**
 * /growth-radar — Business health and signals for the merchant's workspace.
 *
 * Reads real commerce data from PostgreSQL.
 * Every signal with sufficient confidence exposes an "Investigate" CTA
 * that starts an AI Growth Investigation (growth_team orchestration).
 *
 * MERCHANT LANGUAGE ONLY — no API endpoints, no database terms.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchGrowthRadar } from "../lib/api";
import { useAuth } from "../lib/AuthContext";
import type { GrowthRadarResponse } from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";

export function GrowthRadar() {
  const { user } = useAuth();
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
  const merchantName = (user?.memberships?.length ?? 0) > 0 ? undefined : undefined; // will come from merchant context later

  return (
    <section className="shell section" aria-labelledby="radar-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">YOUR BUSINESS · GROWTH RADAR</p>
        <h1 id="radar-heading" className="display-lg" style={{ marginTop: 10 }}>
          Growth Radar
        </h1>
        <p style={{ color: "var(--ink-soft)", maxWidth: "60ch", marginTop: 8 }}>
          Your business health at a glance — measured from real payments, orders, and customers.
        </p>
      </div>

      {/* Business health overview */}
      <WindowPanel title="business-health.app" tone="choc" dark>
        <p className="meta-label" style={{ marginBottom: 18 }}>
          BUSINESS HEALTH · {radar.overall_health.replace(/_/g, " ").toUpperCase()}
        </p>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 20,
          marginBottom: 24,
        }}>
          <Metric
            label="Revenue captured"
            value={`₹${metrics.captured_revenue.toFixed(2)}`}
            explanation="Money successfully received through recent transactions."
          />
          <Metric
            label="Transactions"
            value={metrics.captured_transactions}
            explanation="Number of successful purchases completed."
          />
          <Metric
            label="Customers"
            value={metrics.total_customers}
            explanation="Unique customers who have transacted with your business."
          />
          <Metric
            label="Orders"
            value={metrics.total_orders}
            explanation="Total orders created across your channels."
          />
          <Metric
            label="Average order value"
            value={`₹${metrics.average_order_value.toFixed(2)}`}
            explanation="Average amount customers spend per purchase."
          />
          <Metric
            label="Failed payments"
            value={metrics.failed_payments}
            warn={metrics.failed_payments > 0}
            explanation="Unsuccessful payments representing recoverable revenue."
          />
        </div>

        {/* Data sufficiency */}
        <div style={{
          padding: "14px 16px",
          border: `1px solid ${sufficiency.status === "sufficient" ? "var(--green)" : "rgba(247,235,215,0.3)"}`,
          borderRadius: "var(--radius-window)",
          background: sufficiency.status === "sufficient" ? "rgba(112,184,138,0.12)" : "rgba(247,235,215,0.06)",
        }}>
          <p className="meta-label" style={{ marginBottom: 6 }}>
            DATA COVERAGE · {sufficiency.status.toUpperCase()}
          </p>
          <p style={{ color: "var(--cream-muted)", fontSize: "var(--text-small)", marginBottom: 4 }}>
            {sufficiency.message}
          </p>
          <p className="meta-label" style={{ color: "var(--cream-muted)" }}>
            {sufficiency.available} of {sufficiency.minimum_required} transactions recorded
          </p>
        </div>
      </WindowPanel>

      {/* Signals */}
      <div style={{ marginTop: 24 }}>
        <p className="meta-label" style={{ marginBottom: 14 }}>DETECTED GROWTH SIGNALS</p>

        {radar.signals.length === 0 ? (
          <WindowPanel title="no-signals.app">
            <p style={{ color: "var(--ink-soft)", lineHeight: "var(--leading-body)" }}>
              No growth signals detected yet. This usually means your account is still building
              transaction history. Add more real orders and payments to unlock AI growth analysis.
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
                {sufficiency.minimum_required - sufficiency.available} more transactions needed
                to unlock AI analysis.
              </p>
            )}
          </WindowPanel>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {radar.signals.map((signal, i) => (
              <SignalCard
                key={i}
                signal={signal}
                onInvestigate={handleInvestigate}
              />
            ))}
          </div>
        )}
      </div>

      {/* Navigation footer */}
      <div style={{
        marginTop: 32,
        paddingTop: 24,
        borderTop: "1px solid var(--line-soft)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
      }}>
        <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)" }}>
          {radar.signals.length > 0
            ? "Investigate any signal above to have your AI Growth Team analyse it in depth."
            : "Your AI Growth Team is ready when you have sufficient data."}
        </p>
        {radar.signals.length > 0 && (
          <Button
            variant="secondary"
            mono
            onClick={() => navigate("/agents")}
          >
            Meet the AI Growth Team →
          </Button>
        )}
      </div>
    </section>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function Metric({
  label,
  value,
  explanation,
  warn = false,
}: {
  label: string;
  value: string | number;
  explanation?: string;
  warn?: boolean;
}) {
  return (
    <div>
      <p className="meta-label" style={{ marginBottom: 6 }}>{label}</p>
      <p style={{
        color: warn ? "var(--coral)" : "var(--green)",
        fontSize: "var(--text-title)",
        fontWeight: 700,
        lineHeight: 1,
        fontFamily: "var(--font-mono)",
      }}>
        {value}
      </p>
      {explanation && (
        <p style={{
          marginTop: 6,
          fontSize: "var(--text-meta)",
          color: "var(--cream-muted)",
          lineHeight: 1.35,
        }}>
          {explanation}
        </p>
      )}
    </div>
  );
}

interface SignalCardProps {
  signal: {
    signal: string;
    title: string;
    opportunity: string;
    confidence: number;
    reason: string;
    recommended_action: string;
  };
  onInvestigate: (title: string, opportunity: string) => void;
}

function SignalCard({ signal, onInvestigate }: SignalCardProps) {
  const confidencePct = Math.round(signal.confidence * 100);

  return (
    <WindowPanel title={`signal-${signal.signal.toLowerCase().replace(/[^a-z0-9]/g, "-")}.app`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {/* Header row */}
        <div style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}>
          <h2 style={{ fontSize: "var(--text-title)", fontWeight: 700, color: "var(--ink)", margin: 0, flex: 1 }}>
            {signal.title}
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            <span style={{
              fontFamily: "var(--font-mono)",
              fontSize: "var(--text-meta)",
              textTransform: "uppercase",
              letterSpacing: "var(--tracking-meta)",
              color: confidencePct >= 70 ? "var(--green-deep)" : "var(--ink-soft)",
            }}>
              {confidencePct}% confidence
            </span>
          </div>
        </div>

        {/* Why this signal */}
        <p style={{ color: "var(--ink-soft)", fontSize: "var(--text-body)", lineHeight: "var(--leading-body)" }}>
          {signal.reason}
        </p>

        {/* Opportunity */}
        <div style={{
          padding: "10px 14px",
          background: "var(--paper-deep)",
          border: "1px solid var(--line-soft)",
          borderRadius: "var(--radius-window)",
          borderLeft: "3px solid var(--coral)",
        }}>
          <p className="meta-label" style={{ marginBottom: 4 }}>OPPORTUNITY</p>
          <p style={{ fontSize: "var(--text-small)", color: "var(--ink)", lineHeight: 1.5 }}>
            {signal.opportunity}
          </p>
        </div>

        {/* Recommended action + CTA */}
        <div style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          paddingTop: 4,
        }}>
          <div style={{ flex: 1 }}>
            <p className="meta-label" style={{ marginBottom: 4 }}>SUGGESTED ACTION</p>
            <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)" }}>
              {signal.recommended_action}
            </p>
          </div>
          <Button
            variant="primary"
            mono
            onClick={() => onInvestigate(signal.title, signal.opportunity)}
          >
            Investigate with AI Team →
          </Button>
        </div>
      </div>
    </WindowPanel>
  );
}
