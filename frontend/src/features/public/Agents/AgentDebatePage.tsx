/**
 * AgentDebatePage — full debate detail view.
 *
 * Shows:
 *  - Sidebar list of all debates (from /api/agent-debates)
 *  - Selected debate: AgentDashboard + evidence viewer + messages + rounds
 *  - Explicit INSUFFICIENT EVIDENCE state when data is absent
 *  - Real provenance: every finding links back to its source evidence
 *  - No invented findings — all data comes from the backend API
 *  - Auto-selects debate from ?id= URL param (set by AI Team investigation flow)
 */
import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip } from "../../../components/StatusIndicator";
import {
  fetchAgentDashboard,
  fetchDebateList,
  fetchDebateFindings,
  fetchDebateMessages,
  fetchDebateRoundStatus,
} from "../../../lib/api";
import type {
  AgentDashboardResponse,
  AgentDebateListItem,
  AgentFinding,
  AgentMessage,
  AgentDebateRoundStatus,
} from "../../../types/api";
import { AgentDashboard } from "./AgentDashboard";
import "./AgentDebate.css";

const ROUND_LABELS: Record<number, { name: string; desc: string }> = {
  1: { name: "Round 1: Independent Analysis",  desc: "Each specialist agent analyses data independently — no cross-agent communication." },
  2: { name: "Round 2: Cross-Agent Debate",     desc: "Specialists challenge each other's findings and propose alternatives." },
  3: { name: "Round 3: Rebuttals & Refinements", desc: "Agents respond to challenges and refine their positions." },
  4: { name: "Synthesis",                        desc: "Manager agent synthesises all evidence into a final recommendation." },
};

function debateStatusTone(status: string): "ok" | "accent" | "neutral" {
  if (status === "concluded")                            return "ok";
  if (status === "debating" || status === "synthesizing") return "accent";
  return "neutral";
}

/* ─────────────────────────────────────────────────────────────────────────── */

export function AgentDebatePage() {
  const [searchParams] = useSearchParams();
  const urlDebateId = searchParams.get("id");

  const [debates, setDebates]         = useState<AgentDebateListItem[]>([]);
  const [selectedId, setSelectedId]   = useState<string | null>(urlDebateId);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError]     = useState<string | null>(null);

  /* Load debate list ─────────────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoadingList(true);
        const data = await fetchDebateList();
        if (!cancelled) {
          const list = data.debates ?? [];
          setDebates(list);
          setListError(null);
          // If a URL param id was given but is not in the list yet, keep it selected anyway
          // (the detail panel will fetch it directly)
          if (!selectedId && list.length > 0) {
            setSelectedId(list[0].id);
          }
        }
      } catch (e) {
        if (!cancelled)
          setListError(e instanceof Error ? e.message : "Failed to load debates");
      } finally {
        if (!cancelled) setLoadingList(false);
      }
    })();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When URL param changes (e.g. a new investigation just completed), select that debate
  useEffect(() => {
    if (urlDebateId) setSelectedId(urlDebateId);
  }, [urlDebateId]);

  return (
    <section id="agent-debate" className="shell section agent-debate-page" aria-labelledby="debate-heading">
      <div className="page-hero">
        <p className="meta-label">YOUR BUSINESS · AI INVESTIGATIONS</p>
        <h2 id="debate-heading" className="display-lg" style={{ marginTop: 10 }}>
          AI Investigations
        </h2>
        <p className="page-subtitle" style={{ marginTop: 8 }}>
          Your AI Growth Team has investigated your business and produced evidence-backed findings.
          All conclusions are grounded in real data — no invented numbers.
        </p>
      </div>

      <div className="debate-layout">
        {/* Sidebar */}
        <aside className="debate-sidebar">
          <WindowPanel title="debate-list.agent" className="sidebar-panel">
            <div className="sidebar-header">
              <h3>Recent Debates</h3>
              {loadingList && <span className="loading-indicator">Loading…</span>}
            </div>

            {listError && <div className="sidebar-error">Error: {listError}</div>}

            {!loadingList && !listError && debates.length === 0 && (
              <div className="sidebar-empty">
                No investigations found yet. Visit the AI Team page to start your first analysis.
              </div>
            )}

            <ul className="debate-list">
              {debates.map((d) => (
                <li
                  key={d.id}
                  className={`debate-list-item${selectedId === d.id ? " selected" : ""}`}
                  onClick={() => setSelectedId(d.id)}
                >
                  <div className="debate-item-header">
                    <span className="debate-objective">{d.objective}</span>
                    <StatusChip tone={debateStatusTone(d.status)}>
                      {d.status.toUpperCase()}
                    </StatusChip>
                  </div>
                  <div className="debate-item-meta">
                    <span>Created {new Date(d.created_at).toLocaleDateString()}</span>
                    <span>Updated {new Date(d.updated_at).toLocaleDateString()}</span>
                  </div>
                </li>
              ))}
            </ul>
          </WindowPanel>
        </aside>

        {/* Main content */}
        <main className="debate-main">
          {selectedId ? (
            <DebateDetail debateId={selectedId} />
          ) : (
            <WindowPanel title="welcome.agent" className="welcome-panel">
              <div className="welcome-content">
                <span className="welcome-icon">DEBATE</span>
                <h3>Select an Investigation</h3>
                <p>Choose an investigation from the sidebar to review:</p>
                <ul>
                  <li>Which agents participated and what they found</li>
                  <li>Evidence sources, confidence scores, and data quality</li>
                  <li>How agents challenged each other's findings</li>
                  <li>The Growth Manager's final synthesis</li>
                  <li>What to do when evidence is insufficient</li>
                </ul>
                <div className="welcome-hint">
                  <kbd>AI Team</kbd> → Start AI Investigation to create one
                </div>
              </div>
            </WindowPanel>
          )}
        </main>
      </div>
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────────────── */

