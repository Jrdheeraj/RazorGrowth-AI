import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip, StatusIndicator } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./Agents.css";

const CONFIRMED_ROSTER = [
  {
    id: "manager-agent",
    file: "manager-agent.agent",
    icon: "🧭",
    name: "Manager Agent",
    role: "WORKFLOW ORCHESTRATOR",
    line: "Translates high-level business goals into structured multi-step plans and coordinates specialists.",
    tools: ["plan_workflow", "assign_task", "aggregate_results"],
    route: "/manager-agent",
    linkText: "Manager Console →",
  },
  {
    id: "marketing-agent",
    file: "marketing-agent.agent",
    icon: "📣",
    name: "Marketing Agent",
    role: "CAMPAIGNS & RETENTION",
    line: "Segments customer audiences, drafts promotional messages, and creates targeted email/SMS sequences.",
    tools: ["draft_campaign", "segment_audience", "evaluate_cadence"],
    route: "/marketing-agent",
    linkText: "Marketing Desk →",
  },
  {
    id: "product-agent",
    file: "product-agent.agent",
    icon: "📦",
    name: "Product Agent",
    role: "CATALOG & EXPERIMENTS",
    line: "Evaluates pricing elasticity, conversion funnel friction, inventory velocity, and product-page lift.",
    tools: ["analyze_catalog", "price_elasticity", "design_test"],
    route: "/product-agent",
    linkText: "Product Desk →",
  },
  {
    id: "designer-agent",
    file: "designer-agent.agent",
    icon: "🎨",
    name: "Designer Agent",
    role: "CREATIVE & ASSETS",
    line: "Produces creative briefs, banner layouts, advertising copy, and campaign visual guidelines.",
    tools: ["generate_brief", "layout_spec", "color_palette"],
    route: "/designer-agent",
    linkText: "Creative Studio →",
  },
  {
    id: "software-agent",
    file: "software-agent.agent",
    icon: "⚡",
    name: "Software Agent",
    role: "TECHNICAL FEASIBILITY",
    line: "Verifies technical feasibility, API webhook payloads, tracking events, and automation scripts.",
    tools: ["validate_payload", "check_webhook", "code_spec"],
    route: "/software-agent",
    linkText: "Engineering Desk →",
  },
  {
    id: "payment-recovery",
    file: "payment-recovery.agent",
    icon: "💳",
    name: "Payment Recovery Specialist",
    role: "REVENUE LEAKAGE",
    line: "Distinguishes recoverable payment failures from hard declines and designs safe single-retry workflows.",
    tools: ["classify_decline", "bounded_retry", "reconcile_invoice"],
    route: "/actions",
    linkText: "Review Retries →",
  },
  {
    id: "customer-intel",
    file: "customer-intel.agent",
    icon: "👥",
    name: "Customer Intelligence Specialist",
    role: "SEGMENTS & CHURN",
    line: "Calculates RFM metrics, predicts customer drop-off risks, and surfaces high-value loyalty segments.",
    tools: ["rfm_scoring", "churn_risk", "clv_estimation"],
    route: "/growth-radar",
    linkText: "Customer Signals →",
  },
  {
    id: "growth-discovery",
    file: "growth-discovery.agent",
    icon: "📊",
    name: "Growth Discovery Specialist",
    role: "OPPORTUNITY DETECTION",
    line: "Continuously scans order velocity and transaction patterns to surface high-impact growth opportunities.",
    tools: ["scan_anomalies", "detect_leakage", "rank_priority"],
    route: "/growth-radar",
    linkText: "Radar Signals →",
  },
] as const;

export function Agents() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="agents" className="shell section" aria-labelledby="agents-heading">
      <SectionWindowHeader
        id="agents-heading"
        eyebrow="AI WORKFORCE · SPECIALIST ROSTER"
        title="A coordinated team of"
        accentTitle="specialist agents."
        description="Every agent in RazorGrowth AI operates with a registered tool catalog, explicit permissions, and clear accountability. They prepare work; you retain the decision gate."
        windowTitle="razorgrowth — ai_team_roster.app"
      />

      <div ref={reveal} className="reveal">
        <div className="agents-grid">
          {CONFIRMED_ROSTER.map((a) => (
            <WindowPanel key={a.id} title={a.file} className="agent-card">
              <div className="agent-card__header">
                <StatusChip tone="ok" pulse>REGISTERED AGENT</StatusChip>
                <StatusIndicator tone="ok" label="ready" />
              </div>

              <div className="agent-card__icon-row">
                <span className="agent-card__icon" aria-hidden="true">{a.icon}</span>
                <h3 className="agent-card__name">{a.name}</h3>
              </div>

              <span className="agent-card__role-badge">{a.role}</span>
              <p className="agent-card__line">{a.line}</p>

              <div className="agent-card__tools" aria-label="Registered Tools">
                <span style={{ fontWeight: 700 }}>TOOLS:</span>
                {a.tools.map((t) => (
                  <span key={t} className="agent-card__tool-tag">{t}</span>
                ))}
              </div>

              <div className="agent-card__footer">
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.68rem", color: "var(--ink-faint)" }}>
                  HUMAN GATE ENFORCED
                </span>
                <Link to={a.route} className="agent-card__link">
                  {a.linkText}
                </Link>
              </div>
            </WindowPanel>
          ))}
        </div>

        <div className="agent-roster-cta">
          <p className="agent-roster-cta-text">
            All agents are registered in the backend registry with strict permission boundaries — no agent can authorize budgets or mutate production without human approval.
          </p>
          <Link to="/agents" className="agent-roster-cta-btn">
            Open AI Team Command Center →
          </Link>
        </div>
      </div>
    </section>
  );
}