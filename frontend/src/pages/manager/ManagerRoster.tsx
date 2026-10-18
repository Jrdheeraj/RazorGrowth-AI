import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../../components/WindowPanel";

interface AgentCardDef {
  key: string;
  name: string;
  route?: string;
  statusText: string;
  statusType: "active" | "ready" | "working" | "guarded" | "synced";
  iconColor: string;
  iconBg: string;
  icon: React.ReactNode;
}

const ROSTER_AGENTS: AgentCardDef[] = [
  {
    key: "DiscoveryAgent",
    name: "Discovery Agent",
    statusText: "Active",
    statusType: "active",
    iconColor: "#0284c7",
    iconBg: "#e0f2fe",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" fill="currentColor" fillOpacity="0.3" />
      </svg>
    ),
  },
  {
    key: "MarketingAgent",
    name: "Marketing Agent",
    route: "/marketing-agent",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#dc2626",
    iconBg: "#fee2e2",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="m3 11 18-5v12L3 13v-2z" />
        <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
      </svg>
    ),
  },
  {
    key: "ProductAgent",
    name: "Product Agent",
    route: "/product-agent",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#ea580c",
    iconBg: "#ffedd5",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
        <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
        <line x1="12" y1="22.08" x2="12" y2="12" />
      </svg>
    ),
  },
  {
    key: "DesignerAgent",
    name: "Designer Agent",
    route: "/designer-agent",
    statusText: "Working",
    statusType: "working",
    iconColor: "#7c3aed",
    iconBg: "#ede9fe",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="3" width="18" height="18" rx="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <polyline points="21 15 16 10 5 21" />
      </svg>
    ),
  },
  {
    key: "SoftwareAgent",
    name: "Software Agent",
    route: "/software-agent",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#0d9488",
    iconBg: "#ccfbf1",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    ),
  },
  {
    key: "CustomerIntelligenceAgent",
    name: "Customer Intelligence",
    statusText: "Active",
    statusType: "active",
    iconColor: "#0284c7",
    iconBg: "#e0f2fe",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    key: "RevenueOptimizationAgent",
    name: "Revenue Optimization",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#16a34a",
    iconBg: "#dcfce7",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
  },
  {
    key: "PaymentRecoveryAgent",
    name: "Payment Recovery",
    statusText: "Guarded",
    statusType: "guarded",
    iconColor: "#9333ea",
    iconBg: "#f3e8ff",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="5" width="20" height="14" rx="2" />
        <line x1="2" y1="10" x2="22" y2="10" />
      </svg>
    ),
  },
  {
    key: "ExperimentAgent",
    name: "Experiment Agent",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#ea580c",
    iconBg: "#ffedd5",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2" />
        <line x1="8.5" y1="2" x2="15.5" y2="2" />
      </svg>
    ),
  },
  {
    key: "GrowthMemoryAgent",
    name: "Growth Memory",
    statusText: "Synced",
    statusType: "synced",
    iconColor: "#2563eb",
    iconBg: "#dbeafe",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
        <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
      </svg>
    ),
  },
  {
    key: "PersonalizationAgent",
    name: "Personalization Agent",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#2563eb",
    iconBg: "#dbeafe",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="7" r="4" />
        <path d="M5.5 21a8.5 8.5 0 0 1 13 0" />
      </svg>
    ),
  },
  {
    key: "CampaignStrategistAgent",
    name: "Campaign Strategist",
    statusText: "Working",
    statusType: "working",
    iconColor: "#e05a36",
    iconBg: "#ffebe5",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.5" fill="currentColor" />
      </svg>
    ),
  },
  {
    key: "OpportunityPrioritizationAgent",
    name: "Opportunity Prioritization",
    statusText: "Ready",
    statusType: "ready",
    iconColor: "#d97706",
    iconBg: "#fef3c7",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" />
        <path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" />
        <path d="M4 22h16" />
        <path d="M10 14.66V17c0 .55-.45 1-1 1H8c-.55 0-1 .45-1 1v1h10v-1c0-.55-.45-1-1-1h-1c-.55 0-1-.45-1-1v-2.34" />
        <path d="M6 4h12v6a6 6 0 0 1-12 0V4z" />
      </svg>
    ),
  },
];

interface ManagerRosterProps {
  agentStatusOverrides?: Record<string, string>;
}

export function ManagerRoster({ agentStatusOverrides }: ManagerRosterProps) {
  const navigate = useNavigate();

  const handleCardClick = (agent: AgentCardDef) => {
    if (agent.route) {
      navigate(agent.route);
    } else {
      navigate("/agents");
    }
  };

  return (
    <section className="mgr-roster-section" aria-label="Agent roster">
      <WindowPanel title="agent.roster" className="mgr-roster-panel">
        {/* Header */}
        <div className="mgr-roster__head">
          <div>
            <h2 className="mgr-roster__title">Your connected AI specialists</h2>
            <p className="mgr-roster__desc">
              13 specialized agents, working together under the Manager Agent.
            </p>
          </div>
          <button
            type="button"
            className="mgr-roster__catalogBtn"
            onClick={() => navigate("/agents")}
          >
            <span>View Agent Catalog</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>

        {/* 13 Agent Cards Grid */}
        <div className="mgr-roster__grid">
          {ROSTER_AGENTS.map((agent) => {
            const overrideStatus = agentStatusOverrides?.[agent.key];
            const displayStatus = overrideStatus || agent.statusText;
            const statusType = overrideStatus
              ? overrideStatus.toLowerCase() === "completed"
                ? "active"
                : overrideStatus.toLowerCase() === "running"
                  ? "working"
                  : agent.statusType
              : agent.statusType;

            return (
              <div
                key={agent.key}
                className="mgr-roster-card"
                onClick={() => handleCardClick(agent)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    handleCardClick(agent);
                  }
                }}
              >
                <div
                  className="mgr-roster-card__icon"
                  style={{ background: agent.iconBg, color: agent.iconColor }}
                  aria-hidden="true"
                >
                  {agent.icon}
                </div>
                <div className="mgr-roster-card__main">
                  <span className="mgr-roster-card__name">{agent.name}</span>
                  <div className="mgr-roster-card__badgeRow">
                    <span className={`mgr-badge mgr-badge--${statusType}`}>
                      {statusType === "working" && (
                        <span className="mgr-badge__dot mgr-badge__dot--pulse" aria-hidden="true" />
                      )}
                      {statusType === "guarded" && (
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" style={{ marginRight: 2 }}>
                          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                        </svg>
                      )}
                      {statusType === "synced" && (
                        <span className="mgr-badge__dot" aria-hidden="true" />
                      )}
                      <span>{displayStatus}</span>
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Bottom Banner */}
        <div className="mgr-roster__footerBanner">
          <span className="mgr-roster__plus" aria-hidden="true">+</span>
          <span className="mgr-roster__footerText">
            <strong>All agents are active</strong> — The Manager Agent selects the right specialists for each goal automatically.
          </span>
        </div>
      </WindowPanel>
    </section>
  );
}
