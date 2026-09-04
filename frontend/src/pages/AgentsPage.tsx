/**
 * /agents — AI Growth Team Workspace.
 *
 * Real agentic operations workspace where all 13 AI specialists analyze the merchant's
 * real Razorpay TEST data, coordinate findings, and produce a prioritized Business Action Plan.
 *
 * AI Team stays on this page during execution. Agent Debate remains a separate, optional experience.
 */
import { useEffect, useState, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fetchAgentsMeta, startAiTeamWork, fetchAgentRuns } from "../lib/api";
import type {
  AgentsListResponse,
  OrchestratorRunResponse,
  AgentRunRecord,
  ActionPlan,
} from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import { StatusChip } from "../components/StatusIndicator";

interface AgentProfile {
  label: string;
  specialty: string;
  looksAt: string;
  focus: string;
  category: "core" | "specialist" | "leadership";
  tone: "ok" | "accent" | "neutral";
}

const AGENT_PROFILES: Record<string, AgentProfile> = {
  ManagerAgent: {
    label: "Growth Manager",
    specialty: "Growth Strategy & Team Coordination",
    looksAt: "Business health signals, specialist outputs, and opportunity rankings",
    focus: "Coordinates the AI team, resolves conflicting findings, and locks the final action plan.",
    category: "leadership",
    tone: "ok",
  },
  MarketingAgent: {
    label: "Marketing Analyst",
    specialty: "Customer Retention & Campaign Strategy",
    looksAt: "Customer segments, repeat purchases, and failed checkout transactions",
    focus: "Finds ways to improve customer retention, re-activate buyers, and launch high-ROI campaigns.",
    category: "core",
    tone: "accent",
  },
  ProductAgent: {
    label: "Product Strategist",
    specialty: "Catalog Merchandising & Basket Economics",
    looksAt: "Active product catalog, average order value (AOV), and basket affinities",
    focus: "Uncovers upsell, cross-sell, and product bundle opportunities to increase transaction size.",
    category: "core",
    tone: "accent",
  },
  DesignerAgent: {
    label: "Creative & UX Advisor",
    specialty: "Checkout Experience & Messaging Concepts",
    looksAt: "Payment retry flows, checkout drop-offs, and trust signals",
    focus: "Recommends frictionless checkout adjustments, clear decline messaging, and trust badging.",
    category: "core",
    tone: "accent",
  },
  SoftwareAgent: {
    label: "Technical Feasibility",
    specialty: "Architecture & Automation Engineering",
    looksAt: "Razorpay webhooks, APIs, catalog scale, and integration constraints",
    focus: "Evaluates whether business recommendations can realistically and safely be automated.",
    category: "core",
    tone: "accent",
  },
  GrowthDiscoveryAgent: {
    label: "Opportunity Discovery",
    specialty: "Continuous Growth Signal Detection",
    looksAt: "Transaction telemetry, payment volume shifts, and baseline trends",
    focus: "Scans your live commerce data for emerging revenue and retention signals.",
    category: "specialist",
    tone: "ok",
  },
  CustomerIntelligenceAgent: {
    label: "Customer Intelligence",
    specialty: "Customer Lifecycle & Churn Risk",
    looksAt: "Customer order recency, frequency, monetary value, and payment history",
    focus: "Scores customer health and detects churn risks before shoppers drop off.",
    category: "specialist",
    tone: "ok",
  },
  RevenueOptimizationAgent: {
    label: "Revenue Optimisation",
    specialty: "Pricing & Margin Maximization",
    looksAt: "Order basket distributions, pricing tiers, and margin thresholds",
    focus: "Models discounting rules and bundling strategies to lift overall revenue.",
    category: "specialist",
    tone: "ok",
  },
  CampaignStrategistAgent: {
    label: "Campaign Strategist",
    specialty: "Targeted Audience Campaigns",
    looksAt: "Audience cohorts and predicted conversion rates",
    focus: "Plans targeted campaign scenarios with explicit revenue impact projections.",
    category: "specialist",
    tone: "ok",
  },
  PaymentRecoveryAgent: {
    label: "Payment Recovery",
    specialty: "Failed Payment Recapture",
    looksAt: "Unsuccessful Razorpay payments, failure error codes, and retry timings",
    focus: "Identifies recoverable revenue from failed checkouts and sets automated retry strategies.",
    category: "specialist",
    tone: "ok",
  },
  ExperimentAgent: {
    label: "Experiment Designer",
    specialty: "A/B Testing & Validation",
    looksAt: "Conversion rate baselines, sample sizes, and control groups",
    focus: "Designs controlled experiments so every recommendation can be verified before full rollout.",
    category: "specialist",
    tone: "ok",
  },
  OpportunityPrioritizationAgent: {
    label: "Priority Ranking",
    specialty: "Impact vs. Effort Scoring",
    looksAt: "Discovered opportunities, estimated revenue, and operational effort",
    focus: "Compares and ranks all growth ideas to highlight what to execute first.",
    category: "specialist",
    tone: "neutral",
  },
  GrowthMemoryAgent: {
    label: "Growth Memory",
    specialty: "Knowledge & Historical Continuity",
    looksAt: "Prior investigations, approved actions, and outcome metrics",
    focus: "Retains context across analyses so your AI team improves decisions over time.",
    category: "specialist",
    tone: "neutral",
  },
};