interface DebateDetailProps {
  debateId: string;
}

function DebateDetail({ debateId }: DebateDetailProps) {
  const [dashboard,  setDashboard]  = useState<AgentDashboardResponse | null>(null);
  const [findings,   setFindings]   = useState<AgentFinding[]>([]);
  const [messages,   setMessages]   = useState<AgentMessage[]>([]);
  const [rounds,     setRounds]     = useState<AgentDebateRoundStatus | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState<string | null>(null);
  const [activeTab,  setActiveTab]  = useState<"overview" | "evidence" | "messages" | "rounds">("overview");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [dash, finds, msgs, rds] = await Promise.all([
        fetchAgentDashboard(debateId),
        fetchDebateFindings(debateId).catch(() => ({ findings: [] as AgentFinding[] })),
        fetchDebateMessages(debateId).catch(() => ({ messages: [] as AgentMessage[] })),
        fetchDebateRoundStatus(debateId).catch(() => null),
      ]);
      setDashboard(dash);
      setFindings(finds.findings ?? []);
      setMessages(msgs.messages ?? []);
      setRounds(rds);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load debate");
    } finally {
      setLoading(false);
    }
  }, [debateId]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <WindowPanel title="debate-detail.agent">
        <div className="dashboard-loading">Loading debate data…</div>
      </WindowPanel>
    );
  }

  if (error || !dashboard) {
    return (
      <WindowPanel title="debate-detail.agent">
        <div className="dashboard-error">{error ?? "No data available"}</div>
      </WindowPanel>
    );
  }

  const hasInsufficientData =
    dashboard.rag_context &&
    dashboard.rag_context.status !== "ready" &&
    !dashboard.rag_context.inference_allowed;

  return (
    <div className="debate-detail">
      {/* Insufficient-evidence banner — shown prominently, never hidden */}
      {hasInsufficientData && (
        <div className="insufficient-banner">
          <span className="insufficient-icon">!</span>
          <div className="insufficient-content">
            <h4>More Data Needed</h4>
            <p>
              Your business doesn't have enough transaction history yet for reliable AI analysis.
              Your agents have recorded what they found, but have flagged that more data is needed
              before they can make a confident recommendation.
            </p>
          </div>
        </div>
      )}

      {/* Synthesis / recommendation — only if concluded with real data */}
      {dashboard.debate_status === "concluded" && dashboard.recommendation && (
        <div className="synthesis-block">
          <span className="synthesis-label">Growth Manager's Recommendation</span>
          <p className="synthesis-text">{dashboard.recommendation}</p>
        </div>
      )}

      {/* Tab strip */}
      <DebateTabStrip active={activeTab} onChange={setActiveTab}
        findingsCount={findings.length}
        messagesCount={messages.length}
        roundsCount={rounds?.current_round ?? 1}
      />

      {/* Tab content */}
      {activeTab === "overview" && (
        <AgentDashboard debateId={debateId} />
      )}

      {activeTab === "evidence" && (
        <EvidenceViewer findings={findings} />
      )}

      {activeTab === "messages" && (
        <MessagesViewer messages={messages} />
      )}

      {activeTab === "rounds" && rounds && (
        <RoundsViewer rounds={rounds} />
      )}

      {/* Workflow footer — connects debate to next stage */}
      {dashboard.debate_status === "concluded" && dashboard.recommendation && (
        <div style={{
          marginTop: 24,
          paddingTop: 20,
          borderTop: "1px solid var(--line-soft)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}>
          <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)" }}>
            Investigation concluded. The Growth Manager has produced a recommendation.
          </p>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <a
              href="/agents"
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                textTransform: "uppercase",
                letterSpacing: "var(--tracking-meta)",
                padding: "8px 14px",
                border: "1px solid var(--line-soft)",
                borderRadius: "var(--radius-control)",
                background: "var(--paper-deep)",
                color: "var(--ink-soft)",
                textDecoration: "none",
              }}
            >
              ← AI Team
            </a>
            <span style={{
              fontFamily: "var(--font-mono)",
              fontSize: "var(--text-meta)",
              textTransform: "uppercase",
              letterSpacing: "var(--tracking-meta)",
              padding: "8px 14px",
              border: "1px dashed var(--line-soft)",
              borderRadius: "var(--radius-control)",
              color: "var(--ink-faint)",
            }}>
              Simulation & Approval → coming next
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Tab strip ───────────────────────────────────────────────────────────── */

interface TabStripProps {
  active: "overview" | "evidence" | "messages" | "rounds";
  onChange: (t: "overview" | "evidence" | "messages" | "rounds") => void;
  findingsCount: number;
  messagesCount: number;
  roundsCount: number;
}

function DebateTabStrip({ active, onChange, findingsCount, messagesCount, roundsCount }: TabStripProps) {
  const tabs: Array<{ key: typeof active; label: string; count?: number }> = [
    { key: "overview",  label: "Overview" },
    { key: "evidence",  label: "Evidence",  count: findingsCount },
    { key: "messages",  label: "Messages",  count: messagesCount },
    { key: "rounds",    label: "Rounds",    count: roundsCount },
  ];

  return (
    <nav className="debate-tabs" aria-label="Debate sections">
      {tabs.map((t) => (
        <button
          key={t.key}
          className={`debate-tab${active === t.key ? " active" : ""}`}
          onClick={() => onChange(t.key)}
          type="button"
        >
          {t.label}
          {t.count !== undefined && t.count > 0 && (
            <span className="tab-count">{t.count}</span>
          )}
        </button>
      ))}
    </nav>
  );
}

/* ── Evidence viewer ─────────────────────────────────────────────────────── */

function EvidenceViewer({ findings }: { findings: AgentFinding[] }) {
  if (findings.length === 0) {
    return (
      <WindowPanel title="evidence.agent" className="evidence-panel">
        <div className="messages-empty">
          No findings recorded yet — agents have not analysed this objective.
        </div>
      </WindowPanel>
    );
  }

  const supporting  = findings.filter(f => f.finding_type === "supporting");
  const opposing    = findings.filter(f => f.finding_type === "opposing");
  const uncertainty = findings.filter(f => f.finding_type === "uncertainty");
  const neutral     = findings.filter(f => f.finding_type === "neutral");

  return (
    <WindowPanel title="evidence.agent" className="evidence-panel">
      {/* Summary row */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <EvidenceStat label="Supporting"  count={supporting.length}  tone="supporting" />
        <EvidenceStat label="Opposing"    count={opposing.length}    tone="opposing" />
        <EvidenceStat label="Uncertainty" count={uncertainty.length} tone="uncertainty" />
        <EvidenceStat label="Neutral"     count={neutral.length}     tone="neutral" />
      </div>

      <div className="evidence-grid">
        {[...supporting, ...opposing, ...uncertainty, ...neutral].map((f) => (
          <FindingCard key={f.id} finding={f} />
        ))}
      </div>
    </WindowPanel>
  );
}

function EvidenceStat({ label, count, tone }: { label: string; count: number; tone: string }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      gap: 2, padding: "10px 16px",
      background: "var(--paper-deep)",
      border: "1px solid var(--line-soft)",
      borderRadius: "var(--radius-window)",
      minWidth: 80,
    }}>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-display-md)",
        fontWeight: 700,
        lineHeight: 1,
        color: tone === "supporting" ? "var(--green-deep)"
             : tone === "opposing"   ? "var(--coral-strong)"
             : tone === "uncertainty" ? "var(--coral)"
             : "var(--ink-soft)",
      }}>{count}</span>
      <span style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-meta)",
        textTransform: "uppercase",
        letterSpacing: "var(--tracking-meta)",
        color: "var(--ink-faint)",
      }}>{label}</span>
    </div>
  );
}

