import { useNavigate } from "react-router-dom";
import { useReveal } from "../../../lib/useReveal";
import { StatusIndicator } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import "./HomeWhoItsFor.css";

const AUDIENCES = [
  {
    id: "solo-founders",
    number: "01",
    icon: "👤",
    title: "SOLO FOUNDERS",
    windowTitle: "founder.workspace",
    tagline: "Discover opportunities and prepare growth actions without coordinating a large team.",
    description: "AI specialists monitor store performance, identify high-intent customers, and draft actions for your one-click review.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "MONITOR", text: "Cart drop-off leakage detected" },
      { tone: "accent" as const, pulse: false, label: "ACTION", text: "Automated recovery action queued" },
    ],
    cta: "Explore AI Agents →",
    targetRoute: "/agents",
  },
  {
    id: "lean-startups",
    number: "02",
    icon: "🚀",
    title: "LEAN STARTUPS",
    windowTitle: "startup.monitor",
    tagline: "Connect growth analysis, campaign planning, and product experiments in one workflow.",
    description: "Move from detection to execution without adding coordination overhead. Product, marketing, and design work stay linked.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "SIGNALS", text: "Real-time growth radar active" },
      { tone: "accent" as const, pulse: false, label: "DEBATE", text: "Discount threshold debated" },
    ],
    cta: "View Growth Radar →",
    targetRoute: "/growth-radar",
  },
  {
    id: "growth-teams",
    number: "03",
    icon: "👥",
    title: "GROWTH TEAMS",
    windowTitle: "team.workspace",
    tagline: "Give specialists and AI agents a shared place to investigate, plan, and review work.",
    description: "ManagerAgent assigns tasks across marketing, product, creative design, and technical feasibility so your team never works in silos.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "COORDINATE", text: "Multi-agent plan structured" },
      { tone: "accent" as const, pulse: true, label: "CONSENSUS", text: "Cross-specialist review ready" },
    ],
    cta: "Meet Manager Agent →",
    targetRoute: "/manager-agent",
  },
  {
    id: "organizations",
    number: "04",
    icon: "🏢",
    title: "LARGER ORGANIZATIONS",
    windowTitle: "enterprise.governance",
    tagline: "Make growth workflows easier to review with permissions, controlled actions, and traceable activity.",
    description: "Enforce strict tenant isolation, human approval boundaries, and immutable audit logs on every proposed financial action.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "ISOLATED", text: "Strict tenant boundary enforced" },
      { tone: "accent" as const, pulse: false, label: "AUDIT", text: "Every decision logged immutably" },
    ],
    cta: "Actions & Approvals →",
    targetRoute: "/actions",
  },
] as const;

type Audience = (typeof AUDIENCES)[number];

function AudienceCard({ audience, index }: { audience: Audience; index: number }) {
  const navigate = useNavigate();

  return (
    <article
      className="who-card"
      role="listitem"
      style={{ transitionDelay: `${index * 60}ms` } as React.CSSProperties}
    >
      <div className="who-card__eyebrow">{audience.windowTitle}</div>
      <div className="who-card__divider" aria-hidden="true" />

      <div className="who-card__header">
        <span className="who-card__number">{audience.number}</span>
        <h3 className="who-card__title">
          <span style={{ marginRight: 6 }} aria-hidden="true">{audience.icon}</span>
          {audience.title}
        </h3>
      </div>

      <p className="who-card__primary">{audience.tagline}</p>
      <p className="who-card__support">{audience.description}</p>

      <div className="who-card__activity" aria-label={`${audience.title} activity`}>
        {audience.signals.map((signal) => (
          <div key={`${signal.label}-${signal.text}`} className="who-activity">
            <StatusIndicator tone={signal.tone} pulse={signal.pulse} label={signal.label} />
            <div className="who-activity__copy">
              <span className="who-activity__label">{signal.label}</span>
              <span className="who-activity__text">{signal.text}</span>
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        className="who-card__cta"
        aria-label={`${audience.title}: ${audience.cta}`}
        onClick={() => navigate(audience.targetRoute)}
      >
        <span>{audience.cta}</span>
      </button>
    </article>
  );
}

export function HomeWhoItsFor() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="who-its-for" className="shell section" aria-labelledby="who-heading">
      <SectionWindowHeader
        id="who-heading"
        eyebrow="AUDIENCE · TAILORED USE CASES"
        title="Built for teams that need"
        accentTitle="more growth capacity."
        description="Whether you are a solo merchant or leading a high-velocity growth organization, RazorGrowth AI adapts to your operational scale while keeping humans in control."
        windowTitle="razorgrowth — audience.app"
      />

      <div ref={reveal} className="reveal">
        <div className="home-whoitsfor__grid" role="list">
          {AUDIENCES.map((audience, index) => (
            <AudienceCard key={audience.id} audience={audience} index={index} />
          ))}
        </div>
      </div>
    </section>
  );
}
