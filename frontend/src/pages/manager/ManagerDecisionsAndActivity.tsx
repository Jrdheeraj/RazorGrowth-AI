import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../../components/WindowPanel";
import type { ManagerDecisionItem, TeamActivityItem } from "./types";

interface ManagerDecisionsAndActivityProps {
  decisions?: ManagerDecisionItem[];
  activities?: TeamActivityItem[];
}

const DEFAULT_DECISIONS: ManagerDecisionItem[] = [
  {
    id: "dec-1",
    decision: "Selected 5 agents for growth plan",
    details: "Based on goal: Increase conversion by 20% | Evidence: market trends + customer segments.",
    time: "2h ago",
    type: "success",
  },
  {
    id: "dec-2",
    decision: "Adjusted plan due to API limit",
    details: "Switched to alternative data source for market research",
    time: "5h ago",
    type: "info",
  },
  {
    id: "dec-3",
    decision: "Deferred campaign launch",
    details: "Awaiting budget approval from merchant",
    time: "1d ago",
    type: "warning",
  },
  {
    id: "dec-4",
    decision: "Added experiment agent",
    details: "Included A/B testing for pricing strategy based on analysis",
    time: "1d ago",
    type: "success",
  },
];

const DEFAULT_ACTIVITIES: TeamActivityItem[] = [
  {
    id: "act-1",
    time: "2m ago",
    agent: "Discovery",
    agentKey: "DiscoveryAgent",
    activity: "Completed market research analysis",
  },
  {
    id: "act-2",
    time: "8m ago",
    agent: "Customer Intelligence",
    agentKey: "CustomerIntelligenceAgent",
    activity: "Identified 3 key customer segments",
  },
  {
    id: "act-3",
    time: "12m ago",
    agent: "Revenue Optimization",
    agentKey: "RevenueOptimizationAgent",
    activity: "Found 5 revenue opportunities",
  },
  {
    id: "act-4",
    time: "18m ago",
    agent: "Manager Agent",
    agentKey: "ManagerAgent",
    activity: "Updated execution plan",
  },
  {
    id: "act-5",
    time: "25m ago",
    agent: "Campaign Strategist",
    agentKey: "CampaignStrategistAgent",
    activity: "Started campaign strategy analysis",
  },
];

export function ManagerDecisionsAndActivity({
  decisions = DEFAULT_DECISIONS,
  activities = DEFAULT_ACTIVITIES,
}: ManagerDecisionsAndActivityProps) {
  const navigate = useNavigate();

  return (
    <section className="mgr-split-row" aria-label="Recent decisions and team activity">
      {/* Left Column: Recent Manager Decisions */}
      <WindowPanel
        title="recent.decisions"
        className="mgr-table-panel"
      >
        <div className="mgr-panel-head">
          <div className="mgr-panel-head__titleGroup">
            <span className="mgr-panel-head__docIcon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
                <polyline points="10 9 9 9 8 9" />
              </svg>
            </span>
            <h2 className="mgr-panel-head__title">Recent Manager Decisions</h2>
          </div>
          <button
            type="button"
            className="mgr-panel-head__link"
            onClick={() => navigate("/debate")}
          >
            <span>View All</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div className="mgr-table-wrap">
          <table className="mgr-table">
            <thead>
              <tr>
                <th>DECISION</th>
                <th>DETAILS / EVIDENCE</th>
                <th style={{ width: "80px", textAlign: "right" }}>TIME</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((row) => (
                <tr key={row.id}>
                  <td className="mgr-table__colBold">
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span
                        className={`mgr-decision-icon mgr-decision-icon--${row.type}`}
                        aria-hidden="true"
                      >
                        {row.type === "success" && (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                            <polyline points="20 6 9 17 4 12" />
                          </svg>
                        )}
                        {row.type === "info" && (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <circle cx="12" cy="12" r="10" />
                            <line x1="12" y1="16" x2="12" y2="12" />
                            <line x1="12" y1="8" x2="12.01" y2="8" />
                          </svg>
                        )}
                        {row.type === "warning" && (
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <circle cx="12" cy="12" r="10" />
                            <polyline points="12 6 12 12 16 14" />
                          </svg>
                        )}
                      </span>
                      <span>{row.decision}</span>
                    </div>
                  </td>
                  <td className="mgr-table__colMuted">{row.details}</td>
                  <td className="mgr-table__colMuted" style={{ textAlign: "right" }}>
                    {row.time}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </WindowPanel>

      {/* Right Column: Recent Team Activity */}
      <WindowPanel
        title="team.activity"
        className="mgr-table-panel"
      >
        <div className="mgr-panel-head">
          <div className="mgr-panel-head__titleGroup">
            <span className="mgr-panel-head__usersIcon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
            </span>
            <h2 className="mgr-panel-head__title">Recent Team Activity</h2>
          </div>
          <button
            type="button"
            className="mgr-panel-head__link"
            onClick={() => navigate("/agents")}
          >
            <span>View All</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div className="mgr-table-wrap">
          <table className="mgr-table">
            <thead>
              <tr>
                <th style={{ width: "80px" }}>TIME</th>
                <th>AGENT</th>
                <th>ACTIVITY</th>
              </tr>
            </thead>
            <tbody>
              {activities.map((row) => (
                <tr key={row.id}>
                  <td className="mgr-table__colMuted">{row.time}</td>
                  <td className="mgr-table__colBold">
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="mgr-activity-badge-dot" aria-hidden="true" />
                      <span>{row.agent}</span>
                    </div>
                  </td>
                  <td className="mgr-table__colMuted">{row.activity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </WindowPanel>
    </section>
  );
}
