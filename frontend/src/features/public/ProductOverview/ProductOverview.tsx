import { Link } from "react-router-dom";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./ProductOverview.css";

const WORKFLOW_PILLARS = [
  {
    step: "01",
    phase: "DISCOVERY",
    icon: "📡",
    title: "Signal Discovery",
    desc: "Scans real transaction and customer data to flag revenue leakages, cart abandonment, and conversion drop-offs.",
    tag: "GROWTH RADAR",
    linkTo: "/growth-radar",
    linkText: "Open Radar →",
  },
  {
    step: "02",
    phase: "COORDINATION",
    icon: "🧭",
    title: "Manager Agent",
    desc: "Breaks high-level growth objectives into structured tasks and assigns work to specialized autonomous agents.",
    tag: "ORCHESTRATOR",
    linkTo: "/manager-agent",
    linkText: "View Manager →",
  },
  {
    step: "03",
    phase: "COLLABORATION",
    icon: "💬",
    title: "Specialist Debates",
    desc: "Marketing, Product, Design, and Software agents evaluate feasibility and debate trade-offs before proposing actions.",
    tag: "AGENT DEBATES",
    linkTo: "/debate",
    linkText: "Explore Debates →",
  },
  {
    step: "04",
    phase: "HUMAN CONTROL",
    icon: "🛡️",
    title: "Decision Gate",
    desc: "Every consequential action requires human sign-off with clear Will Do / Will Not Do boundaries and monetary caps.",
    tag: "APPROVAL REQUIRED",
    linkTo: "/actions",
    linkText: "Actions Console →",
  },
  {
    step: "05",
    phase: "AUDITED EXECUTION",
    icon: "📜",
    title: "Bounded Execution",
    desc: "Approved actions execute safely within limits while every decision and outcome is recorded in an immutable audit trail.",
    tag: "AUDIT LOGGED",
    linkTo: "/actions",
    linkText: "Inspect Audit →",
  },
] as const;

export function ProductOverview() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="overview" className="shell section overview-section" aria-labelledby="overview-heading">
      <SectionWindowHeader
        id="overview-heading"
        eyebrow="SYSTEM ARCHITECTURE · CONNECTED WORKFLOW"
        title="Everything your growth workflow needs,"
        accentTitle="connected."
        description="RazorGrowth AI connects live revenue signals, autonomous specialist agents, human-reviewed proposals, and bounded execution in one coordinated growth operating system."
        windowTitle="razorgrowth — architecture.app"
      />

      <div ref={reveal} className="reveal" style={{ marginTop: 22 }}>
        <div className="overview-grid" role="list">
          {WORKFLOW_PILLARS.map((p) => (
            <article key={p.step} className="overview-card" role="listitem">
              <div className="overview-card__step">
                <span>{p.step} · {p.phase}</span>
              </div>
              <div className="overview-card__icon" aria-hidden="true">{p.icon}</div>
              <h3 className="overview-card__title">{p.title}</h3>
              <p className="overview-card__desc">{p.desc}</p>
              <span className="overview-card__tag">{p.tag}</span>
              <Link to={p.linkTo} className="overview-card__link">
                {p.linkText}
              </Link>
            </article>
          ))}
        </div>

        <div className="overview-flow-indicator" aria-hidden="true">
          <span>Continuous Loop:</span>
          <strong>Signal Detected</strong> → <strong>Tasks Assigned</strong> → <strong>Debate & Refine</strong> → <strong>Human Approval</strong> → <strong>Audit Trail Logged</strong>
        </div>
      </div>
    </section>
  );
}
