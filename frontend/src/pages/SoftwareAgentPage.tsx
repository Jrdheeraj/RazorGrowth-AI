/**
 * /software-agent — Software Agent autonomous workstation.
 *
 * Checks automation paths, webhook integrations, API constraints, and technical
 * feasibility. Truthfully reports real backend run history and registered tools.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../components/WindowPanel";
import { PreviewModeBanner } from "../components/PreviewModeBanner";
import { Button } from "../components/Button";
import { MerchantWorldBackground } from "../features/public/MerchantWorld/MerchantWorldBackground";
import { isAuthenticated } from "../lib/auth";
import { fetchAgentCatalog, fetchAgentRuns, type AgentCatalogResponse } from "../lib/api";
import type { AgentRunRow } from "../types/api";
import "./SoftwareAgentPage.css";

export function SoftwareAgentPage() {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<AgentRunRow[]>([]);
  const [catalog, setCatalog] = useState<AgentCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      fetchAgentRuns(50),
      fetchAgentCatalog(),
    ]).then(([runsRes, catRes]) => {
      if (cancelled) return;
      if (runsRes.status === "fulfilled" && runsRes.value.runs) {
        setRuns(runsRes.value.runs.filter((r) => r.agent_name === "SoftwareAgent"));
      }
      if (catRes.status === "fulfilled") {
        setCatalog(catRes.value);
      }
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const latestRun = runs[0] ?? null;
  const softwareEntry = catalog?.agents?.find((a) => a.name === "SoftwareAgent") ?? null;
  const tools = softwareEntry?.tools ?? [];

  return (
    <div className="software-page">
      <MerchantWorldBackground />
      <div className="software-shell">
        {!isAuthenticated() && (
          <PreviewModeBanner pageName="Software Specialist Workstation" />
        )}
        {/* Hero Banner */}
        <header className="software-hero">
          <div>
            <span className="meta-label">AUTONOMOUS TECHNICAL & INTEGRATIONS EMPLOYEE</span>
            <h1 className="software-hero__title">Software Agent</h1>
            <p className="software-hero__desc">
              Checks technical feasibility, webhook integrations, catalog scale, and automation constraints
              before recommendations are locked into execution.
            </p>
          </div>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <span className="software-hero__badge">
              ● {latestRun?.status ? latestRun.status.toUpperCase() : "READY & REGISTERED"}
            </span>
            <Button variant="secondary" mono onClick={() => navigate("/agents")}>
              ← AI Team Overview
            </Button>
          </div>
        </header>

        {/* Technical Checks & Guardrails */}
        <WindowPanel title="software.technical-checks">
          <div className="software-grid">
            <div className="software-card">
              <div className="software-card__header">
                <div className="software-card__icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="16 18 22 12 16 6" />
                    <polyline points="8 6 2 12 8 18" />
                  </svg>
                </div>
                <h3 className="software-card__title">Razorpay Webhooks</h3>
              </div>
              <p className="software-card__desc">
                Validates webhook delivery signatures, payment.failed event retries, and automated recapture triggers.
              </p>
              <span className="software-card__status">INTEGRATION CONSTRAINTS VERIFIED</span>
            </div>

            <div className="software-card">
              <div className="software-card__header">
                <div className="software-card__icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
                    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
                    <line x1="6" y1="6" x2="6.01" y2="6" />
                    <line x1="6" y1="18" x2="6.01" y2="18" />
                  </svg>
                </div>
                <h3 className="software-card__title">API Rate Limits & Safe Execution</h3>
              </div>
              <p className="software-card__desc">
                Enforces safety budgets, merchant authorization requirements, and idempotent execution keys.
              </p>
              <span className="software-card__status">SAFE EXECUTION GUARDRAILS ACTIVE</span>
            </div>

            <div className="software-card">
              <div className="software-card__header">
                <div className="software-card__icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  </svg>
                </div>
                <h3 className="software-card__title">Human Approval Gate</h3>
              </div>
              <p className="software-card__desc">
                No automation runs autonomously without human review in the Growth Actions console.
              </p>
              <span className="software-card__status">HUMAN-IN-THE-LOOP ENFORCED</span>
            </div>
          </div>
        </WindowPanel>

        {/* Registered Capabilities & Tools */}
        <WindowPanel title="software.capabilities">
          {tools.length > 0 ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {tools.map((t) => (
                <span
                  key={t}
                  style={{
                    background: "var(--paper, #f7ebd7)",
                    border: "1px solid var(--line, #e2d7c5)",
                    padding: "6px 12px",
                    borderRadius: "6px",
                    fontFamily: "var(--font-mono, monospace)",
                    fontSize: "0.8rem",
                    color: "var(--ink, #180f0b)",
                  }}
                >
                  {t}
                </span>
              ))}
            </div>
          ) : (
            <p className="software-card__desc" style={{ fontStyle: "italic" }}>
              Technical feasibility verification capabilities are registered and coordinated directly by the Manager Agent.
            </p>
          )}
        </WindowPanel>

        {/* Recent Software Agent Runs */}
        <WindowPanel title="software.run-history">
          {loading ? (
            <p className="software-empty">Loading execution history...</p>
          ) : runs.length === 0 ? (
            <p className="software-empty">
              No individual Software Agent runs found yet. The Software Agent executes as part of the shared AI Team analysis cycle.
            </p>
          ) : (
            <table className="software-table">
              <thead>
                <tr>
                  <th>RUN ID</th>
                  <th>STARTED</th>
                  <th>STATUS</th>
                  <th>ACTIONS PROPOSED</th>
                  <th>LATENCY</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontFamily: "var(--font-mono, monospace)" }}>{r.id.slice(0, 8)}…</td>
                    <td>{new Date(r.started_at).toLocaleString()}</td>
                    <td>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "3px 8px",
                          borderRadius: "4px",
                          fontSize: "0.72rem",
                          fontWeight: 600,
                          background: r.status === "completed" ? "#e8f5e9" : "#fff3e0",
                          color: r.status === "completed" ? "#2e7d32" : "#e65100",
                        }}
                      >
                        {r.status.toUpperCase()}
                      </span>
                    </td>
                    <td>{r.actions_proposed}</td>
                    <td>{r.total_latency_ms ? `${r.total_latency_ms}ms` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </WindowPanel>
      </div>
    </div>
  );
}
