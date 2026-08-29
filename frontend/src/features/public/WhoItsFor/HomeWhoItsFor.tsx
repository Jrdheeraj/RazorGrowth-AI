import { useReveal } from "../../../lib/useReveal";
import { StatusIndicator } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import "./HomeWhoItsFor.css";

const AUDIENCES = [
  {
    id: "solo-founders",
    number: "01",
    title: "SOLO FOUNDERS",
    windowTitle: "founder.workspace",
    tagline: "Run growth without building a full department.",
    description: "AI agents monitor signals, find opportunities, and prepare recommendations while you stay in control.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "ONLINE", text: "Revenue signal detected" },
      { tone: "accent" as const, pulse: true, label: "SCORING", text: "Opportunity score 87%" },
      { tone: "accent" as const, pulse: false, label: "PENDING", text: "AI recommendation prepared" },
    ],
    cta: "REVIEW PROPOSAL",
  },
  {
    id: "lean-startups",
    number: "02",
    title: "LEAN STARTUPS",
    windowTitle: "startup.monitor",
    tagline: "Move faster without adding unnecessary headcount.",
    description: "Deploy AI agents to monitor opportunities, prepare campaigns, and keep execution moving.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "ONLINE", text: "Churn risk flagged" },
      { tone: "accent" as const, pulse: true, label: "SCORING", text: "Retention opportunity 73%" },
      { tone: "accent" as const, pulse: false, label: "PENDING", text: "Win-back sequence drafted" },
    ],
    cta: "LAUNCH CAMPAIGN",
  },
  {
    id: "growth-teams",
    number: "03",
    title: "GROWTH TEAMS",
    windowTitle: "team.workspace",
    tagline: "Give humans and AI agents one shared operating context.",
    description: "Keep marketing, product, sales, and growth work connected in one workspace.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "ACTIVE", text: "7 active opportunities" },
      { tone: "accent" as const, pulse: true, label: "REVIEWING", text: "Team reviewing 3 proposals" },
      { tone: "accent" as const, pulse: false, label: "PENDING", text: "Approval queue live" },
    ],
    cta: "VIEW WORKSPACE",
  },
  {
    id: "enterprise",
    number: "04",
    title: "ENTERPRISE",
    windowTitle: "enterprise.governance",
    tagline: "Scale AI growth with governance and control.",
    description: "Deploy agents with role-based permissions, activity visibility, and auditable workflows.",
    signals: [
      { tone: "ok" as const, pulse: true, label: "VERIFIED", text: "Tenant isolation verified" },
      { tone: "ok" as const, pulse: true, label: "ENFORCED", text: "RBAC enforced 100%" },
      { tone: "accent" as const, pulse: false, label: "RECORDING", text: "Audit trail recording" },
    ],
    cta: "VIEW CONTROLS",
  },
] as const;

type Audience = (typeof AUDIENCES)[number];

function AudienceCard({ audience, index }: { audience: Audience; index: number }) {
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
        <h3 className="who-card__title">{audience.title}</h3>
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
      >
        <span>{audience.cta}</span>
        <span className="who-card__cta-arrow" aria-hidden="true">
          -&gt;
        </span>
      </button>
    </article>
  );
}

export function HomeWhoItsFor() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="who-its-for" className="shell section" aria-labelledby="who-heading">
      <SectionWindowHeader
        eyebrow="WHO IT'S FOR · AUDIENCE"
        title="One workspace. Shared context."
        accentTitle="No juggling."
        description="RazorGrowth AI gives solo founders, lean startups, growth teams and enterprises an always-on AI growth department — agents do the watching, planning and drafting; people make the calls."
        id="who-heading"
        windowTitle="razorgrowth — welcome.app"
        compact
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
