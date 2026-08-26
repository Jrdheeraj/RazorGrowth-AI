import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

// API base URL comes from environment configuration only.
// Empty string ⇒ same-origin requests; override with VITE_API_BASE_URL.
const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

const TERMINAL_STATUSES = ["completed", "failed", "rejected"];

async function api<T = any>(path: string): Promise<T> {
  const res = await fetch(API_BASE + path, { credentials: "include" });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const d = detail?.detail;
    throw new Error(typeof d === "string" ? d : d?.error ? `${d.error}` : "API error " + res.status);
  }
  return res.json();
}

async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const d = detail?.detail;
    throw new Error(typeof d === "string" ? d : d?.error ? `${d.error}` : "API error " + res.status);
  }
  return res.json();
}

function fmtINR(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return "₹" + Math.round(v).toLocaleString("en-IN");
}
function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(1) + "%";
}

type TabId =
  | "radar" | "opportunities" | "agents" | "customers" | "recovery"
  | "campaigns" | "simulator" | "experiments" | "queue" | "memory"
  | "results" | "explain";

const TABS: { id: TabId; label: string }[] = [
  { id: "radar", label: "Growth Radar" },
  { id: "opportunities", label: "Top Opportunities" },
  { id: "agents", label: "Agent Activity" },
  { id: "customers", label: "Customer Intelligence" },
  { id: "recovery", label: "Payment Recovery" },
  { id: "campaigns", label: "Campaigns" },
  { id: "simulator", label: "What-If Simulator" },
  { id: "experiments", label: "Experiments" },
  { id: "queue", label: "Approval Queue" },
  { id: "memory", label: "Growth Memory" },
  { id: "results", label: "Measurement" },
  { id: "explain", label: "Explainability" },
];

interface Signal {
  id: string; signal_type: string; title: string; metric: string;
  current_value: number; comparison_value: number;
  change_percentage?: number | null; confidence: number;
  evidence?: any; detected_at: string;
}
interface RankedOpp {
  rank: number; opportunity_id: string; title: string; type: string;
  status: string; opportunity_score: number; expected_revenue: number;
  confidence: number; score_breakdown: any;
}
interface AgentRunRow {
  id: string; agent_name: string; status: string; mode: string;
  started_at: string; total_latency_ms: number; llm_latency_ms: number;
  db_latency_ms: number; tool_latency_ms: number; errors?: string[] | null;
}
interface Insight {
  customer_id: string; primary_segment: string; order_count: number;
  lifetime_value: number; recency_days?: number | null;
  churn_risk_score: number; churn_risk_level: string; churn_reasons?: string[] | null;
}
interface ExperimentRow {
  id: string; name: string; status: string;
  latest_result?: { statistical_status: string; uplift_percentage?: number | null } | null;
}
interface MemoryRow {
  id: string; memory_type: string; content: string;
  importance: number; outcome_variance_pct?: number | null; created_at: string;
}
interface Action {
  id: string; action_type: string; status: string; created_at: string;
  error_message?: string | null;
}

async function loadAll(setters: Record<string, (d: any) => void>, setError: (e: string | null) => void) {
  const tasks: [string, string][] = [
    ["radar", "/api/radar"],
    ["ranked", "/api/opportunities/ranked"],
    ["runs", "/api/agents/runs?limit=25"],
    ["insights", "/api/customer-insights"],
    ["experiments", "/api/experiments"],
    ["memory", "/api/growth-memory"],
    ["brief", "/api/growth-brief"],
    ["actions", "/api/actions"],
    ["agentsMeta", "/api/agents"],
  ];
  for (const [key, path] of tasks) {
    try {
      setters[key](await api(path));
      setError(null);
    } catch (e) {
      // non-fatal: keep other panels alive
      console.warn("load failed:", path, e);
    }
  }
}

