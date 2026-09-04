import { useEffect, useState } from "react";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip } from "../../../components/StatusIndicator";
import { fetchAgentDashboard, type AgentDashboardResponse, type AgentDashboardAgent } from "../../../lib/api";
import { AgentDashboard } from "./AgentDashboard";
import "./AgentDebateDashboard.css";

interface DebateListItem {
  id: string;
  objective: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export function AgentDebateDashboard() {
  const [debates, setDebates] = useState<DebateListItem[]>([]);
  const [selectedDebateId, setSelectedDebateId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadDebates() {
      try {
        setLoading(true);
        const token = localStorage.getItem("access_token");
        const res = await fetch("/api/agent-debates", {
          credentials: "same-origin",
          headers: {
            "Authorization": `Bearer ${token || ""}`
          }
        });
        if (!res.ok) {
          if (res.status === 401) {
            if (!cancelled) {
              setDebates([]);
              setError(null);
            }
            return;
          }
          throw new Error("Failed to fetch debates");
        }
        const data = await res.json();
        if (!cancelled) {
          setDebates(data.debates || []);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load debates");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadDebates();
    return () => { cancelled = true; };
  }, []);

  const handleSelectDebate = (debateId: string) => {
    setSelectedDebateId(debateId);
  };

  if (loading) {
    return (
      <section id="agent-debate" className="shell section" aria-labelledby="agent-debate-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">AI GROWTH TEAM · DEBATE DASHBOARD</p>
          <h2 id="agent-debate-heading" className="display-lg" style={{ marginTop: 10 }}>
            Agent Debate Dashboard
          </h2>
        </div>
        <div className="readable">
          <WindowPanel title="agent-debate.agent" className="agent-debate-loading">
            <div className="dashboard-loading">Loading debates…</div>
          </WindowPanel>
        </div>
      </section>
    );
  }

  return (
    <section id="agent-debate" className="shell section" aria-labelledby="agent-debate-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">AI GROWTH TEAM · INVESTIGATIONS</p>
        <h2 id="agent-debate-heading" className="display-lg" style={{ marginTop: 10 }}>
          AI Investigations
        </h2>
        <p className="page-subtitle" style={{ marginTop: 8 }}>
          Review your AI Growth Team's investigations — structured multi-agent analysis
          grounded in real business data with evidence, debate, and synthesis.
        </p>
      </div>

      <div className="debate-dashboard-layout">
        {/* Debate List Sidebar */}
        <aside className="debate-sidebar">
          <WindowPanel title="debate-list.agent" className="sidebar-panel">
            <div className="sidebar-header">
              <h3>Recent Debates</h3>
            </div>

            {debates.length === 0 && (
              <div className="sidebar-empty">
                <div className="empty-icon">⚖️</div>
                <h4>No Investigations Yet</h4>
                <p>Start your first AI Growth Investigation to see your team in action.</p>
              </div>
            )}

            <ul className="debate-list">
              {debates.map((debate) => (
                <li 
                  key={debate.id} 
                  className={`debate-list-item ${selectedDebateId === debate.id ? "selected" : ""}`}
                  onClick={() => handleSelectDebate(debate.id)}
                >
                  <div className="debate-item-header">
                    <span className="debate-objective">{debate.objective}</span>
                    <StatusChip 
                      tone={debate.status === "concluded" ? "ok" : debate.status === "debating" || debate.status === "synthesizing" ? "accent" : "neutral"}
                    >
                      {debate.status.toUpperCase()}
                    </StatusChip>
                  </div>
                  <div className="debate-item-meta">
                    <span>Created: {new Date(debate.created_at).toLocaleDateString()}</span>
                    <span>Updated: {new Date(debate.updated_at).toLocaleDateString()}</span>
                  </div>
                </li>
              ))}
            </ul>
          </WindowPanel>
        </aside>

        {/* Dashboard Content */}
        <main className="debate-main">
          {selectedDebateId ? (
            <AgentDashboard debateId={selectedDebateId} />
          ) : (
            <WindowPanel title="welcome.agent" className="welcome-panel">
              <div className="welcome-content">
                <div className="welcome-icon">DEBATE</div>
                <h3>Select an Investigation</h3>
                <p>Choose an investigation from the sidebar to review:</p>
                <ul>
                  <li>Participating agents and their analysis status</li>
                  <li>Findings with evidence sources and confidence scores</li>
                  <li>Data coverage and evidence quality</li>
                  <li>Debate flow and how agents reached their conclusions</li>
                  <li>Growth Manager synthesis and recommendation</li>
                </ul>
                <div className="welcome-hint">
                  <kbd>Go to AI Team</kbd> to start a new investigation
                </div>
              </div>
            </WindowPanel>
          )}
        </main>
      </div>
    </section>
  );
}