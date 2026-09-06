import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  fetchAgentsMeta,
  fetchAgentRuns,
  fetchGrowthRadar,
  fetchRankedOpportunities,
  startAiTeamWork,
} from "../lib/api";
import type {
  ActionPlan,
  ActionPlanItem,
  AgentRunRow,
  AgentsListResponse,
  GrowthRadarResponse,
  OrchestratorRunResponse,
  OrchestrationAgentOutput,
  RankedOpportunity,
} from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import { StatusChip } from "../components/StatusIndicator";
import "./AgentsPage.css";

const DEFAULT_OBJECTIVE = "Comprehensive commerce analysis and growth optimization";

interface AgentProfile {
  label: string;
  specialty: string;
  looksAt: string;
  focus: string;
}

const AGENT_PROFILES: Record<string, AgentProfile> = {
  ManagerAgent: {
    label: "Growth Manager",
    specialty: "Growth strategy & coordination",
    looksAt: "Business health, specialist findings, and opportunity rankings",
    focus: "Coordinates the team, resolves disagreements, and locks the final recommendation.",
  },
  MarketingAgent: {
    label: "Marketing Analyst",
    specialty: "Customer retention & campaigns",
    looksAt: "Customer segments, repeat purchases, and failed checkout transactions",
    focus: "Finds ways to retain customers, win back buyers, and run high-return campaigns.",
  },
  ProductAgent: {
    label: "Product Strategist",
    specialty: "Catalog & basket economics",
    looksAt: "Product catalog, average order value, and items bought together",
    focus: "Uncovers upsell, cross-sell, and bundle opportunities to increase order size.",
  },
  DesignerAgent: {
    label: "Creative & UX Advisor",
    specialty: "Checkout experience & messaging",
    looksAt: "Payment retry flows, checkout drop-offs, and trust signals",
    focus: "Recommends smoother checkout steps and clearer decline messaging.",
  },
  SoftwareAgent: {
    label: "Technical Feasibility",
    specialty: "Automation & integrations",
    looksAt: "Razorpay webhooks, APIs, catalog scale, and integration constraints",
    focus: "Checks whether each recommendation can realistically and safely be automated.",
  },
  GrowthDiscoveryAgent: {
    label: "Opportunity Discovery",
    specialty: "Growth signal detection",
    looksAt: "Payment volume shifts, transaction outcomes, and baseline trends",
    focus: "Scans live commerce data for emerging revenue and retention signals.",
  },
  CustomerIntelligenceAgent: {
    label: "Customer Intelligence",
    specialty: "Customer lifecycle & churn risk",
    looksAt: "Customer order recency, frequency, spend, and payment history",
    focus: "Spots at-risk customers and high-value buyers before patterns are obvious.",
  },
  RevenueOptimizationAgent: {
    label: "Revenue Optimisation",
    specialty: "Pricing & margin maximization",
    looksAt: "Order basket distributions, pricing tiers, and margin thresholds",
    focus: "Models discount rules and bundling strategies that lift total revenue.",
  },
  CampaignStrategistAgent: {
    label: "Campaign Strategist",
    specialty: "Targeted audience campaigns",
    looksAt: "Audience cohorts and predicted conversion rates",
    focus: "Plans targeted campaigns with explicit revenue impact projections.",
  },
  PaymentRecoveryAgent: {
    label: "Payment Recovery",
    specialty: "Failed payment recapture",
    looksAt: "Unsuccessful Razorpay payments, failure error codes, and retry timings",
    focus: "Identifies recoverable revenue from failed checkouts and sets retry strategies.",
  },
  ExperimentAgent: {
    label: "Experiment Designer",
    specialty: "A/B testing & validation",
    looksAt: "Conversion rate baselines, sample sizes, and control groups",
    focus: "Designs controlled tests so recommendations are verified before rollout.",
  },
  OpportunityPrioritizationAgent: {
    label: "Priority Ranking",
    specialty: "Impact vs. effort scoring",
    looksAt: "Discovered opportunities, estimated revenue, and operational effort",
    focus: "Compares and ranks all growth ideas to decide what to execute first.",
  },
  GrowthMemoryAgent: {
    label: "Growth Memory",
    specialty: "Knowledge & historical continuity",
    looksAt: "Prior investigations, approved actions, and outcome metrics",
    focus: "Retains context across analyses so decisions improve over time.",
  },
};

const AGENT_ORDER: string[] = [
  "GrowthMemoryAgent",
  "GrowthDiscoveryAgent",
  "CustomerIntelligenceAgent",
  "RevenueOptimizationAgent",
  "PaymentRecoveryAgent",
  "MarketingAgent",
  "ProductAgent",
  "CampaignStrategistAgent",
  "DesignerAgent",
  "ExperimentAgent",
  "OpportunityPrioritizationAgent",
  "SoftwareAgent",
  "ManagerAgent",
];