function App() {
  const [tab, setTab] = React.useState<TabId>("radar");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [runningAgents, setRunningAgents] = React.useState(false);

  const [radar, setRadar] = React.useState<{ signals: Signal[] }>({ signals: [] });
  const [ranked, setRanked] = React.useState<{ opportunities: RankedOpp[] }>({ opportunities: [] });
  const [runs, setRuns] = React.useState<{ runs: AgentRunRow[] }>({ runs: [] });
  const [insights, setInsights] = React.useState<{ insights: Insight[] }>({ insights: [] });
  const [exps, setExps] = React.useState<{ experiments: ExperimentRow[] }>({ experiments: [] });
  const [memory, setMemory] = React.useState<{ memories: MemoryRow[] }>({ memories: [] });
  const [brief, setBrief] = React.useState<any>(null);
  const [actions, setActions] = React.useState<{ actions: Action[] }>({ actions: [] });
  const [agentsMeta, setAgentsMeta] = React.useState<any>(null);

  // simulator state
  const [scenarioType, setScenarioType] = React.useState("discount");
  const [simPct, setSimPct] = React.useState(10);
  const [simTargets, setSimTargets] = React.useState(200);
  const [simConv, setSimConv] = React.useState(0.1);
  const [simAov, setSimAov] = React.useState(500);
  const [simResult, setSimResult] = React.useState<any>(null);

  const refresh = React.useCallback(async () => {
    setLoading(true);
    try {
      await loadAll(
        {
          radar: setRadar, ranked: setRanked, runs: setRuns,
          insights: setInsights, experiments: setExps, memory: setMemory,
          brief: setBrief, actions: setActions, agentsMeta: setAgentsMeta,
        },
        setError
      );
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { refresh(); }, [refresh]);

  const runAgents = async (mode: "fast" | "deep") => {
    setRunningAgents(true); setError(null);
    try {
      await apiPost("/api/agents/run", { mode });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunningAgents(false);
    }
  };

  const runSimulation = async () => {
    setSimResult(null); setError(null);
    const payload: any =
      scenarioType === "discount"
        ? { scenario_type: "discount", discount_percentage: simPct, target_customers: simTargets, expected_conversion: simConv, avg_order_value: simAov }
        : { scenario_type: "campaign", target_customers: simTargets, expected_conversion: simConv, avg_order_value: simAov };
    try {
      setSimResult(await apiPost("/api/simulations", payload));
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const act = async (action: Action, verb: "approve" | "reject" | "execute") => {
    setLoading(true); setError(null);
    try {
      await apiPost(`/api/actions/${action.id}/${verb}`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      await refresh();
    } finally {
      setLoading(false);
    }
  };

  const topRisk = brief?.top_risk as { type: string; detail: string } | null | undefined;
  const recoverySignals = radar.signals.filter((s) =>
    s.signal_type.includes("payment")
  );
  const campaignOpps = ranked.opportunities.filter((o) =>
    o.type === "campaign" || o.type === "failed_payment_recovery"
  );
  const queue = actions.actions.filter((a) => !TERMINAL_STATUSES.includes(a.status));

  return (
    <main className="shell">
      <header>
        <div>
          <p className="eyebrow">RAZORGROWTH AI · PHASE 5</p>
          <h1>Agentic Growth Control Center</h1>
          <p className="muted">
            Specialised agents observe, reason, simulate and propose — humans approve.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={() => runAgents("fast")} disabled={runningAgents || loading} className="secondary">
            {runningAgents ? "Running…" : "Run Fast Agents"}
          </button>
          <button onClick={() => runAgents("deep")} disabled={runningAgents || loading} className="primary">
            {runningAgents ? "Running…" : "Run Deep Agents"}
          </button>
          <button onClick={() => refresh()} disabled={loading}>Refresh</button>
          <div className="status">TEST MODE</div>
        </div>
      </header>

      {error && (
        <section className="panel" role="alert"><p className="error">{error}</p></section>
      )}

      {/* Daily brief strip */}
      {brief && (
        <section className="metrics">
          <div>
            <span>Revenue ({brief.window_days}d)</span>
            <strong>{fmtINR(brief.revenue.current_period)}</strong>
            <small>vs prev {pct(brief.revenue.change_percentage)}</small>
          </div>
          <div>
            <span>Top opportunity</span>
            <strong style={{ fontSize: 14 }}>{brief.top_opportunity?.title ?? "—"}</strong>
            <small>{brief.top_opportunity
              ? `confidence ${(100 * brief.top_opportunity.confidence).toFixed(0)}%`
              : "run the agents"}</small>
          </div>
          <div>
            <span>Top risk</span>
            <strong style={{ fontSize: 14 }}>{topRisk?.type ?? "none detected"}</strong>
            <small style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", display: "block" }}>
              {topRisk?.detail ?? "no risk signals"}
            </small>
          </div>
          <div>
            <span>Pending approval</span>
            <strong>{queue.length}</strong>
            <small>human gate active</small>
          </div>
        </section>
      )}

      <nav style={{ display: "flex", flexWrap: "wrap", gap: 6, margin: "16px 0" }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={t.id === tab ? "primary" : "secondary"}
            style={{ opacity: t.id === tab ? 1 : 0.75 }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* ── Growth Radar ─────────────────────────────────────────── */}
      {tab === "radar" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">LIVE SIGNALS</p><h2>Growth Radar</h2></div>
          </div>
          {radar.signals.length === 0 && (
            <p className="muted">No active signals. Run the agents to scan merchant data.</p>
          )}
          {radar.signals.map((s) => (
            <article className="opportunity" key={s.id}>
              <div className="op-header">
                <span className="tag">{s.signal_type.replace(/_/g, " ").toUpperCase()}</span>
                <small>confidence {(s.confidence * 100).toFixed(0)}%</small>
              </div>
              <div className="op-details">
                <h3 style={{ fontSize: 15 }}>{s.title}</h3>
                <p className="muted">{s.metric}: now {fmtINR(s.current_value)} vs prior {fmtINR(s.comparison_value)} ({pct(s.change_percentage ?? undefined)})</p>
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Top Opportunities ───────────────────────────────────── */}
      {tab === "opportunities" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">RANKED BY DETERMINISTIC SCORE</p><h2>Top Opportunities</h2></div>
          </div>
          {ranked.opportunities.length === 0 && (
            <p className="muted">No open opportunities yet.</p>
          )}
          {ranked.opportunities.map((o) => (
            <article className="opportunity" key={o.opportunity_id}>
              <div className="op-header">
                <span className="tag">#{o.rank} · SCORE {o.opportunity_score.toFixed(1)}</span>
                <small>{o.type.replace(/_/g, " ")}</small>
              </div>
              <div className="op-details">
                <h3 style={{ fontSize: 15 }}>{o.title}</h3>
                <p className="muted">
                  Est. impact {fmtINR(o.expected_revenue)} · confidence {(o.confidence * 100).toFixed(0)}%
                  {" · "}urgency {(o.score_breakdown?.urgency_score ?? 0).toFixed(2)}
                  {" · "}cost adj ×{(o.score_breakdown?.implementation_cost_adjustment ?? 1).toFixed(2)}
                </p>
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Agent Activity ──────────────────────────────────────── */}
      {tab === "agents" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">OBSERVABILITY</p><h2>Agent Activity</h2></div>
          </div>
          {agentsMeta?.observability && (
            <p className="muted">
              Runs: {agentsMeta.observability.total_runs} · success {agentsMeta.observability.successful_runs}
              {" · "}failed {agentsMeta.observability.failed_runs}
              {" · "}total latency {agentsMeta.observability.latency?.total_latency_ms ?? 0} ms
              {" · "}LLM {agentsMeta.observability.latency?.llm_latency_ms ?? 0} ms
            </p>
          )}
          {runs.runs.length === 0 && <p className="muted">No agent runs recorded yet.</p>}
          {runs.runs.map((r) => (
            <article className="opportunity" key={r.id}>
              <div className="op-header">
                <span className="tag">{r.agent_name.replace(/Agent$/, "").toUpperCase()}</span>
                <small>{r.mode} · {r.total_latency_ms} ms (llm {r.llm_latency_ms} / db {r.db_latency_ms} / tools {r.tool_latency_ms})</small>
              </div>
              <div className="op-details">
                <p>Status: <strong>{r.status}</strong> · {new Date(r.started_at).toLocaleString()}</p>
                {r.errors?.length ? <p className="error">{r.errors.join("; ")}</p> : null}
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Customer Intelligence ──────────────────────────────── */}
      {tab === "customers" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">CHURN RISK & SEGMENTS</p><h2>Customer Intelligence</h2></div>
          </div>
          {insights.insights.length === 0 && (
            <p className="muted">No insights yet — run Deep Agents to compute customer intelligence.</p>
          )}
          {insights.insights.slice(0, 20).map((i) => (
            <article className="opportunity" key={i.customer_id}>
              <div className="op-header">
                <span className="tag">{i.primary_segment.toUpperCase()}</span>
                <small>churn {Number(i.churn_risk_score).toFixed(0)} ({i.churn_risk_level})</small>
              </div>
              <div className="op-details">
                <p className="muted">
                  orders {i.order_count} · LTV {fmtINR(i.lifetime_value)} · last purchase {i.recency_days ?? "—"} days ago
                </p>
                {i.churn_reasons?.length ? <p className="muted">Why: {i.churn_reasons.join("; ")}</p> : null}
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Payment Recovery ───────────────────────────────────── */}
      {tab === "recovery" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">FAILED PAYMENTS</p><h2>Payment Recovery</h2></div>
          </div>
          {recoverySignals.length === 0 && (
            <p className="muted">No payment-failure signals detected.</p>
          )}
          {recoverySignals.map((s) => (
            <article className="opportunity" key={s.id}>
              <div className="op-header"><span className="tag">{s.signal_type.replace(/_/g, " ").toUpperCase()}</span></div>
              <div className="op-details"><h3 style={{ fontSize: 15 }}>{s.title}</h3></div>
            </article>
          ))}
        </section>
      )}

      {/* ── Campaign Recommendations ───────────────────────────── */}
      {tab === "campaigns" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">STRATEGIST PROPOSALS</p><h2>Campaign Recommendations</h2></div>
          </div>
          {campaignOpps.length === 0 && <p className="muted">No campaign-type opportunities yet.</p>}
          {campaignOpps.map((o) => (
            <article className="opportunity" key={o.opportunity_id}>
              <div className="op-header"><span className="tag">#{o.rank}</span><small>{o.status}</small></div>
              <div className="op-details">
                <h3 style={{ fontSize: 15 }}>{o.title}</h3>
                <p className="muted">Est. {fmtINR(o.expected_revenue)} (estimate)</p>
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── What-If Simulator ─────────────────────────────────── */}
      {tab === "simulator" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">DETERMINISTIC ESTIMATES — NEVER REAL OUTCOMES</p><h2>What-If Simulator</h2></div>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "end" }}>
            <label>Scenario<br />
              <select value={scenarioType} onChange={(e) => setScenarioType(e.target.value)}>
                <option value="discount">Discount</option>
                <option value="campaign">Campaign</option>
              </select>
            </label>
            {scenarioType === "discount" && (
              <label>Discount %<br /><input type="number" min={1} max={100} value={simPct} onChange={(e) => setSimPct(+e.target.value)} /></label>
            )}
            <label>Target customers<br /><input type="number" min={0} value={simTargets} onChange={(e) => setSimTargets(+e.target.value)} /></label>
            <label>Expected conversion<br /><input type="number" step="0.01" min={0} max={1} value={simConv} onChange={(e) => setSimConv(+e.target.value)} /></label>
            <label>Avg order value ₹<br /><input type="number" min={0} value={simAov} onChange={(e) => setSimAov(+e.target.value)} /></label>
            <button className="primary" onClick={runSimulation} disabled={loading}>Simulate</button>
          </div>
          {simResult && (
            <div style={{ marginTop: 16 }}>
              <p><strong>ESTIMATE ONLY:</strong> revenue {fmtINR(simResult.estimated_revenue)}
                {" "}· cost {fmtINR(simResult.estimated_cost)}
                {" "}· profit {fmtINR(simResult.estimated_profit)}</p>
              <p className="muted">Confidence range: {fmtINR(simResult.confidence_low)} – {fmtINR(simResult.confidence_high)}</p>
              <ul className="muted">{(simResult.assumptions ?? []).map((a: string, i: number) => <li key={i}>{a}</li>)}</ul>
            </div>
          )}
        </section>
      )}

      {/* ── Experiments ───────────────────────────────────────── */}
      {tab === "experiments" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">HONEST STATISTICS ONLY</p><h2>Experiments</h2></div>
          </div>
          {exps.experiments.length === 0 && <p className="muted">No experiments proposed yet.</p>}
          {exps.experiments.map((e) => (
            <article className="opportunity" key={e.id}>
              <div className="op-header"><span className="tag">{e.status.toUpperCase()}</span></div>
              <div className="op-details">
                <h3 style={{ fontSize: 15 }}>{e.name}</h3>
                <p className="muted">
                  {e.latest_result
                    ? `${e.latest_result.statistical_status}${e.latest_result.uplift_percentage != null ? ` · uplift ${pct(e.latest_result.uplift_percentage)}` : ""}`
                    : "no results yet"}
                </p>
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Approval Queue ────────────────────────────────────── */}
      {tab === "queue" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">HUMAN GATE — AGENTS CANNOT PASS THIS</p><h2>Action Approval Queue</h2></div>
          </div>
          {queue.length === 0 && <p className="muted">Nothing awaiting review.</p>}
          {queue.map((a) => (
            <article className="opportunity" key={a.id}>
              <div className="op-header">
                <span className="tag">{a.action_type.replace(/_/g, " ").toUpperCase()}</span>
                <small>{a.created_at ? new Date(a.created_at).toLocaleString() : ""}</small>
              </div>
              <div className="op-details">
                <p>Status: <strong>{a.status}</strong></p>
                {a.error_message && <p className="error">{a.error_message}</p>}
              </div>
              <div className="op-actions">
                {a.status === "requested" && (<>
                  <button className="primary" onClick={() => act(a, "approve")} disabled={loading}>Approve</button>{" "}
                  <button className="secondary" onClick={() => act(a, "reject")} disabled={loading}>Reject</button>
                </>)}
                {a.status === "approved" && (
                  <button className="primary" onClick={() => act(a, "execute")} disabled={loading}>Execute</button>
                )}
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Growth Memory ─────────────────────────────────────── */}
      {tab === "memory" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">WHAT THE SYSTEM REMEMBERS</p><h2>Growth Memory</h2></div>
          </div>
          {memory.memories.length === 0 && <p className="muted">Memory is empty.</p>}
          {memory.memories.map((m) => (
            <article className="opportunity" key={m.id}>
              <div className="op-header"><span className="tag">{m.memory_type.replace(/_/g, " ").toUpperCase()}</span>
                <small>importance {(m.importance * 100).toFixed(0)}%</small></div>
              <div className="op-details">
                <p>{m.content}</p>
                {m.outcome_variance_pct !== null && m.outcome_variance_pct !== undefined && (
                  <p className="muted">Measured variance vs expectation: {pct(m.outcome_variance_pct)}</p>
                )}
              </div>
            </article>
          ))}
        </section>
      )}

      {/* ── Measurement / Results ─────────────────────────────── */}
      {tab === "results" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">REAL NUMBERS ONLY — PENDING STAYS PENDING</p><h2>Measurement & Results</h2></div>
          </div>
          {agentsMeta?.observability && (
            <>
              <p>Measured campaign revenue (actual): <strong>{fmtINR(agentsMeta.observability.measured_revenue_total)}</strong></p>
              <p className="muted">Actions approved to date: {agentsMeta.observability.actions_approved} · rejected: {agentsMeta.observability.actions_rejected}</p>
            </>
          )}
        </section>
      )}

      {/* ── Explainability ────────────────────────────────────── */}
      {tab === "explain" && (
        <section className="panel">
          <div className="panelHead">
            <div><p className="eyebrow">WHY THIS RECOMMENDATION?</p><h2>Explainability</h2></div>
          </div>
          {ranked.opportunities.length === 0 && <p className="muted">Rank an opportunity first.</p>}
          {ranked.opportunities.slice(0, 3).map((o) => (
            <article className="opportunity" key={o.opportunity_id}>
              <div className="op-header"><span className="tag">#{o.rank} {o.title}</span></div>
              <div className="op-details">
                <p><strong>WHY:</strong> score {o.opportunity_score.toFixed(1)} from transparent factors:</p>
                <ul className="muted">
                  <li>Revenue potential: {(o.score_breakdown?.revenue_potential ?? 0).toFixed(2)}</li>
                  <li>Confidence: {(o.score_breakdown?.confidence_score ?? 0).toFixed(2)}</li>
                  <li>Urgency: {(o.score_breakdown?.urgency_score ?? 0).toFixed(2)}</li>
                  <li>Evidence strength: {(o.score_breakdown?.evidence_strength ?? 0).toFixed(2)}</li>
                  <li>Risk (reported separately): {(o.score_breakdown?.risk_score ?? 0).toFixed(2)}</li>
                </ul>
                <p className="muted">{o.score_breakdown?.formula}</p>
                <details>
                  <summary className="muted">DO NOTHING vs TAKE ACTION</summary>
                  <p className="muted">
                    Do-nothing baseline and take-action estimates are available via
                    GET /api/opportunities/ranked + explainability service; simulated values are always labelled estimates.
                  </p>
                </details>
              </div>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
