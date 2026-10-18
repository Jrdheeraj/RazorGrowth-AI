import { ManagerCommandCenter } from "./ManagerCommandCenter";

interface ManagerHeroProps {
  onCreatePlan: (goal: string) => Promise<void>;
  isCreating: boolean;
  statusMessage?: string | null;
  agentStatusOverrides?: Record<string, string>;
}

interface StatItem {
  id: string;
  val: string;
  unit: string;
  title: string;
  desc: string;
  statusBadge: string;
  icon: React.ReactNode;
}

const STATS_ITEMS: StatItem[] = [
  {
    id: "agents",
    val: "13",
    unit: "Specialists",
    title: "Autonomous Fleet",
    desc: "Cross-functional AI agents synchronized across marketing, tech & revenue.",
    statusBadge: "13 Active Nodes",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="18" cy="5" r="3" />
        <circle cx="6" cy="12" r="3" />
        <circle cx="18" cy="19" r="3" />
        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49" />
        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49" />
      </svg>
    ),
  },
  {
    id: "latency",
    val: "< 450ms",
    unit: "Consensus Loop",
    title: "Instant Synthesis",
    desc: "Deterministic goal decomposition and real-time conflict arbitration.",
    statusBadge: "Real-Time Arbitration",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
      </svg>
    ),
  },
  {
    id: "guardrails",
    val: "100%",
    unit: "Audited",
    title: "Safety Guardrails",
    desc: "Every campaign, pricing curve and code change strictly verified.",
    statusBadge: "Zero Rogue Actions",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <polyline points="9 12 11 14 15 10" />
      </svg>
    ),
  },
];

export function ManagerHero({
  onCreatePlan,
  isCreating,
  statusMessage,
  agentStatusOverrides,
}: ManagerHeroProps) {
  return (
    <section className="mgr-hero" aria-label="Manager Agent Hero">
      {/* Left Column: Strong Editorial Typography, Workflow & Key Performance Matrix */}
      <div className="mgr-hero__left">
        <div className="mgr-hero__editorial">
          <div className="mgr-hero__eyebrow">
            <span className="mgr-hero__eyebrowDot" aria-hidden="true" />
            <span>MANAGER AGENT · AUTONOMOUS GROWTH ORCHESTRATOR</span>
          </div>

          <h1 className="mgr-hero__headline">
            One goal.<br />
            Every agent.<br />
            <span className="mgr-hero__headlineAccent">Smarter growth.</span>
          </h1>

          <p className="mgr-hero__desc">
            Coordinate your AI team, turn merchant goals into intelligent execution, and drive measurable business growth.
          </p>

          {/* 4 Elegant workflow steps in one horizontal row */}
          <div className="mgr-hero__workflow" aria-label="Manager orchestration workflow">
            <div className="mgr-hero__workflowStep">
              <span className="mgr-hero__workflowNum">01</span>
              <div className="mgr-hero__workflowIcon" aria-hidden="true">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <circle cx="12" cy="12" r="5" />
                  <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                </svg>
              </div>
              <span className="mgr-hero__workflowLabel">Understand</span>
            </div>

            <span className="mgr-hero__workflowSep" aria-hidden="true" />

            <div className="mgr-hero__workflowStep">
              <span className="mgr-hero__workflowNum">02</span>
              <div className="mgr-hero__workflowIcon" aria-hidden="true">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </div>
              <span className="mgr-hero__workflowLabel">Delegate</span>
            </div>

            <span className="mgr-hero__workflowSep" aria-hidden="true" />

            <div className="mgr-hero__workflowStep">
              <span className="mgr-hero__workflowNum">03</span>
              <div className="mgr-hero__workflowIcon" aria-hidden="true">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <polyline points="9 12 11 14 15 10" />
                </svg>
              </div>
              <span className="mgr-hero__workflowLabel">Validate</span>
            </div>

            <span className="mgr-hero__workflowSep" aria-hidden="true" />

            <div className="mgr-hero__workflowStep">
              <span className="mgr-hero__workflowNum">04</span>
              <div className="mgr-hero__workflowIcon" aria-hidden="true">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="20" x2="18" y2="10" />
                  <line x1="12" y1="20" x2="12" y2="4" />
                  <line x1="6" y1="20" x2="6" y2="14" />
                </svg>
              </div>
              <span className="mgr-hero__workflowLabel">Deliver</span>
            </div>
          </div>
        </div>

        {/* Orchestration Performance & Trust Matrix (3 Stat Cards) */}
        <div className="mgr-hero__statsGrid" role="group" aria-label="Orchestrator Key Performance Indicators">
          {STATS_ITEMS.map((item) => (
            <div key={item.id} className="mgr-hero__statCard">
              <div className="mgr-hero__statTop">
                <div className="mgr-hero__statHead">
                  <div className="mgr-hero__statIcon" aria-hidden="true">
                    {item.icon}
                  </div>
                  <span className="mgr-hero__statUnit">{item.unit}</span>
                </div>
                <div className="mgr-hero__statValue">{item.val}</div>
                <div className="mgr-hero__statTitle">{item.title}</div>
                <p className="mgr-hero__statDesc">{item.desc}</p>
              </div>
              <div className="mgr-hero__statBadge">
                <span className="mgr-hero__statBadgeDot" aria-hidden="true" />
                <span>{item.statusBadge}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right Column: Premium AI Command Center Visual */}
      <div className="mgr-hero__right">
        <ManagerCommandCenter
          onCreatePlan={onCreatePlan}
          isCreating={isCreating}
          statusMessage={statusMessage}
          agentStatusOverrides={agentStatusOverrides}
        />
      </div>
    </section>
  );
}