function FindingCard({ finding }: { finding: AgentFinding }) {
  const evidenceSources: string[] = [];
  if (Array.isArray(finding.evidence)) {
    finding.evidence.forEach((e) => {
      if (typeof e === "object" && e !== null) {
        const src = (e as Record<string, unknown>).source ?? (e as Record<string, unknown>).type;
        if (typeof src === "string") evidenceSources.push(src);
      }
    });
  }

  return (
    <div className={`evidence-item ${finding.finding_type}`}>
      <div className="evidence-item-header">
        <span className="evidence-agent">{finding.agent_specialty}</span>
        <span className={`evidence-type-badge ${finding.finding_type}`}>
          {finding.finding_type}
        </span>
        <span className="evidence-confidence">
          {Math.round(finding.confidence * 100)}% confidence
        </span>
      </div>

      <div className="evidence-title">{finding.title}</div>

      {finding.description && (
        <div className="evidence-description">{finding.description}</div>
      )}

      {finding.uncertainty_notes && (
        <div style={{
          marginTop: 6, padding: "8px 12px",
          background: "var(--coral-wash)",
          border: "1px solid var(--coral)",
          borderRadius: "var(--radius-control)",
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-meta)",
          color: "var(--coral-strong)",
        }}>
          ⚠ {finding.uncertainty_notes}
        </div>
      )}

      {evidenceSources.length > 0 && (
        <div className="evidence-sources-row">
          {evidenceSources.map((src, i) => (
            <span key={i} className="evidence-source-chip">{src}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Messages viewer ─────────────────────────────────────────────────────── */

const AGENT_SHORT: Record<string, string> = {
  manager: "Growth Manager",
  marketing: "Marketing Analyst",
  product: "Product Strategist",
  designer: "Creative & UX Advisor",
  software: "Technical Feasibility",
};

function agentLabel(raw: string) {
  return AGENT_SHORT[raw?.toLowerCase()] ?? raw;
}

function getRound(msg: AgentMessage): number {
  if (Array.isArray(msg.references)) {
    const first = msg.references[0] as Record<string, unknown> | undefined;
    if (first && typeof first.round === "number") return first.round;
  }
  return 0;
}

const ROUND_BADGE_LABELS: Record<number, string> = {
  1: "R1 — Investigation",
  2: "R2 — Challenge",
  3: "R3 — Rebuttal",
  4: "R4 — Synthesis",
};

function MessagesViewer({ messages }: { messages: AgentMessage[] }) {
  if (messages.length === 0) {
    return (
      <WindowPanel title="messages.agent" className="messages-panel">
        <div className="messages-empty">
          No messages yet — agents have not exchanged debate messages.
        </div>
      </WindowPanel>
    );
  }

  // Group by round
  const byRound = new Map<number, AgentMessage[]>();
  for (const m of messages) {
    const r = getRound(m);
    if (!byRound.has(r)) byRound.set(r, []);
    byRound.get(r)!.push(m);
  }
  const rounds = Array.from(byRound.keys()).sort((a, b) => a - b);

  return (
    <WindowPanel title="messages.agent" className="messages-panel">
      <div className="messages-list">
        {rounds.map((r) => (
          <div key={r}>
            {r > 0 && (
              <div style={{
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                textTransform: "uppercase",
                letterSpacing: "var(--tracking-meta)",
                color: "var(--ink-faint)",
                padding: "10px 0 6px",
                borderBottom: "1px solid var(--line-soft)",
                marginBottom: 10,
              }}>
                {ROUND_BADGE_LABELS[r] ?? `Round ${r}`}
              </div>
            )}
            {byRound.get(r)!.map((m) => (
              <div key={m.id} className="message-item">
                <div className="message-header">
                  <span className="message-from">{agentLabel(m.from_agent)}</span>
                  {m.to_agent && (
                    <>
                      <span className="message-arrow">→</span>
                      <span className="message-to">{agentLabel(m.to_agent)}</span>
                    </>
                  )}
                  <span className={`message-type-badge ${m.message_type.toLowerCase()}`}>
                    {m.message_type}
                  </span>
                </div>
                <div className="message-content">{m.content}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </WindowPanel>
  );
}

/* ── Rounds viewer ───────────────────────────────────────────────────────── */

function RoundsViewer({ rounds }: { rounds: AgentDebateRoundStatus }) {
  const current = rounds.current_round ?? 1;

  return (
    <WindowPanel title="rounds.agent" className="rounds-panel">
      <div className="rounds-timeline">
        {([1, 2, 3, 4] as const).map((n) => {
          const meta = ROUND_LABELS[n] ?? { name: `Round ${n}`, desc: "" };
          const isCompleted = n < current;
          const isActive    = n === current;
          const className   = isCompleted ? "round-row completed"
                            : isActive    ? "round-row active"
                            :               "round-row pending";

          // Messages for this round
          const roundMsgs = rounds.rounds?.[n] ?? [];

          return (
            <div key={n} className={className}>
              <span className="round-badge">R{n}</span>
              <div className="round-info">
                <div className="round-name">{meta.name}</div>
                <div className="round-desc">{meta.desc}</div>
                {roundMsgs.length > 0 && (
                  <div style={{ marginTop: 8, fontSize: "var(--text-small)", color: "var(--ink-soft)" }}>
                    {roundMsgs.length} message{roundMsgs.length !== 1 ? "s" : ""} exchanged
                  </div>
                )}
                {/* Agent positions for this round */}
                {rounds.findings_summary?.by_agent && n === 1 && (
                  <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {Object.entries(rounds.findings_summary.by_agent).map(([agent, count]) => (
                      <span key={agent} style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "var(--text-meta)",
                        padding: "2px 8px",
                        background: "var(--paper-bright)",
                        border: "1px solid var(--line-soft)",
                        borderRadius: "var(--radius-control)",
                        color: "var(--ink-soft)",
                      }}>
                        {agent}: {String(count)} findings
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <span className="round-indicator" />
            </div>
          );
        })}
      </div>
    </WindowPanel>
  );
}
