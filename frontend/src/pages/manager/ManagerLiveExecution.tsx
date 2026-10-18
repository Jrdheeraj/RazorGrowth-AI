import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../../components/WindowPanel";
import type { ExecutionStepItem, ApprovalQueueItem } from "./types";

interface ManagerLiveExecutionProps {
  steps?: ExecutionStepItem[];
  pendingActions?: ApprovalQueueItem[];
  workflowName?: string;
}

const DEFAULT_STEPS: ExecutionStepItem[] = [
  {
    num: "1",
    step: "Analyze market trends",
    specialist: "Discovery Agent",
    specialistKey: "DiscoveryAgent",
    task: "Research opportunities",
    status: "Completed",
    duration: "2m 14s",
  },
  {
    num: "2",
    step: "Customer segment analysis",
    specialist: "Customer Intelligence",
    specialistKey: "CustomerIntelligenceAgent",
    task: "Identify key segments",
    status: "Completed",
    duration: "3m 32s",
  },
  {
    num: "3",
    step: "Revenue optimization plan",
    specialist: "Revenue Optimization",
    specialistKey: "RevenueOptimizationAgent",
    task: "Find growth opportunities",
    status: "In Progress",
    duration: "1m 20s",
  },
  {
    num: "4",
    step: "Campaign strategy",
    specialist: "Campaign Strategist",
    specialistKey: "CampaignStrategistAgent",
    task: "Create campaign plan",
    status: "Pending",
    duration: "-",
  },
  {
    num: "5",
    step: "Creative assets",
    specialist: "Designer Agent",
    specialistKey: "DesignerAgent",
    task: "Generate visuals",
    status: "Pending",
    duration: "-",
  },
  {
    num: "6",
    step: "A/B test setup",
    specialist: "Experiment Agent",
    specialistKey: "ExperimentAgent",
    task: "Design experiments",
    status: "Pending",
    duration: "-",
  },
];

const DEFAULT_APPROVALS: ApprovalQueueItem[] = [
  {
    id: "act-1",
    actionTitle: "Review campaign budget proposal",
    actionType: "campaign_budget",
    agent: "Campaign Strategist",
    agentKey: "CampaignStrategistAgent",
    createdText: "2 hours ago",
    status: "Pending",
  },
  {
    id: "act-2",
    actionTitle: "Approve payment recovery strategy",
    actionType: "payment_recovery",
    agent: "Payment Recovery",
    agentKey: "PaymentRecoveryAgent",
    createdText: "4 hours ago",
    status: "Pending",
  },
  {
    id: "act-3",
    actionTitle: "Confirm A/B test launch",
    actionType: "experiment_launch",
    agent: "Experiment Agent",
    agentKey: "ExperimentAgent",
    createdText: "6 hours ago",
    status: "In Review",
  },
  {
    id: "act-4",
    actionTitle: "Approve growth opportunity list",
    actionType: "opportunity_ranking",
    agent: "Opportunity Prioritization",
    agentKey: "OpportunityPrioritizationAgent",
    createdText: "1 day ago",
    status: "Pending",
  },
];