const LIVE_TASKS: Record<string, string> = {
  ManagerAgent: "Team strategy, specialist coordination, and the final recommendation",
  MarketingAgent: "Failed payments + customer purchase history",
  ProductAgent: "Products, order values, and items bought together",
  DesignerAgent: "Checkout experience and payment retry messaging",
  SoftwareAgent: "Automation paths and technical constraints",
  GrowthDiscoveryAgent: "Live commerce data for emerging growth signals",
  CustomerIntelligenceAgent: "Customer purchase behavior and repeat patterns",
  RevenueOptimizationAgent: "Pricing, basket value, and margin opportunities",
  CampaignStrategistAgent: "Customer cohorts for targeted campaigns",
  PaymentRecoveryAgent: "Failed transactions and recoverable revenue",
  ExperimentAgent: "How each recommendation can be safely tested",
  OpportunityPrioritizationAgent: "All discovered opportunities, ranked by impact",
  GrowthMemoryAgent: "Historical context from past analyses",
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

const OPPORTUNITY_TYPES: Record<string, string> = {
  payment_recovery: "Some customers tried to pay but their payments failed — this revenue can be won back.",
  customer_winback: "Past customers have not purchased in a while and could be invited back.",
  cross_sell: "Customers who buy certain products tend to buy related ones together.",
  upsell: "Some orders could be expanded with a higher-value option or add-on.",
  bundle: "Frequently bought together products can be offered as a discounted bundle.",
  repeat_purchase: "Repeat buyers show patterns that can be encouraged across more customers.",
  campaign: "A targeted campaign could lift sales for a specific customer group.",
};

interface AgentUiStatus {
  label: string;
  tone: "ok" | "accent" | "neutral";
  marker: "" | "--working" | "--found" | "--done";
}

function prettifyName(raw: string) {
  return raw
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\s*Agent\s*$/i, "")
    .trim();
}

function agentProfile(name: string): AgentProfile {
  return (
    AGENT_PROFILES[name] ?? {
      label: prettifyName(name),
      specialty: "Business analysis",
      looksAt: "Your live commerce records",
      focus: "Analyzes your business data for growth opportunities.",
    }
  );
}

function firstSentence(text: string | null | undefined): string | null {
  if (!text) return null;
  const match = text.trim().match(/^(.+?[.!?])(\s|$)/);
  return match?.[1] ?? text.trim();
}

function sentences(text: string | null | undefined, count: number): string | null {
  if (!text) return null;
  return text
    .split(/(?<=[.!?])\s+/)
    .filter(Boolean)
    .slice(0, count)
    .join(" ");
}