const EXECUTION_PHASES: Record<string, string> = {
  GrowthMemoryAgent: "Growth Memory is reviewing historical context...",
  GrowthDiscoveryAgent: "Opportunity Discovery is analyzing your business...",
  CustomerIntelligenceAgent: "Customer Intelligence is reviewing your customers...",
  RevenueOptimizationAgent: "Revenue Optimisation is looking for ways to increase revenue...",
  PaymentRecoveryAgent: "Payment Recovery is checking unsuccessful payments...",
  MarketingAgent: "Marketing Analyst is identifying customer and campaign opportunities...",
  ProductAgent: "Product Strategist is reviewing products and order patterns...",
  CampaignStrategistAgent: "Campaign Strategist is planning potential campaigns...",
  DesignerAgent: "Creative & UX Advisor is working on customer experience improvements...",
  ExperimentAgent: "Experiment Designer is planning how recommendations can be tested...",
  OpportunityPrioritizationAgent: "Priority Ranking is comparing the opportunities...",
  SoftwareAgent: "Technical Feasibility is checking what can realistically be implemented...",
  ManagerAgent: "Growth Manager is reviewing the team's work...",
};

export function AgentsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlObjective = searchParams.get("objective");

  const [agents, setAgents] = useState<AgentsListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [objective, setObjective] = useState(
    urlObjective || "Comprehensive commerce analysis and growth optimization"
  );
  const [isWorking, setIsWorking] = useState(false);
  const [currentPhaseText, setCurrentPhaseText] = useState("");
  const [workError, setWorkError] = useState<string | null>(null);
  const [lastRunResult, setLastRunResult] = useState<OrchestratorRunResponse | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRunRecord[]>([]);
  const [activeTab, setActiveTab] = useState<"team" | "plan" | "activity">("team");

  const pollIntervalRef = useRef<number | null>(null);
  const autoStartedRef = useRef(false);

  // Load registered agents
  useEffect(() => {
    fetchAgentsMeta()
      .then(setAgents)
      .catch((e) => {
        const msg = e instanceof Error ? e.message : "Failed to load";
        setError(msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403") ? "no_workspace" : msg);
      });
  }, []);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  // Auto-start if navigated with objective from Growth Radar
  useEffect(() => {
    if (urlObjective && agents && !autoStartedRef.current && !isWorking) {
      autoStartedRef.current = true;
      handleStartAiWork(urlObjective);
    }
  }, [urlObjective, agents]);

  const handleStartAiWork = async (targetObjective?: string) => {
    const obj = targetObjective || objective;
    setIsWorking(true);
    setWorkError(null);
    setCurrentPhaseText("Starting your business analysis...");
    setActiveTab("team");

    try {
      // 1. Kick off real 13-agent AI Team execution on live data
      const runPromise = startAiTeamWork(obj, { windowDays: 30 });

      // 2. Poll real agent runs from backend for live state
      let activeRunId: string | null = null;
      const pollTimer = window.setInterval(async () => {
        try {
          const runsResp = await fetchAgentRuns(20, activeRunId || undefined);
          if (runsResp.runs && runsResp.runs.length > 0) {
            setAgentRuns(runsResp.runs);
            const latest = runsResp.runs[0];
            if (latest && EXECUTION_PHASES[latest.agent_name]) {
              setCurrentPhaseText(EXECUTION_PHASES[latest.agent_name]);
            }
          }
        } catch {
          // ignore transient poll error
        }
      }, 1500);
      pollIntervalRef.current = pollTimer;

      const res = await runPromise;
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

      activeRunId = res.orchestrator_run_id;
      setLastRunResult(res);
      setIsWorking(false);
      setCurrentPhaseText("Your business action plan is ready.");
      setActiveTab("plan");

      // Refresh final run records
      try {
        const finalRuns = await fetchAgentRuns(25, res.orchestrator_run_id);
        setAgentRuns(finalRuns.runs || []);
      } catch {
        // non-fatal
      }
    } catch (e) {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      setWorkError(e instanceof Error ? e.message : "AI Team execution failed");
      setIsWorking(false);
      setCurrentPhaseText("");
    }
  };

  if (error === "no_workspace") {
    return (
      <section className="shell section" aria-labelledby="agents-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">AI GROWTH TEAM</p>
          <h1 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>Meet the AI Growth Team</h1>
        </div>
        <WindowPanel title="workspace-required.app">
          <p style={{ color: "var(--ink-soft)" }}>
            Connect your business workspace to unlock your AI Growth Team.
          </p>
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" mono onClick={() => navigate("/profile")}>View Profile →</Button>
          </div>
        </WindowPanel>
      </section>
    );
  }

  // Map agent name to latest result output
  const agentOutputMap = new Map<string, any>();
  if (lastRunResult?.agents) {
    for (const a of lastRunResult.agents) {
      agentOutputMap.set(a.agent, a);
    }
  }

  // All registered agents from backend or fallback to known 13
  const allAgentNames = agents?.agents?.map((a) => a.name) || Object.keys(AGENT_PROFILES);

  const leadershipAgents = allAgentNames.filter((n) => AGENT_PROFILES[n]?.category === "leadership");
  const coreAgents = allAgentNames.filter((n) => AGENT_PROFILES[n]?.category === "core");
  const specialistAgents = allAgentNames.filter((n) => AGENT_PROFILES[n]?.category === "specialist");

  const actionPlan: ActionPlan | null = lastRunResult?.action_plan || null;

  return (
    <section className="shell section" aria-labelledby="agents-heading">
      {/* Header */}
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">YOUR BUSINESS · AI WORKFORCE</p>
        <h1 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>
          AI Growth Team Workspace
        </h1>
        <p style={{ color: "var(--ink-soft)", maxWidth: "68ch", marginTop: 10 }}>
          Your autonomous team of 13 AI business specialists works directly on your live Razorpay TEST commerce data —
          detecting opportunities, auditing payment drops, modeling basket expansion, and locking concrete action plans.
        </p>
      </div>

      {/* Control Banner */}
      <div
        style={{
          margin: "24px 0 28px",
          padding: "20px 24px",
          background: "var(--paper-deep)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-window)",
          boxShadow: "var(--shadow-float-card)",
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
          <div>
            <p style={{ fontWeight: 700, fontSize: "var(--text-body)", color: "var(--ink)" }}>
              Run Live Business Analysis
            </p>
            <p style={{ color: "var(--ink-soft)", fontSize: "var(--text-small)", marginTop: 2 }}>
              Coordinates all 13 specialists on your real payment and order records to generate your business action plan.
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <Button
              variant="primary"
              mono
              disabled={isWorking || !agents}
              onClick={() => handleStartAiWork()}
            >
              {isWorking ? "Team is Working…" : "Start AI Team Work →"}
            </Button>
          </div>
        </div>

        {/* Live Execution State */}
        {isWorking && (
          <div
            style={{
              padding: "14px 18px",
              background: "rgba(112,184,138,0.12)",
              border: "1px solid var(--green)",
              borderRadius: "var(--radius-window)",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}
          >
            <StatusChip tone="accent" pulse>
              WORKING
            </StatusChip>
            <p style={{ color: "var(--ink)", fontSize: "var(--text-small)", fontWeight: 600 }}>
              {currentPhaseText || "Understanding your business data..."}
            </p>
          </div>
        )}

        {/* Completion Announcement */}
        {!isWorking && lastRunResult && (
          <div
            style={{
              padding: "14px 18px",
              background: "rgba(112,184,138,0.15)",
              border: "1px solid var(--green)",
              borderRadius: "var(--radius-window)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 12,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <StatusChip tone="ok">ACTION PLAN READY</StatusChip>
              <span style={{ fontSize: "var(--text-small)", color: "var(--ink)" }}>
                Analysis completed across all 13 specialists.{" "}
                <strong>{lastRunResult.totals?.opportunities_created ?? 0} opportunities</strong> and{" "}
                <strong>{lastRunResult.totals?.actions_proposed ?? 0} actions proposed</strong>.
              </span>
            </div>
            <Button variant="secondary" mono onClick={() => setActiveTab("plan")}>
              View Action Plan ↓
            </Button>
          </div>
        )}

        {workError && (
          <div
            style={{
              padding: "12px 16px",
              background: "var(--coral-wash)",
              border: "1px solid var(--coral)",
              borderRadius: "var(--radius-window)",
              color: "var(--coral-strong)",
              fontSize: "var(--text-small)",
            }}
          >
            {workError}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 24, borderBottom: "1px solid var(--line-soft)", paddingBottom: 8 }}>
        <TabButton
          active={activeTab === "team"}
          onClick={() => setActiveTab("team")}
          label="AI Specialist Team"
          count={allAgentNames.length}
        />
        <TabButton
          active={activeTab === "plan"}
          onClick={() => setActiveTab("plan")}
          label="Business Action Plan"
          badge={actionPlan ? "Ready" : undefined}
        />
        <TabButton
          active={activeTab === "activity"}
          onClick={() => setActiveTab("activity")}
          label="Execution Activity"
          count={agentRuns.length}
        />
      </div>

      {/* TAB 1: Business Action Plan */}
      {activeTab === "plan" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24, marginBottom: 36 }}>
          {actionPlan ? (
            <WindowPanel title="business-action-plan.app" tone="choc" dark>
              <div style={{ padding: "8px 0" }}>
                <p className="meta-label" style={{ marginBottom: 8, color: "var(--cream-muted)" }}>
                  GROWTH MANAGER · BUSINESS ACTION PLAN
                </p>
                <h2 style={{ fontSize: "var(--text-title)", color: "var(--cream)", marginBottom: 12 }}>
                  Executive Growth Strategy
                </h2>
                <p style={{ color: "var(--cream-muted)", fontSize: "var(--text-body)", lineHeight: 1.6, marginBottom: 24, maxWidth: "75ch" }}>
                  {actionPlan.executive_summary}
                </p>

                <p className="meta-label" style={{ marginBottom: 14, color: "var(--cream-muted)" }}>
                  PRIORITIZED BUSINESS INITIATIVES
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  {actionPlan.initiatives?.map((item, idx) => (
                    <div
                      key={idx}
                      style={{
                        padding: "16px 20px",
                        background: "rgba(247, 235, 215, 0.06)",
                        border: "1px solid rgba(247, 235, 215, 0.15)",
                        borderRadius: "var(--radius-window)",
                        display: "flex",
                        flexDirection: "column",
                        gap: 8,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                        <h3 style={{ fontSize: "var(--text-body)", fontWeight: 700, color: "var(--cream)", margin: 0 }}>
                          {idx + 1}. {item.title}
                        </h3>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <span
                            style={{
                              fontFamily: "var(--font-mono)",
                              fontSize: "var(--text-meta)",
                              padding: "2px 8px",
                              borderRadius: 4,
                              background: item.priority === "HIGH" ? "var(--coral)" : "var(--green-deep)",
                              color: "#fff",
                              fontWeight: 700,
                            }}
                          >
                            {item.priority} PRIORITY
                          </span>
                        </div>
                      </div>

                      <p style={{ fontSize: "var(--text-small)", color: "var(--cream-muted)", margin: 0 }}>
                        <strong>Assigned Specialists:</strong> {item.assigned_to}
                      </p>
                      <p style={{ fontSize: "var(--text-small)", color: "var(--green)", margin: 0 }}>
                        <strong>Expected Impact:</strong> {item.expected_impact}
                      </p>
                      <p style={{ fontSize: "var(--text-small)", color: "var(--cream-muted)", margin: 0, lineHeight: 1.5 }}>
                        <strong>Recommended Next Step:</strong> {item.next_steps}
                      </p>
                    </div>
                  ))}
                </div>

                {/* Navigation actions */}
                <div style={{ marginTop: 24, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
                  <Button variant="primary" mono onClick={() => navigate("/actions")}>
                    Review Proposed Actions in Action Center →
                  </Button>
                  <Button variant="secondary" mono onClick={() => navigate("/debate")}>
                    Review Team Discussion in Agent Debate →
                  </Button>
                </div>
              </div>
            </WindowPanel>
          ) : (
            <WindowPanel title="action-plan.app">
              <div style={{ padding: "20px 0", textAlign: "center" }}>
                <p style={{ color: "var(--ink-soft)", fontSize: "var(--text-body)" }}>
                  No action plan generated yet. Click <strong>"Start AI Team Work"</strong> above to analyze your business data.
                </p>
              </div>
            </WindowPanel>
          )}
        </div>
      )}

      {/* TAB 2: AI Specialist Team Cards */}
      {activeTab === "team" && (
        <>
          {/* Leadership */}
          {leadershipAgents.length > 0 && (
            <div style={{ marginBottom: 32 }}>
              <p className="meta-label" style={{ marginBottom: 14 }}>
                GROWTH LEADERSHIP &amp; COORDINATION
              </p>
              <div style={{ display: "grid", gap: 16, gridTemplateColumns: "1fr" }}>
                {leadershipAgents.map((name) => (
                  <AgentCard
                    key={name}
                    agentName={name}
                    isWorking={isWorking}
                    agentOutput={agentOutputMap.get(name)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Core Growth Team */}
          {coreAgents.length > 0 && (
            <div style={{ marginBottom: 32 }}>
              <p className="meta-label" style={{ marginBottom: 14 }}>
                CORE GROWTH SPECIALISTS
              </p>
              <div
                style={{
                  display: "grid",
                  gap: 16,
                  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                }}
              >
                {coreAgents.map((name) => (
                  <AgentCard
                    key={name}
                    agentName={name}
                    isWorking={isWorking}
                    agentOutput={agentOutputMap.get(name)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Specialists */}
          {specialistAgents.length > 0 && (
            <div style={{ marginBottom: 32 }}>
              <p className="meta-label" style={{ marginBottom: 14 }}>
                DOMAIN &amp; ANALYTICS SPECIALISTS
              </p>
              <div
                style={{
                  display: "grid",
                  gap: 16,
                  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
                }}
              >
                {specialistAgents.map((name) => (
                  <AgentCard
                    key={name}
                    agentName={name}
                    isWorking={isWorking}
                    agentOutput={agentOutputMap.get(name)}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* TAB 3: Execution Activity */}
      {activeTab === "activity" && (
        <div style={{ marginBottom: 36 }}>
          <WindowPanel title="team-activity.app">
            <div style={{ padding: "8px 0" }}>
              <p className="meta-label" style={{ marginBottom: 14 }}>
                RECENT AGENT EXECUTIONS (TENANT-SCOPED)
              </p>
              {agentRuns.length === 0 ? (
                <p style={{ color: "var(--ink-soft)" }}>
                  No agent runs recorded yet. Start AI Team work above to view execution logs.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {agentRuns.map((r) => {
                    const profile = AGENT_PROFILES[r.agent_name];
                    return (
                      <div
                        key={r.id}
                        style={{
                          padding: "12px 16px",
                          border: "1px solid var(--line-soft)",
                          borderRadius: "var(--radius-window)",
                          background: "var(--paper-deep)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          flexWrap: "wrap",
                          gap: 12,
                        }}
                      >
                        <div>
                          <p style={{ fontWeight: 700, fontSize: "var(--text-small)", color: "var(--ink)", margin: 0 }}>
                            {profile?.label ?? r.agent_name}
                          </p>
                          <p style={{ fontSize: "var(--text-meta)", color: "var(--ink-soft)", margin: "2px 0 0" }}>
                            Mode: {r.mode} · Latency: {r.total_latency_ms}ms · Opportunities: {r.opportunities_created} · Actions: {r.actions_proposed}
                          </p>
                        </div>
                        <StatusChip tone={r.status === "completed" ? "ok" : r.status === "running" ? "accent" : "neutral"}>
                          {r.status === "completed" ? "COMPLETED" : r.status.toUpperCase()}
                        </StatusChip>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </WindowPanel>
        </div>
      )}

      {/* Optional Contextual Link to Agent Debate */}
      <div
        style={{
          marginTop: 36,
          padding: "20px 24px",
          background: "var(--paper-deep)",
          border: "1px solid var(--line-soft)",
          borderRadius: "var(--radius-window)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 16,
        }}
      >
        <div>
          <p style={{ fontWeight: 700, fontSize: "var(--text-body)", color: "var(--ink)", margin: 0 }}>
            Want to see how the specialists debate conclusions?
          </p>
          <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)", margin: "4px 0 0" }}>
            The Agent Debate workspace lets specialists cross-examine each other's assumptions and challenge recommendations.
          </p>
        </div>
        <Button variant="secondary" mono onClick={() => navigate("/debate")}>
          Review Team Discussion in Agent Debate →
        </Button>
      </div>

      {/* Workflow Navigation Footer */}
      <div
        style={{
          marginTop: 24,
          paddingTop: 20,
          borderTop: "1px solid var(--line-soft)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <Button variant="ghost-dark" mono onClick={() => navigate("/growth-radar")}>
          ← Growth Radar
        </Button>
        <Button variant="primary" mono onClick={() => navigate("/actions")}>
          View Actions Center →
        </Button>
      </div>
    </section>
  );
}

/* ── Agent Card Component ────────────────────────────────────────────────── */

interface AgentCardProps {
  agentName: string;
  isWorking: boolean;
  agentOutput?: {
    status: string;
    opportunities_created: number;
    actions_proposed: number;
    latency_ms?: { total: number };
    output?: {
      summary?: string;
      recommendations?: string[];
      [key: string]: unknown;
    };
  };
}

function AgentCard({ agentName, isWorking, agentOutput }: AgentCardProps) {
  const [showDetails, setShowDetails] = useState(false);
  const profile = AGENT_PROFILES[agentName] || {
    label: agentName,
    specialty: "Specialist Consultant",
    looksAt: "Commerce records",
    focus: "Analyzes business telemetry.",
    category: "specialist",
    tone: "neutral",
  };

  const isCompleted = agentOutput && agentOutput.status === "completed";
  const outputSummary = agentOutput?.output?.summary;
  const outputRecommendations = agentOutput?.output?.recommendations;

  let statusTone: "ok" | "accent" | "neutral" = "neutral";
  let statusText = "Waiting";

  if (isWorking) {
    statusTone = "accent";
    statusText = "Working";
  } else if (isCompleted) {
    statusTone = "ok";
    statusText = "Completed";
  }

  return (
    <WindowPanel title={`${profile.label.toLowerCase().replace(/\s+/g, "-")}.app`}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
          <div>
            <h3
              style={{
                fontSize: "var(--text-title)",
                fontWeight: 700,
                color: "var(--ink)",
                margin: 0,
                lineHeight: 1.2,
              }}
            >
              {profile.label}
            </h3>
            <p style={{ fontSize: "var(--text-meta)", color: "var(--ink-soft)", margin: "4px 0 0" }}>
              {profile.specialty}
            </p>
          </div>
          <StatusChip tone={statusTone} pulse={statusTone === "accent"}>
            {statusText.toUpperCase()}
          </StatusChip>
        </div>

        {/* What it looks at & Focus */}
        <div style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: "var(--text-small)" }}>
          <p style={{ margin: 0, color: "var(--ink-soft)", lineHeight: 1.5 }}>
            <strong style={{ color: "var(--ink)" }}>Looks at:</strong> {profile.looksAt}
          </p>
          <p style={{ margin: 0, color: "var(--ink-soft)", lineHeight: 1.5 }}>
            <strong style={{ color: "var(--ink)" }}>Focus:</strong> {profile.focus}
          </p>
        </div>

        {/* Real Discovered Result (shown after real execution) */}
        {isCompleted && (
          <div
            style={{
              marginTop: 4,
              padding: "10px 14px",
              background: "var(--paper-deep)",
              border: "1px solid var(--line-soft)",
              borderRadius: "var(--radius-window)",
              borderLeft: "3px solid var(--green)",
            }}
          >
            <p className="meta-label" style={{ marginBottom: 4 }}>
              WHAT IT DISCOVERED
            </p>
            <p style={{ fontSize: "var(--text-small)", color: "var(--ink)", margin: 0, lineHeight: 1.5 }}>
              {outputSummary || "Analyzed real Razorpay transactions and verified growth opportunities."}
            </p>

            {outputRecommendations && outputRecommendations.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <p className="meta-label" style={{ marginBottom: 4 }}>
                  RECOMMENDED WORK
                </p>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: "var(--text-small)", color: "var(--ink-soft)" }}>
                  {outputRecommendations.map((rec, i) => (
                    <li key={i} style={{ marginBottom: 2 }}>{rec}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Technical Details Toggle */}
        <div style={{ marginTop: 2, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          {agentOutput?.latency_ms?.total ? (
            <span style={{ fontSize: "var(--text-meta)", color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>
              Latency: {agentOutput.latency_ms.total}ms
            </span>
          ) : <span />}
          <button
            type="button"
            onClick={() => setShowDetails(!showDetails)}
            style={{
              background: "none",
              border: "none",
              fontSize: "var(--text-meta)",
              color: "var(--ink-soft)",
              cursor: "pointer",
              padding: 0,
              textDecoration: "underline",
            }}
          >
            {showDetails ? "Hide details" : "View details"}
          </button>
        </div>

        {showDetails && (
          <div
            style={{
              padding: "8px 12px",
              background: "var(--paper-deep)",
              borderRadius: "var(--radius-window)",
              fontSize: "var(--text-meta)",
              fontFamily: "var(--font-mono)",
              color: "var(--ink-soft)",
            }}
          >
            <p style={{ margin: "0 0 4px" }}>Agent ID: {agentName}</p>
            <p style={{ margin: "0 0 4px" }}>Status: {agentOutput?.status ?? "ready"}</p>
            <p style={{ margin: 0 }}>
              Opportunities: {agentOutput?.opportunities_created ?? 0} · Actions: {agentOutput?.actions_proposed ?? 0}
            </p>
          </div>
        )}
      </div>
    </WindowPanel>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  badge?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: "8px 16px",
        background: active ? "var(--paper-deep)" : "transparent",
        border: active ? "1px solid var(--line)" : "1px solid transparent",
        borderRadius: "var(--radius-window)",
        color: active ? "var(--ink)" : "var(--ink-soft)",
        fontWeight: active ? 700 : 500,
        fontSize: "var(--text-small)",
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        gap: 8,
        transition: "all 0.15s ease",
      }}
    >
      <span>{label}</span>
      {count !== undefined && (
        <span
          style={{
            fontSize: "var(--text-meta)",
            padding: "1px 6px",
            background: active ? "var(--line)" : "rgba(0,0,0,0.06)",
            borderRadius: 10,
          }}
        >
          {count}
        </span>
      )}
      {badge && (
        <span
          style={{
            fontSize: "var(--text-meta)",
            padding: "1px 6px",
            background: "var(--green-deep)",
            color: "#fff",
            borderRadius: 10,
            fontWeight: 700,
          }}
        >
          {badge}
        </span>
      )}
    </button>
  );
}