export function ManagerLiveExecution({
  steps = DEFAULT_STEPS,
  pendingActions = DEFAULT_APPROVALS,
  workflowName = "Growth Acceleration Plan",
}: ManagerLiveExecutionProps) {
  const navigate = useNavigate();

  return (
    <section className="mgr-split-row" aria-label="Execution plan and approval queue">
      {/* Left Column: Live Execution Plan */}
      <WindowPanel
        title="live.execution"
        className="mgr-table-panel"
      >
        <div id="live-execution-panel" className="mgr-panel-head">
          <div className="mgr-panel-head__titleGroup">
            <span className="mgr-panel-head__playIcon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            </span>
            <div>
              <h2 className="mgr-panel-head__title">Live Execution Plan</h2>
              <span className="mgr-panel-head__sub">
                Current workflow: {workflowName}
              </span>
            </div>
          </div>
          <button
            type="button"
            className="mgr-panel-head__btn"
            onClick={() => navigate("/debate")}
          >
            <span>View Full Plan</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div className="mgr-table-wrap">
          <table className="mgr-table">
            <thead>
              <tr>
                <th style={{ width: "36px" }}>#</th>
                <th>STEP</th>
                <th>SPECIALIST</th>
                <th>TASK</th>
                <th>STATUS</th>
                <th>DURATION</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((row) => (
                <tr key={`${row.num}-${row.step}`}>
                  <td className="mgr-table__colMuted">{row.num}</td>
                  <td className="mgr-table__colBold">{row.step}</td>
                  <td>{row.specialist}</td>
                  <td className="mgr-table__colMuted">{row.task}</td>
                  <td>
                    <span
                      className={`mgr-status-pill mgr-status-pill--${
                        row.status === "Completed"
                          ? "completed"
                          : row.status === "In Progress"
                            ? "progress"
                            : "pending"
                      }`}
                    >
                      {row.status === "Completed" && (
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      )}
                      {row.status === "In Progress" && (
                        <span className="mgr-status-pill__spinner" aria-hidden="true" />
                      )}
                      {row.status === "Pending" && (
                        <span className="mgr-status-pill__circle" aria-hidden="true" />
                      )}
                      <span>{row.status}</span>
                    </span>
                  </td>
                  <td className="mgr-table__colMuted">{row.duration}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </WindowPanel>

      {/* Right Column: Pending Actions Requiring Approval */}
      <WindowPanel
        title="approval.queue"
        className="mgr-table-panel"
      >
        <div id="approval-queue" className="mgr-panel-head">
          <div className="mgr-panel-head__titleGroup">
            <span className="mgr-panel-head__alertIcon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </span>
            <h2 className="mgr-panel-head__title">Pending Actions Requiring Approval</h2>
          </div>
          <button
            type="button"
            className="mgr-panel-head__link"
            onClick={() => navigate("/actions")}
          >
            <span>View All</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>

        <div className="mgr-table-wrap">
          <table className="mgr-table">
            <thead>
              <tr>
                <th>ACTION</th>
                <th>AGENT</th>
                <th>CREATED</th>
                <th>STATUS</th>
                <th style={{ textAlign: "right" }}>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {pendingActions.map((row) => (
                <tr key={row.id}>
                  <td className="mgr-table__colBold">
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span className="mgr-table__actionIcon" aria-hidden="true">
                        {row.actionType.includes("campaign") ? (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#e05a36" strokeWidth="2">
                            <path d="m3 11 18-5v12L3 13v-2z" />
                          </svg>
                        ) : row.actionType.includes("payment") ? (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#9333ea" strokeWidth="2">
                            <rect x="2" y="5" width="20" height="14" rx="2" />
                            <line x1="2" y1="10" x2="22" y2="10" />
                          </svg>
                        ) : row.actionType.includes("experiment") ? (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#2563eb" strokeWidth="2">
                            <path d="M10 2v7.5L4.7 20.5a1 1 0 0 0 .9 1.5h12.8a1 1 0 0 0 .9-1.5L14 9.5V2" />
                          </svg>
                        ) : (
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2">
                            <circle cx="12" cy="12" r="9" />
                          </svg>
                        )}
                      </span>
                      <span>{row.actionTitle}</span>
                    </div>
                  </td>
                  <td>{row.agent}</td>
                  <td className="mgr-table__colMuted">{row.createdText}</td>
                  <td>
                    <span
                      className={`mgr-status-pill mgr-status-pill--${
                        row.status === "Approved"
                          ? "completed"
                          : row.status === "In Review"
                            ? "progress"
                            : "amber"
                      }`}
                    >
                      <span className="mgr-status-pill__circle" aria-hidden="true" />
                      <span>{row.status}</span>
                    </span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <button
                      type="button"
                      className="mgr-table__reviewBtn"
                      onClick={() => navigate("/actions")}
                    >
                      Review
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </WindowPanel>
    </section>
  );
}