function formatMoney(value: number | null | undefined): string | null {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function confidenceWord(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  if (value >= 0.75) return "High";
  if (value >= 0.45) return "Medium";
  return "Low";
}

function timeAgo(ts: number | null) {
  if (!ts) return "Not yet run";
  const seconds = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (seconds < 45) return "Just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

interface OpportunityView {
  title: string;
  why: string;
  evidence: string | null;
  impact: string | null;
  action: string | null;
  discoveredBy: string[];
  confidence: string | null;
}

function translateOpportunityType(type: string | undefined) {
  if (!type) return "This opportunity was identified from patterns in your live business data.";
  const key = type.toLowerCase().replace(/[^a-z]/g, "_");
  return (
    OPPORTUNITY_TYPES[key] ??
    OPPORTUNITY_TYPES[type.toLowerCase()] ??
    `${prettifyName(type)}: identified by the AI team from your live business data.`
  );
}

function findInitiative(plan: ActionPlan | null, title: string): ActionPlanItem | null {
  if (!plan?.initiatives?.length) return null;
  const needle = title.toLowerCase();
  const exact = plan.initiatives.find((item) => item.title.toLowerCase() === needle);
  if (exact) return exact;
  const partial = plan.initiatives.find(
    (item) =>
      item.title.toLowerCase().includes(needle) || needle.includes(item.title.toLowerCase()),
  );
  return partial ?? null;
}

function liveNotesFor(
  name: string,
  output: OrchestrationAgentOutput | undefined,
  radar: GrowthRadarResponse | null,
): string[] {
  const notes: string[] = [];
  const recs = output?.output?.recommendations;
  if (recs?.length) notes.push(firstSentence(recs[0]) || recs[0]);
  if (output?.output?.summary) {
    const head = firstSentence(output.output.summary) ?? "";
    const rest = output.output.summary.replace(head, "").trim();
    const second = firstSentence(rest);
    if (second && !notes.includes(second)) notes.push(second);
  }

  const m = radar?.metrics;
  const failed = m?.failed_payments ?? 0;
  const failedValue = m && failed > 0 ? failed * (m.average_order_value || 0) : 0;

  if (name === "PaymentRecoveryAgent" && failed > 0) {
    notes.push(`${failed} failed payment${failed === 1 ? "" : "s"} detected after checkout was attempted`);
    if (failedValue > 0)
      notes.push(`Estimated recoverable revenue: ${formatMoney(failedValue) ?? "a small amount"}`);
  }
  if (name === "MarketingAgent" && failedValue > 0) {
    notes.push(`Found ${formatMoney(failedValue) ?? "a small amount"} in failed payments`);
  }
  if (name === "CustomerIntelligenceAgent" && m) {
    if (m.total_customers > 0) notes.push(`Found ${m.total_customers} customers`);
    if (m.repeat_customers > 0)
      notes.push(`Identified ${m.repeat_customers} repeat buyer${m.repeat_customers === 1 ? "" : "s"}`);
  }
  if (name === "GrowthDiscoveryAgent" && radar && radar.signals.length > 0) {
    notes.push(`Detected ${radar.signals.length} growth signal${radar.signals.length === 1 ? "" : "s"} in recent activity`);
  }

  return notes.slice(0, 3);
}

export function AgentsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlObjective = searchParams.get("objective");

  const [agentsMeta, setAgentsMeta] = useState<AgentsListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [radar, setRadar] = useState<GrowthRadarResponse | null>(null);
  const [ranked, setRanked] = useState<RankedOpportunity[]>([]);
  const [isWorking, setIsWorking] = useState(false);
  const [currentPhaseText, setCurrentPhaseText] = useState("");
  const [workError, setWorkError] = useState<string | null>(null);
  const [lastRunResult, setLastRunResult] = useState<OrchestratorRunResponse | null>(null);
  const [liveRuns, setLiveRuns] = useState<AgentRunRow[]>([]);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [lastAnalysisTime, setLastAnalysisTime] = useState<number | null>(null);

  const pollIntervalRef = useRef<number | null>(null);
  const autoStartedRef = useRef(false);

  useEffect(() => {
    fetchAgentsMeta()
      .then(setAgentsMeta)
      .catch((e) => {
        const msg = e instanceof Error ? e.message : "Failed to load";
        setError(
          msg.includes("NOT_AUTHENTICATED") || msg.includes("TOKEN_EXPIRED") || msg.includes("401")
            ? "login_required"
            : msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403")
              ? "no_workspace"
              : msg,
        );
      });
    fetchGrowthRadar(30)
      .then((r) => setRadar(r))
      .catch(() => undefined);
    fetchRankedOpportunities()
      .then((r) => setRanked(r.opportunities ?? []))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  useEffect(() => {
    if (urlObjective && agentsMeta && !autoStartedRef.current && !isWorking) {
      autoStartedRef.current = true;
      handleStartAiWork(urlObjective);
    }
  }, [urlObjective, agentsMeta]);

  const handleStartAiWork = async (targetObjective?: string) => {
    const obj = targetObjective || urlObjective || DEFAULT_OBJECTIVE;
    if (isWorking) return;
    setIsWorking(true);
    setWorkError(null);
    setCurrentPhaseText("Starting your business analysis...");

    try {
      const runPromise = startAiTeamWork(obj, { windowDays: 30 });

      let activeRunId: string | null = null;
      const pollTimer = window.setInterval(async () => {
        try {
          const runsResp = await fetchAgentRuns(20, activeRunId || undefined);
          if (runsResp.runs && runsResp.runs.length > 0) {
            setLiveRuns(runsResp.runs);
            const latest = runsResp.runs[0];
            if (latest && EXECUTION_PHASES[latest.agent_name]) {
              setCurrentPhaseText(EXECUTION_PHASES[latest.agent_name]);
            }
          }
        } catch {
          // transient poll error — keep waiting
        }
      }, 1500);
      pollIntervalRef.current = pollTimer;

      const res = await runPromise;
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }

      activeRunId = res.orchestrator_run_id;
      setLastRunResult(res);
      setIsWorking(false);
      setCurrentPhaseText("");
      setLastAnalysisTime(Date.now());

      try {
        const finalRuns = await fetchAgentRuns(25, res.orchestrator_run_id);
        setLiveRuns(finalRuns.runs || []);
      } catch {
        // non-fatal
      }
      try {
        const rankedResp = await fetchRankedOpportunities();
        setRanked(rankedResp.opportunities ?? []);
      } catch {
        // non-fatal
      }
      try {
        const refreshed = await fetchGrowthRadar(30);
        setRadar(refreshed);
      } catch {
        // non-fatal
      }
    } catch (e) {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      const msg = e instanceof Error ? e.message : "";
      if (msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403")) {
        setError("no_workspace");
      } else {
        setWorkError(
          msg || "The AI team could not complete this analysis. Please try again in a moment.",
        );
      }
      setIsWorking(false);
      setCurrentPhaseText("");
    }
  };

  if (error === "login_required") {
    return (
      <section className="shell section" aria-labelledby="agents-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">AI GROWTH TEAM</p>
          <h1 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>
            AI Growth Team
          </h1>
        </div>
        <WindowPanel title="login-required.app">
          <p className="meta-label" style={{ marginBottom: 12 }}>SIGN IN REQUIRED</p>
          <p style={{ fontSize: "var(--text-body)", lineHeight: "var(--leading-body)", color: "var(--ink-soft)" }}>
            Your AI Growth Team analyses your business data. Sign in to start
            an analysis of your live Razorpay TEST commerce data.
          </p>
          <div style={{ marginTop: 20, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Button variant="primary" mono onClick={() => navigate("/login")}>
              Sign in
            </Button>
          </div>
        </WindowPanel>
      </section>
    );
  }

  if (error === "no_workspace") {
    return (
      <section className="shell section" aria-labelledby="agents-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">AI GROWTH TEAM</p>
          <h1 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>
            AI Growth Team
          </h1>
        </div>
        <WindowPanel title="workspace-required.app">
          <p style={{ color: "var(--ink-soft)" }}>
            Connect your business workspace to unlock your AI Growth Team.
          </p>
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" mono onClick={() => navigate("/profile")}>
              View Profile →
            </Button>
          </div>
        </WindowPanel>
      </section>
    );
  }

  const metrics = radar?.metrics;
  const signals = radar?.signals?.length ?? 0;

  const agentOutputMap = new Map<string, OrchestrationAgentOutput>();
  if (lastRunResult?.agents) {
    for (const a of lastRunResult.agents) agentOutputMap.set(a.agent, a);
  }

  const runByAgent = new Map<string, AgentRunRow>();
  const runCountByAgent = new Map<string, number>();
  [...liveRuns].reverse().forEach((r) => {
    if (!runByAgent.has(r.agent_name)) runByAgent.set(r.agent_name, r);
    runCountByAgent.set(r.agent_name, (runCountByAgent.get(r.agent_name) ?? 0) + 1);
  });

  const executedAgentNames: string[] = [];
  [...liveRuns].reverse().forEach((r) => {
    if (!executedAgentNames.includes(r.agent_name)) executedAgentNames.push(r.agent_name);
  });
  lastRunResult?.agents?.forEach((a) => {
    if (a.status === "completed" && !executedAgentNames.includes(a.agent)) {
      executedAgentNames.push(a.agent);
    }
  });

  const allAgentNames = agentsMeta?.agents?.map((a) => a.name) || Object.keys(AGENT_PROFILES);
  const rosterOrder = [
    ...AGENT_ORDER.filter((n) => allAgentNames.includes(n)),
    ...allAgentNames.filter((n) => !AGENT_ORDER.includes(n)),
  ];

  const actionPlan: ActionPlan | null = lastRunResult?.action_plan ?? null;
  const totals = lastRunResult?.totals;

  const discovererNames = (lastRunResult?.agents ?? [])
    .filter((a) => a.status === "completed" && a.opportunities_created > 0)
    .map((a) => agentProfile(a.agent).label);

  const statusOf = (name: string): AgentUiStatus => {
    const run = runByAgent.get(name);
    const out = agentOutputMap.get(name);
    if (run) {
      if (run.status === "running") return { label: "WORKING", tone: "accent", marker: "--working" };
      if (run.status === "completed") {
        if (run.opportunities_created > 0)
          return { label: "FOUND SOMETHING", tone: "accent", marker: "--found" };
        return { label: "COMPLETED", tone: "ok", marker: "--done" };
      }
      if (run.status === "failed") return { label: "WAITING", tone: "neutral", marker: "" };
      return { label: "REVIEWING", tone: "accent", marker: "--working" };
    }
    if (out?.status === "completed") {
      if (out.opportunities_created > 0)
        return { label: "FOUND SOMETHING", tone: "accent", marker: "--found" };
      return { label: "COMPLETED", tone: "ok", marker: "--done" };
    }
    if (out) return { label: "REVIEWING", tone: "accent", marker: "--working" };
    return { label: "WAITING", tone: "neutral", marker: "" };
  };

  const findings = rosterOrder
    .map((name) => {
      const output = agentOutputMap.get(name);
      if (!output || output.status !== "completed") return null;
      const recs = output.output?.recommendations ?? [];
      const summary = output.output?.summary ?? "";
      if (!summary && recs.length === 0) return null;
      const profile = agentProfile(name);
      const finding = firstSentence(summary) || recs[0] || "Completed its analysis of your business data.";
      const action = recs.find((rec) => rec !== (firstSentence(summary) || "")) ?? recs[0] ?? null;
      const head = firstSentence(summary) ?? "";
      const rest = summary.replace(head, "").trim();
      const why = recs[1] ?? (rest ? firstSentence(rest) : null);
      return {
        name,
        label: profile.label,
        status: statusOf(name),
        finding,
        why: why && why !== finding ? why : null,
        evidence: profile.looksAt,
        action,
      };
    })
    .filter((f): f is NonNullable<typeof f> => f !== null);

  const runOpps = lastRunResult?.ranked_opportunities ?? [];
  const sources: Array<{
    title: string;
    type?: string;
    expectedRevenue?: number | null;
    confidenceValue?: number | null;
    rank: number;
  }> = [];
  if (runOpps.length > 0) {
    runOpps.forEach((o, idx) => {
      const sb = (o as { score_breakdown?: { confidence_score?: number } }).score_breakdown;
      sources.push({
        title: o.title,
        type: o.type,
        expectedRevenue: o.expected_revenue ?? null,
        confidenceValue: o.confidence ?? sb?.confidence_score ?? null,
        rank: idx + 1,
      });
    });
  } else if (ranked.length > 0) {
    ranked.forEach((o) => {
      sources.push({
        title: o.title,
        type: o.type,
        expectedRevenue: o.expected_revenue ?? null,
        confidenceValue: o.confidence ?? o.score_breakdown?.confidence_score ?? null,
        rank: o.rank,
      });
    });
  }

  const opportunities: OpportunityView[] = sources.map((src) => {
    const initiative = findInitiative(actionPlan, src.title);
    return {
      title: src.title,
      why: translateOpportunityType(src.type),
      evidence:
        initiative?.expected_impact ??
        `Ranked #${src.rank} by the AI team from your live Razorpay business data.`,
      impact: formatMoney(src.expectedRevenue)
        ? `Potential revenue impact: ${formatMoney(src.expectedRevenue)}`
        : null,
      action: initiative?.next_steps ?? null,
      discoveredBy: discovererNames.length > 0 ? discovererNames : [],
      confidence: confidenceWord(src.confidenceValue),
    };
  });

  const topOpp = opportunities[0] ?? null;
  const topInitiative = actionPlan?.initiatives?.[0] ?? null;
  const matchedTopInitiative = topOpp ? findInitiative(actionPlan, topOpp.title) : topInitiative;
  const showRecommendation = Boolean(topOpp || actionPlan || topInitiative);

  const latestCompletedAt = liveRuns
    .map((r) => r.completed_at)
    .filter((v): v is string => Boolean(v))
    .sort()
    .pop();
  const lastAnalysisTs =
    lastAnalysisTime ?? (latestCompletedAt ? new Date(latestCompletedAt).getTime() : null);

  return (
    <section className="shell section ai-team" aria-labelledby="agents-heading">
      <header className="ai-team__hero">
        <div className="ai-team__hero-text">
          <p className="meta-label">YOUR BUSINESS · AI WORKFORCE</p>
          <h1 id="agents-heading" className="display-lg">
            AI Growth Team
          </h1>
          <p className="ai-team__hero-lede">
            Your AI employees continuously analyze your Razorpay business data, find growth
            opportunities, and prepare actions for your approval.
          </p>
        </div>
        <div className="ai-team__hero-cta">
          <div className="ai-team-status">
            <span
              className={`ai-team-status__dot${isWorking ? " ai-team-status__dot--pulse" : ""}`}
              aria-hidden="true"
            />
            <span style={{ color: "var(--ink)", fontWeight: 700 }}>
              {isWorking ? "AI TEAM ACTIVE" : "AI TEAM STANDING BY"}
            </span>
            <span className="ai-team-status__sep">/</span>
            <span>
              {isWorking ? "Specialists working" : `${allAgentNames.length} specialists on the team`}
            </span>
            <span className="ai-team-status__sep">/</span>
            <span>Last analysis: {timeAgo(lastAnalysisTs)}</span>
          </div>
          <Button
            variant="primary"
            mono
            disabled={isWorking || !agentsMeta}
            onClick={() => handleStartAiWork()}
          >
            {isWorking ? "Analyzing your business…" : "Start AI Analysis →"}
          </Button>
        </div>
      </header>

      {workError && <div className="ai-team-error">{workError}</div>}

      <WindowPanel title="business-snapshot.app" tone="choc" dark>
        <p className="meta-label" style={{ marginBottom: 18 }}>
          BUSINESS SNAPSHOT · LIVE FROM YOUR RAZORPAY TEST ACCOUNT
        </p>
        <div className="ai-team-snapshot">
          <SnapshotCell
            label="Revenue"
            value={metrics ? (formatMoney(metrics.captured_revenue) ?? "—") : "…"}
            hint="Money successfully received"
          />
          <SnapshotCell
            label="Successful payments"
            value={metrics ? String(metrics.successful_payments ?? metrics.captured_transactions) : "…"}
            hint="Completed purchases"
          />
          <SnapshotCell
            label="Failed payments"
            value={metrics ? String(metrics.failed_payments) : "…"}
            hint="Recoverable checkouts"
            warn={Boolean(metrics && metrics.failed_payments > 0)}
          />
          <SnapshotCell
            label="Customers"
            value={metrics ? String(metrics.total_customers) : "…"}
            hint="Unique buyers"
          />
          <SnapshotCell
            label="Orders"
            value={metrics ? String(metrics.total_orders) : "…"}
            hint="Across all channels"
          />
          <SnapshotCell
            label="Growth signals"
            value={radar ? String(signals) : "…"}
            hint="Patterns worth acting on"
          />
        </div>
      </WindowPanel>

      <div>
        <div className="ai-team__section-head">
          <div>
            <h2>Live AI Work</h2>
            <p className="ai-team__section-sub">
              What each specialist is doing on your business data right now — and what they found.
            </p>
          </div>
          {isWorking && <StatusChip tone="accent" pulse>WORKING</StatusChip>}
        </div>
        <WindowPanel title="ai-live-work.app">
          {executedAgentNames.length === 0 ? (
            <div className="ai-team-empty">
              {isWorking
                ? "The team is starting — specialists will appear here as soon as they begin work."
                : "Your AI team is standing by. Start an analysis above to watch the specialists review your live Razorpay data — every task, finding, and recommendation will appear here."}
            </div>
          ) : (
            <div className="ai-team-live">
              {executedAgentNames.map((name) => {
                const profile = agentProfile(name);
                const status = statusOf(name);
                const output = agentOutputMap.get(name);
                const notes = liveNotesFor(name, output, radar);
                return (
                  <div className="ai-team-live__entry" key={name}>
                    <span
                      className={`ai-team-live__marker ai-team-live__marker${status.marker}`}
                      aria-hidden="true"
                    />
                    <div className="ai-team-live__body">
                      <div className="ai-team-live__meta">
                        <p className="ai-team-live__agent">{profile.label}</p>
                        <StatusChip tone={status.tone} pulse={status.marker === "--working"}>
                          {status.label}
                        </StatusChip>
                      </div>
                      <p className="ai-team-live__task">
                        Analyzing {LIVE_TASKS[name] ?? "your live business data"}...
                      </p>
                      {notes.length > 0 ? (
                        <ul className="ai-team-live__notes">
                          {notes.map((note, i) => (
                            <li className="ai-team-live__note" key={i}>
                              {note}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="ai-team-live__hint">Findings will appear as they are produced</p>
                      )}
                    </div>
                  </div>
                );
              })}
              {isWorking && currentPhaseText && (
                <p className="ai-team-live__hint">{currentPhaseText}</p>
              )}
            </div>
          )}
        </WindowPanel>
      </div>

      <div>
        <div className="ai-team__section-head">
          <div>
            <h2>Agent Findings</h2>
            <p className="ai-team__section-sub">
              What each specialist concluded from your data, in plain business language.
            </p>
          </div>
          {findings.length > 0 && (
            <span className="ai-team-status">{findings.length} COMPLETED</span>
          )}
        </div>
        {findings.length === 0 ? (
          <div className="ai-team-empty">
            No findings yet. Once the specialists finish analyzing your business data, their
            conclusions will be summarized here.
          </div>
        ) : (
          <div className="ai-team-findings">
            {findings.map((f) => (
              <article className="ai-team-finding" key={f.name}>
                <div className="ai-team-finding__head">
                  <p className="ai-team-finding__agent">{f.label}</p>
                  <StatusChip tone={f.status.tone}>{f.status.label}</StatusChip>
                </div>
                <div className="ai-team-finding__grid">
                  <span className="ai-team-finding__label">Finding</span>
                  <p className="ai-team-finding__text ai-team-finding__text--strong">{f.finding}</p>
                  {f.why && (
                    <>
                      <span className="ai-team-finding__label">Why it matters</span>
                      <p className="ai-team-finding__text">{f.why}</p>
                    </>
                  )}
                  <span className="ai-team-finding__label">Evidence</span>
                  <p className="ai-team-finding__text">{f.evidence}</p>
                  {f.action && (
                    <>
                      <span className="ai-team-finding__label">Recommended action</span>
                      <p className="ai-team-finding__text">{f.action}</p>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="ai-team__section-head">
          <div>
            <h2>Growth Opportunities Found</h2>
            <p className="ai-team__section-sub">
              Ranked by the AI team from your live Razorpay TEST data — with the recommended next
              move for each.
            </p>
          </div>
        </div>
        {opportunities.length === 0 ? (
          <div className="ai-team-empty">
            No clear growth opportunity has been found yet. The AI team is still analyzing your
            latest business activity — start an analysis above and check back in a moment.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {opportunities.map((opp, idx) => (
              <article className="ai-team-opp" key={`${opp.title}-${idx}`}>
                <div className="ai-team-opp__head">
                  <div>
                    <p className="meta-label" style={{ marginBottom: 4 }}>
                      OPPORTUNITY {idx + 1}
                    </p>
                    <h3 className="ai-team-opp__title">{opp.title}</h3>
                  </div>
                  {opp.impact && <p className="ai-team-opp__impact">{opp.impact}</p>}
                </div>
                <div className="ai-team-opp__grid">
                  <span className="ai-team-opp__label">Why it matters</span>
                  <p className="ai-team-opp__text">{opp.why}</p>
                  <span className="ai-team-opp__label">Evidence</span>
                  <p className="ai-team-opp__text">{opp.evidence}</p>
                  {opp.action && (
                    <>
                      <span className="ai-team-opp__label">Recommended action</span>
                      <p className="ai-team-opp__text ai-team-opp__text--strong">{opp.action}</p>
                    </>
                  )}
                  {opp.discoveredBy.length > 0 && (
                    <>
                      <span className="ai-team-opp__label">Discovered by</span>
                      <p className="ai-team-opp__text">{opp.discoveredBy.join(" + ")}</p>
                    </>
                  )}
                  {opp.confidence && (
                    <>
                      <span className="ai-team-opp__label">Confidence</span>
                      <p className="ai-team-opp__text">{opp.confidence}</p>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="ai-team__section-head">
          <div>
            <h2>How the AI Team Works</h2>
            <p className="ai-team__section-sub">
              From your real business data to an approved action — every step is shown above.
            </p>
          </div>
        </div>
        <WindowPanel title="ai-workflow.app" flush>
          <div className="ai-team-pipeline">
            <PipelineStep num="01" name="Real business data" hint="Payments, orders, customers" reached />
            <PipelineStep num="02" name="AI agents analyze" hint="Specialists work in parallel" reached={executedAgentNames.length > 0} />
            <PipelineStep num="03" name="Signals found" hint="Patterns worth acting on" reached={(totals?.signals_detected ?? 0) > 0 || signals > 0} />
            <PipelineStep num="04" name="Findings challenged" hint="Agents cross-examine in debate" reached={Boolean(lastRunResult?.debate_id)} />
            <PipelineStep num="05" name="Opportunities ranked" hint="Best ideas first" reached={opportunities.length > 0} />
            <PipelineStep num="06" name="Action prepared" hint="Ready for approval" reached={Boolean(actionPlan)} />
            <PipelineStep num="07" name="Human approval" hint="You stay in control" reached={false} />
          </div>
        </WindowPanel>
      </div>

      {showRecommendation && (
        <div>
          <div className="ai-team__section-head">
            <div>
              <h2>AI Team Recommendation</h2>
              <p className="ai-team__section-sub">
                The team&apos;s single highest-impact recommendation for your business right now.
              </p>
            </div>
          </div>
          <WindowPanel title="ai-recommendation.app" tone="choc" dark flush>
            <div className="ai-team-rec">
              <div className="ai-team-rec__main">
                <p className="meta-label" style={{ color: "var(--cream-muted)" }}>
                  PRIORITY OPPORTUNITY
                </p>
                <h3 className="ai-team-rec__title">
                  {topOpp?.title ?? topInitiative?.title ?? "Growth action plan"}
                </h3>
                <div className="ai-team-rec__grid">
                  <span className="ai-team-rec__label">Why we recommend this</span>
                  <p className="ai-team-rec__text">
                    {topOpp?.why ??
                      sentences(actionPlan?.executive_summary, 2) ??
                      "The team identified this as the strongest opportunity in your current business data."}
                  </p>                  <span className="ai-team-rec__label">Evidence</span>
                  <p className="ai-team-rec__text">
                    {topOpp?.evidence ??
                      matchedTopInitiative?.expected_impact ??
                      "Based on the team's analysis of your live Razorpay TEST data."}
                  </p>
                  {(topOpp?.impact || matchedTopInitiative?.expected_impact) && (
                    <>
                      <span className="ai-team-rec__label">Expected impact</span>
                      <p className="ai-team-rec__text ai-team-rec__text--strong">
                        {topOpp?.impact ?? matchedTopInitiative?.expected_impact}
                      </p>
                    </>
                  )}
                  <span className="ai-team-rec__label">Next step</span>
                  <p className="ai-team-rec__text">
                    {matchedTopInitiative?.next_steps ??
                      topOpp?.action ??
                      "Review and approve the recommended action below."}
                  </p>
                </div>
              </div>
              <div className="ai-team-rec__side">
                <div className="ai-team-rec__side-stat">
                  <span className="ai-team-rec__side-label">Opportunities found</span>
                  <span className="ai-team-rec__side-value">
                    {totals?.opportunities_created ?? opportunities.length}
                  </span>
                </div>
                <div className="ai-team-rec__side-stat">
                  <span className="ai-team-rec__side-label">Actions prepared</span>
                  <span className="ai-team-rec__side-value">
                    {totals?.actions_proposed ?? actionPlan?.initiatives?.length ?? 0}
                  </span>
                </div>
                <Button variant="primary" mono onClick={() => navigate("/actions")}>
                  Review &amp; Approve →
                </Button>
              </div>
            </div>
          </WindowPanel>
        </div>
      )}

      <div>
        <div className="ai-team__section-head">
          <div>
            <h2>The AI Team</h2>
            <p className="ai-team__section-sub">
              {allAgentNames.length} specialists. Click any agent to see the actual work it
              performed.
            </p>
          </div>
        </div>
        <WindowPanel title="ai-team-roster.app" flush>
          <div className="ai-team-roster">
            {rosterOrder.map((name) => {
              const profile = agentProfile(name);
              const status = statusOf(name);
              const output = agentOutputMap.get(name);
              const run = runByAgent.get(name);
              const workCount = runCountByAgent.get(name) ?? 0;
              const summary = output?.output?.summary ?? "";
              const recs = output?.output?.recommendations ?? [];
              const latestFinding =
                firstSentence(summary) || recs[0] || (run?.opportunities_created ? "Contributed to a growth opportunity" : "");
              const isOpen = expandedAgent === name;
              return (
                <div key={name}>
                  <button
                    type="button"
                    className="ai-team-roster__row"
                    aria-expanded={isOpen}
                    onClick={() => setExpandedAgent(isOpen ? null : name)}
                  >
                    <span className="ai-team-roster__id">
                      <span className="ai-team-roster__name">{profile.label}</span>
                      <span className="ai-team-roster__spec">{profile.specialty}</span>
                    </span>
                    <StatusChip tone={status.tone} pulse={status.marker === "--working"}>
                      {status.label}
                    </StatusChip>
                    <span className="ai-team-roster__work">
                      <span className="ai-team-roster__task">
                        <span className="ai-team-roster__muted">Analyzed: </span>
                        {LIVE_TASKS[name] ?? "your live business data"}
                      </span>
                      {latestFinding && (
                        <span className="ai-team-roster__finding">
                          Latest finding: <b>{latestFinding}</b>
                        </span>
                      )}
                    </span>
                    <span className="ai-team-roster__meta">
                      <span className="ai-team-roster__count">
                        {workCount > 0 ? `${workCount} completed ${workCount === 1 ? "analysis" : "analyses"}` : "Not run yet"}
                      </span>
                      <span className="ai-team-roster__toggle">{isOpen ? "Hide work" : "View work"}</span>
                    </span>
                  </button>
                  {isOpen && (
                    <div className="ai-team-work">
                      <div className="ai-team-work__grid">
                        <span className="ai-team-work__label">Agent</span>
                        <p className="ai-team-work__text ai-team-work__text--strong">
                          {profile.label} — {profile.specialty}
                        </p>
                        <span className="ai-team-work__label">Task</span>
                        <p className="ai-team-work__text">
                          {LIVE_TASKS[name] ?? "Analyze your live business data"}
                        </p>
                        <span className="ai-team-work__label">Data reviewed</span>
                        <p className="ai-team-work__text">{profile.looksAt}</p>
                        <span className="ai-team-work__label">Status</span>
                        <p className="ai-team-work__text">{status.label === "COMPLETED" ? "Completed this analysis" : status.label === "WORKING" ? "Currently working" : status.label === "WAITING" ? "Waiting for the next analysis" : "Reviewing results"}</p>
                        {summary && (
                          <>
                            <span className="ai-team-work__label">What it discovered</span>
                            <p className="ai-team-work__text">{summary}</p>
                          </>
                        )}
                        {recs.length > 0 && (
                          <>
                            <span className="ai-team-work__label">Recommendations</span>
                            <ul className="ai-team-work__recs">
                              {recs.map((rec, i) => (
                                <li className="ai-team-work__text" key={i}>
                                  {rec}
                                </li>
                              ))}
                            </ul>
                          </>
                        )}
                        {run && (run.opportunities_created > 0 || run.actions_proposed > 0) && (
                          <>
                            <span className="ai-team-work__label">Contribution</span>
                            <p className="ai-team-work__text">
                              {[
                                run.opportunities_created > 0
                                  ? `Contributed to ${run.opportunities_created} growth opportunit${run.opportunities_created === 1 ? "y" : "ies"}`
                                  : null,
                                run.actions_proposed > 0
                                  ? `Prepared ${run.actions_proposed} action${run.actions_proposed === 1 ? "" : "s"} for your approval`
                                  : null,
                              ]
                                .filter(Boolean)
                                .join(" and ")}
                              .
                            </p>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </WindowPanel>
      </div>

      <footer className="ai-team__footer">
        <Button variant="ghost-dark" mono onClick={() => navigate("/growth-radar")}>
          ← Growth Radar
        </Button>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Button variant="secondary" mono onClick={() => navigate("/debate")}>
            Agent Debate →
          </Button>
          <Button variant="primary" mono onClick={() => navigate("/actions")}>
            Review &amp; Approve Actions →
          </Button>
        </div>
      </footer>
    </section>
  );
}

function SnapshotCell({
  label,
  value,
  hint,
  warn = false,
}: {
  label: string;
  value: string;
  hint: string;
  warn?: boolean;
}) {
  return (
    <div className="ai-team-snapshot__cell">
      <p className="meta-label" style={{ color: "var(--cream-muted)" }}>
        {label}
      </p>
      <p
        className={`ai-team-snapshot__value${warn ? " ai-team-snapshot__value--warn" : ""}`}
        style={{ color: warn ? "var(--coral)" : "var(--green)" }}
      >
        {value}
      </p>
      <p className="ai-team-snapshot__hint">{hint}</p>
    </div>
  );
}

function PipelineStep({
  num,
  name,
  hint,
  reached,
}: {
  num: string;
  name: string;
  hint: string;
  reached: boolean;
}) {
  return (
    <div className="ai-team-pipeline__step" style={{ opacity: reached ? 1 : 0.5 }}>
      <span className="ai-team-pipeline__num">{num}</span>
      <span className="ai-team-pipeline__name">{name}</span>
      <span className="ai-team-pipeline__hint">{hint}</span>
    </div>
  );
}
