import { useReveal } from "../../../lib/useReveal";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip } from "../../../components/StatusIndicator";
import "./AudienceOverview.css";

const AUDIENCES = [
  {
    number: "01",
    title: "SOLO FOUNDERS",
    problem: "You wear every hat. Growth gets pushed to tomorrow.",
    solution: "An AI growth department that watches, plans, and drafts while you decide.",
    agents: ["Growth Analyst", "Marketing Agent", "Customer Intel Agent"],
    protection: "Every action waits for your approval. Nothing executes without you."
  },
  {
    number: "02",
    title: "LEAN STARTUPS",
    problem: "Small team. Big surface area. Signals slip through cracks.",
    solution: "Continuous monitoring across revenue, churn, and acquisition — agents never sleep.",
    agents: ["Campaign Agent", "Retention Agent", "Acquisition Agent"],
    protection: "Bounded plans. Explicit guardrails. Human gate on every execution."
  },
  {
    number: "03",
    title: "GROWTH TEAMS",
    problem: "Context scattered across tools. Handoffs lose signal. Decisions stall.",
    solution: "One shared workspace. Centralized opportunities. Unified approval queue. Full audit trail.",
    agents: ["Growth Analyst", "Experimentation Agent", "Customer Intel Agent", "Campaign Agent"],
    protection: "Team-wide visibility. Role-based approvals. Replayable history."
  },
  {
    number: "04",
    title: "ENTERPRISE",
    problem: "Compliance demands control. Data must stay isolated. Actions need traceability.",
    solution: "Tenant isolation. Role-based access. Approval enforcement. Complete audit history.",
    agents: ["Growth Analyst", "Compliance Agent", "Customer Intel Agent", "Campaign Agent", "Operations Agent"],
    protection: "Guardrails wrap every step. Approval cannot be bypassed by any role, token, or agent."
  }
] as const;

export function AudienceOverview() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="audience-overview" className="shell section" aria-labelledby="audience-overview-heading">
      <div className="page-hero">
        <p className="meta-label">AUDIENCE · OVERVIEW</p>
        <h2 id="audience-overview-heading" className="display-lg" style={{ marginTop: 10, maxWidth: "24ch" }}>
          Who RazorGrowth AI is built for.
        </h2>
      </div>

      <div ref={reveal} className="reveal">
        <div className="audience-grid">
          {AUDIENCES.map((audience) => (
            <article key={audience.title} className="audience-card">
              <div className="audience-card__header">
                <span className="audience-card__number">{audience.number}</span>
                <h3 className="audience-card__title">{audience.title}</h3>
              </div>

              <div className="audience-card__problem">
                <span className="meta-label">PROBLEM</span>
                <p>{audience.problem}</p>
              </div>

              <div className="audience-card__solution">
                <span className="meta-label">WHAT RAZORGROWTH AI DOES</span>
                <p>{audience.solution}</p>
              </div>

              <div className="audience-card__agents">
                <span className="meta-label">AI EMPLOYEES</span>
                <div className="audience-card__agent-list">
                  {audience.agents.map((agent, i) => (
                    <StatusChip key={agent} tone={i === 0 ? "ok" : "neutral"} pulse={i === 0}>
                      {agent}
                    </StatusChip>
                  ))}
                </div>
              </div>

              <hr className="meta-rule" style={{ marginBlock: 16 }} />

              <div className="audience-card__protection">
                <span className="meta-label">HUMAN APPROVAL PROTECTS YOU</span>
                <p style={{ color: "var(--ink-soft)", fontSize: "var(--text-small)" }}>
                  {audience.protection}
                </p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}