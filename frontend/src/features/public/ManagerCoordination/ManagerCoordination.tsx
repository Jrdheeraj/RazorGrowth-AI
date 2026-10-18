import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./ManagerCoordination.css";

const COORDINATED_SPECIALISTS = [
  {
    icon: "📣",
    name: "Marketing Agent",
    badge: "CAMPAIGNS & RETENTION",
    desc: "Drafts hyper-segmented email/SMS campaigns, seasonal promotions, and personalized customer messaging.",
    route: "/marketing-agent",
  },
  {
    icon: "📦",
    name: "Product Agent",
    badge: "CATALOG & PRICING",
    desc: "Evaluates inventory turnover, conversion friction, price elasticity, and creates high-impact catalog tests.",
    route: "/product-agent",
  },
  {
    icon: "🎨",
    name: "Designer Agent",
    badge: "CREATIVE & ASSETS",
    desc: "Generates advertising banners, visual concepts, creative briefs, and promotional aesthetic guidelines.",
    route: "/designer-agent",
  },
  {
    icon: "⚡",
    name: "Software Agent",
    badge: "FEASIBILITY & CODE",
    desc: "Validates technical execution, webhook payloads, integration boundaries, and automation scripts.",
    route: "/software-agent",
  },
  {
    icon: "💳",
    name: "Payment Recovery Specialist",
    badge: "LEAKAGE RECOVERY",
    desc: "Analyzes failure reasons and prepares safe, non-invasive single-retry workflows for drop-offs.",
    route: "/actions",
  },
] as const;

export function ManagerCoordination() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="manager-coordination" className="shell section manager-section" aria-labelledby="manager-heading">
      <SectionWindowHeader
        id="manager-heading"
        eyebrow="AUTONOMOUS ORCHESTRATION · MANAGER AGENT"
        title="One manager."
        accentTitle="Coordinated specialists."
        description="Rather than running unguided bots, RazorGrowth AI pairs you with ManagerAgent — an orchestrator that decomposes strategic goals into multi-agent task graphs with clear dependencies."
        windowTitle="razorgrowth — manager_orchestrator.app"
      />

      <div ref={reveal} className="reveal manager-orchestration-panel">
        <WindowPanel title="manager-agent.plan" flush>
          <div style={{ padding: "clamp(16px, 3vw, 24px)" }}>
            <div className="manager-layout">
              {/* Left Column: Manager Card */}
              <div className="manager-orchestrator-card">
                <div className="manager-badge-row">
                  <span className="manager-badge">
                    <StatusIndicator tone="ok" pulse label="active" />
                    AUTONOMOUS ORCHESTRATOR
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--ink-faint)" }}>
                    CENTRAL DISPATCH
                  </span>
                </div>

                <h3 className="manager-role-title">Manager Agent</h3>
                <p className="manager-role-desc">
                  Transforms your high-level business goals into a structured, dependency-checked execution plan. Tracks task state in real time and synthesizes findings into a single human review gate.
                </p>

                <ul className="manager-capabilities-list">
                  <li className="manager-capability-item">
                    <span className="manager-capability-dot">✦</span>
                    <div>
                      <strong>Goal Decomposition:</strong> Automatically structures complex objectives into step-by-step tasks.
                    </div>
                  </li>
                  <li className="manager-capability-item">
                    <span className="manager-capability-dot">✦</span>
                    <div>
                      <strong>Topological Task Graph:</strong> Ensures research precedes creative work and creative precedes technical specs.
                    </div>
                  </li>
                  <li className="manager-capability-item">
                    <span className="manager-capability-dot">✦</span>
                    <div>
                      <strong>Action Synthesis:</strong> Compiles specialist outputs into bounded, reviewable Growth Action proposals.
                    </div>
                  </li>
                </ul>

                <Link to="/manager-agent" className="manager-cta-btn">
                  Launch Manager Agent Console →
                </Link>
              </div>

              {/* Right Column: Specialists Roster */}
              <div className="specialists-roster-column">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.74rem", fontWeight: 700, color: "var(--ink-faint)", letterSpacing: "0.08em" }}>
                    MANAGED SPECIALIST WORKFORCE
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--coral-strong)" }}>
                    5 WORKSTATIONS ACTIVE
                  </span>
                </div>

                {COORDINATED_SPECIALISTS.map((s) => (
                  <div key={s.name} className="specialist-card">
                    <div className="specialist-avatar" aria-hidden="true">{s.icon}</div>
                    <div className="specialist-info">
                      <div className="specialist-top">
                        <h4 className="specialist-name">{s.name}</h4>
                        <span className="specialist-badge">{s.badge}</span>
                      </div>
                      <p className="specialist-desc">{s.desc}</p>
                      <Link to={s.route} className="specialist-link">
                        Open workstation →
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
