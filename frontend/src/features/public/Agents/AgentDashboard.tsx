import { useEffect, useState } from "react";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip } from "../../../components/StatusIndicator";
import { fetchAgentDashboard, type AgentDashboardResponse, type AgentDashboardAgent } from "../../../lib/api";
import "./AgentDashboard.css";

const FLOW_ARROW = String.fromCharCode(8594);

interface AgentDashboardProps {
  debateId: string;
  onSelectAgent?: (agent: AgentDashboardAgent) => void;
}

export function AgentDashboard({ debateId, onSelectAgent }: AgentDashboardProps) {
  const [dashboard, setDashboard] = useState<AgentDashboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        const data = await fetchAgentDashboard(debateId);
        if (!cancelled) {
          setDashboard(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load dashboard");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [debateId]);

  if (loading) {
    return (
      <WindowPanel title="agent-dashboard.agent" className="agent-dashboard">
        <div className="dashboard-loading">Loading agent dashboard…</div>
      </WindowPanel>
    );
  }

  if (error) {
    return (
      <WindowPanel title="agent-dashboard.agent" className="agent-dashboard">
        <div className="dashboard-error">Error: {error}</div>
      </WindowPanel>
    );
  }

  if (!dashboard) {
    return (
      <WindowPanel title="agent-dashboard.agent" className="agent-dashboard">
        <div className="dashboard-empty">No dashboard data</div>
      </WindowPanel>
    );
  }

  const { agents, debate_status, rag_context, objective, findings_by_type, final_synthesis, recommendation } = dashboard;

  const getStatusTone = (status: string): "ok" | "accent" | "neutral" => {
    switch (status) {
      case "completed": return "ok";
      case "running":
      case "in_progress": return "accent";
      case "failed": return "neutral"; // StatusChip doesn't have "warn"
      default: return "neutral"; // StatusChip doesn't have "muted"
    }
  };

  const getStatusLabel = (status: string) => {
    switch (status) {
      case "completed":
      case "concluded": return "COMPLETED";
      case "running": return "RUNNING";
      case "in_progress": return "IN PROGRESS";
      case "assigned": return "WORKING";
      case "pending": return "WAITING";
      case "failed": return "FAILED";
      default: return status.toUpperCase();
    }
  };

  return (
    <section className="agent-dashboard-section" aria-labelledby="dashboard-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">AI GROWTH TEAM · DASHBOARD</p>
        <h2 id="dashboard-heading" className="display-lg" style={{ marginTop: 10 }}>
          Agent Analysis Dashboard
        </h2>
        <p className="dashboard-objective" style={{ marginTop: 8, color: "var(--ink-soft)" }}>
          Objective: {objective}
        </p>
        <div className="dashboard-meta">
          <StatusChip tone={debate_status === "concluded" ? "ok" : "accent"} pulse={debate_status === "concluded"}>
            {getStatusLabel(debate_status)}
          </StatusChip>
          <span className="meta-divider">|</span>
          <span className="meta-item">What the team found: {(findings_by_type?.supporting || 0) + (findings_by_type?.opposing || 0) + (findings_by_type?.neutral || 0) + (findings_by_type?.uncertainty || 0)}</span>
          <span className="meta-divider">|</span>
          <span className="meta-item">Evidence supporting this opportunity: {findings_by_type?.supporting || 0}</span>
          <span className="meta-divider">|</span>
          <span className="meta-item">Concerns raised by the team: {findings_by_type?.opposing || 0}</span>
          <span className="meta-divider">|</span>
          <span className="meta-item">Where more evidence is needed: {findings_by_type?.uncertainty || 0}</span>
        </div>
      </div>

      {/* RAG Context Banner */}
      {rag_context && (
        <div className={`rag-context-banner ${rag_context.status === "ready" ? "sufficient" : "insufficient"}`}>
          <div className="rag-status">
            <StatusChip tone={rag_context.status === "ready" ? "ok" : "neutral"}>
              {rag_context.status === "ready" ? "SUFFICIENT DATA" : "INSUFFICIENT DATA"}
            </StatusChip>
            <span>Business data used: {rag_context.status === "ready" ? "Verified" : "Limited"}</span>
            {rag_context.data_sufficiency ? (
              <span>
                ({(rag_context.data_sufficiency as Record<string, number>)?.available ?? 0} / {(rag_context.data_sufficiency as Record<string, number>)?.minimum_required ?? 0} minimum transactions)
              </span>
            ) : null}
          </div>
          <div className="rag-facts">
            {rag_context.verified_facts?.slice(0, 3).map((fact: { fact: string; value: number }, i: number): React.ReactNode => (
              <span key={i} className="fact-chip">{fact.fact}: {fact.value}</span>
            ))}
            {rag_context.verified_facts && rag_context.verified_facts.length > 3 && (
              <span className="fact-chip more">+{rag_context.verified_facts.length - 3} more</span>
            )}
          </div>
        </div>
      )}

      {/* Agent Cards Grid */}
      <div className="agents-grid">
        {agents.map((agent: AgentDashboardAgent) => (
          <AgentCard
            key={agent.specialty}
            agent={agent}
            onClick={() => onSelectAgent?.(agent)}
            isSelected={false}
          />
        ))}
      </div>

      {/* Debate Flow Visualization */}
      <DebateFlowVisualization agents={agents} debateStatus={debate_status} />

      {/* Synthesis & Recommendation */}
      {(final_synthesis || recommendation) && (
        <WindowPanel title="growth-recommendation.app" className="synthesis-panel">
          <div className="synthesis-content">
            {recommendation && (
              <div className="recommendation-box">
                <h4>Growth Manager's Recommendation</h4>
                <p>{recommendation}</p>
              </div>
            )}
            {final_synthesis && (
              <div className="full-synthesis">
                <h4>Full Strategic Synthesis</h4>
                <pre>{final_synthesis}</pre>
              </div>
            )}
          </div>
        </WindowPanel>
      )}
    </section>
  );
}

interface AgentCardProps {
  agent: AgentDashboardAgent;
  onClick?: () => void;
  isSelected?: boolean;
}

function AgentCard({ agent, onClick, isSelected }: AgentCardProps) {
  const tone = agent.status === "completed" ? "ok" : 
               agent.status === "running" || agent.status === "in_progress" ? "accent" :
               agent.status === "failed" ? "neutral" : "neutral";

  const cardStatusLabel = (status: string) => {
    switch (status) {
      case "completed":
      case "concluded": return "COMPLETED";
      case "running": return "RUNNING";
      case "in_progress": return "IN PROGRESS";
      case "assigned": return "WORKING";
      case "pending": return "WAITING";
      case "failed": return "FAILED";
      default: return status.toUpperCase();
    }
  };

  return (
    <div onClick={onClick} style={{ cursor: onClick ? "pointer" : "default" }}>
      <WindowPanel 
        title={`${agent.name.toLowerCase().replace(/\s+/g, '-')}.agent`} 
        className={`agent-dashboard-card ${isSelected ? "selected" : ""}`}
      >
      <div className="agent-card-header">
        <div>
          <StatusChip tone={tone} pulse={tone === "ok"}>
            {cardStatusLabel(agent.status)}
          </StatusChip>
        </div>
        <div className="agent-specialty-badge">{agent.specialty.toUpperCase()}</div>
      </div>
      <h3 className="agent-card-name">{agent.name}</h3>
      <p className="agent-card-desc">{agent.description}</p>
      
      <div className="agent-card-stats">
        <div className="stat">
          <span className="stat-value">{agent.findings_count}</span>
          <span className="stat-label">Findings</span>
        </div>
        <div className="stat supporting">
          <span className="stat-value">{agent.supporting_findings}</span>
          <span className="stat-label">Supporting</span>
        </div>
        <div className="stat opposing">
          <span className="stat-value">{agent.opposing_findings}</span>
          <span className="stat-label">Opposing</span>
        </div>
        <div className="stat uncertainty">
          <span className="stat-value">{agent.uncertainty_findings}</span>
          <span className="stat-label">Uncertain</span>
        </div>
      </div>

      {agent.confidence_avg !== null && (
        <div className="agent-confidence">
          <span className="confidence-label">Avg Confidence:</span>
          <div className="confidence-bar">
            <div 
              className="confidence-fill" 
              style={{ width: `${Math.round(agent.confidence_avg * 100)}%` }}
            ></div>
          </div>
          <span className="confidence-value">{Math.round(agent.confidence_avg * 100)}%</span>
        </div>
      )}

      {agent.evidence_summary?.sources && agent.evidence_summary.sources.length > 0 && (
        <div className="agent-evidence-sources">
          <span className="evidence-label">Evidence Sources:</span>
          <div className="evidence-chips">
            {agent.evidence_summary.sources.slice(0, 4).map((src: string, i: number) => (
              <span key={i} className="evidence-chip">{src}</span>
            ))}
            {agent.evidence_summary.sources.length > 4 && (
              <span className="evidence-chip more">+{agent.evidence_summary.sources.length - 4}</span>
            )}
          </div>
        </div>
      )}

{agent.output_summary && (
          <details className="agent-output-details">
            <summary>View Output Summary</summary>
            <pre className="output-json">{JSON.stringify(agent.output_summary, null, 2)}</pre>
          </details>
        )}
      </WindowPanel>
    </div>
  );
}

function DebateFlowVisualization({ agents, debateStatus }: { agents: AgentDashboardAgent[], debateStatus: string }) {
  const completedAgents = agents.filter(a => a.status === "completed").length;
  const totalAgents = agents.filter(a => a.specialty !== "manager").length;
  const progress = totalAgents > 0 ? (completedAgents / totalAgents) * 100 : 0;

  return (
    <WindowPanel title="investigation-progress.app" className="debate-flow-panel">
      <div className="flow-header">
        <h4>Investigation Progress</h4>
        <div className="flow-progress">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${progress}%` }}></div>
          </div>
          <span className="progress-text">{completedAgents}/{totalAgents} specialists completed</span>
        </div>
      </div>

      <div className="flow-steps">
        <FlowStep 
          label="1. Growth Manager" 
          description="Delegates tasks to specialists" 
          status={debateStatus !== "initiated" ? "completed" : "pending"}
          icon="MGR"
        />
        <div className="flow-arrow">{FLOW_ARROW}</div>
        <FlowStep 
          label="2. Business Experts" 
          description="Parallel independent analysis" 
          status={completedAgents > 0 ? (completedAgents === totalAgents ? "completed" : "running") : "pending"}
          icon="SPEC"
          subSteps={agents.filter(a => a.specialty !== "manager").map(a => ({
            label: a.name.replace("Agent", ""),
            status: a.status === "completed" ? "completed" : a.status === "running" || a.status === "in_progress" ? "running" : "pending",
            findings: a.findings_count,
          }))}
        />
        <div className="flow-arrow">{FLOW_ARROW}</div>
        <FlowStep 
          label="3. Team Discussion" 
          description="Cross-agent challenge & rebuttal" 
          status={debateStatus === "debating" || debateStatus === "synthesizing" || debateStatus === "concluded" ? "completed" : "pending"}
          icon="⚖"
        />
        <div className="flow-arrow">{FLOW_ARROW}</div>
        <FlowStep 
          label="4. Final Recommendation" 
          description="Manager synthesizes final recommendation" 
          status={debateStatus === "synthesizing" || debateStatus === "concluded" ? "completed" : "pending"}
          icon="SYNTH"
        />
      </div>
    </WindowPanel>
  );
}

function FlowStep({ label, description, status, icon, subSteps }: { 
  label: string; 
  description: string; 
  status: "pending" | "running" | "completed";
  icon: string;
  subSteps?: { label: string; status: "pending" | "running" | "completed"; findings: number }[];
}) {
  const statusClass = status === "completed" ? "completed" : status === "running" ? "running" : "pending";
  
  return (
    <div className={`flow-step ${statusClass}`}>
      <div className="step-main">
        <div className="step-icon">{icon}</div>
        <div className="step-content">
          <div className="step-label">{label}</div>
          <div className="step-desc">{description}</div>
        </div>
        <div className={`step-status-indicator ${statusClass}`}></div>
      </div>
      {subSteps && subSteps.length > 0 && (
        <div className="sub-steps">
          {subSteps.map((sub, i) => (
            <div key={i} className={`sub-step ${sub.status}`}>
              <span className="sub-step-dot"></span>
              <span className="sub-step-label">{sub.label}</span>
              <span className="sub-step-findings">{sub.findings} findings</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
