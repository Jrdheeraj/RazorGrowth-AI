import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../../components/WindowPanel";

interface ManagerWorkspaceAndMetricsProps {
  agentsCount?: number;
  completedTasksCount?: number;
  awaitingApprovalCount?: number;
  activeWorkflowsCount?: number;
  onViewLivePlan?: () => void;
  onReviewActions?: () => void;
}

export function ManagerWorkspaceAndMetrics({
  agentsCount = 13,
  completedTasksCount = 28,
  awaitingApprovalCount = 6,
  activeWorkflowsCount = 4,
  onViewLivePlan,
  onReviewActions,
}: ManagerWorkspaceAndMetricsProps) {
  const navigate = useNavigate();

  const handleLivePlan = () => {
    if (onViewLivePlan) {
      onViewLivePlan();
      return;
    }
    const el = document.getElementById("live-execution-panel");
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  const handleReviewActions = () => {
    if (onReviewActions) {
      onReviewActions();
      return;
    }
    navigate("/actions");
  };

  return (
    <section className="mgr-workspace-metrics" aria-label="Growth workspace and key metrics">
      {/* Left Panel: Growth Workspace */}
      <WindowPanel title="growth.workspace" className="mgr-workspace-panel">
        <div className="mgr-ws__topBar">
          <div className="mgr-ws__eyebrow">
            <span className="mgr-ws__sparkleIcon" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                <path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z" />
              </svg>
            </span>
            <span>YOUR GROWTH WORKSPACE</span>
          </div>
          <span className="mgr-ws__coordinationBadge">
            <span className="mgr-ws__dot" aria-hidden="true" />
            <span>COORDINATION ACTIVE</span>
          </span>
        </div>

        <div className="mgr-ws__main">
          <div className="mgr-ws__content">
            <h2 className="mgr-ws__title">Your AI team is working together.</h2>
            <p className="mgr-ws__desc">
              The Manager Agent is coordinating the right specialists, tracking progress,
              and ensuring safe, measurable execution for your business.
            </p>

            {/* 4-Step Process Flow with Icons and Arrows */}
            <div className="mgr-ws__steps">
              <div className="mgr-ws__step">
                <div className="mgr-ws__stepIcon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="9" />
                    <circle cx="12" cy="12" r="5" />
                    <circle cx="12" cy="12" r="1.5" fill="currentColor" />
                  </svg>
                </div>
                <div className="mgr-ws__stepText">
                  <strong>Understand</strong>
                  <span>Your Goal</span>
                </div>
              </div>

              <span className="mgr-ws__stepArrow" aria-hidden="true">→</span>

              <div className="mgr-ws__step">
                <div className="mgr-ws__stepIcon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                    <circle cx="9" cy="7" r="4" />
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                    <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                  </svg>
                </div>
                <div className="mgr-ws__stepText">
                  <strong>Delegate</strong>
                  <span>To Specialists</span>
                </div>
              </div>

              <span className="mgr-ws__stepArrow" aria-hidden="true">→</span>

              <div className="mgr-ws__step">
                <div className="mgr-ws__stepIcon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                    <polyline points="9 12 11 14 15 10" />
                  </svg>
                </div>
                <div className="mgr-ws__stepText">
                  <strong>Validate</strong>
                  <span>Results & Safety</span>
                </div>
              </div>

              <span className="mgr-ws__stepArrow" aria-hidden="true">→</span>

              <div className="mgr-ws__step">
                <div className="mgr-ws__stepIcon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="20" x2="18" y2="10" />
                    <line x1="12" y1="20" x2="12" y2="4" />
                    <line x1="6" y1="20" x2="6" y2="14" />
                  </svg>
                </div>
                <div className="mgr-ws__stepText">
                  <strong>Deliver</strong>
                  <span>Measurable Growth</span>
                </div>
              </div>
            </div>

            {/* Action buttons */}
            <div className="mgr-ws__actions">
              <button
                type="button"
                className="mgr-ws__btnPrimary"
                onClick={handleLivePlan}
              >
                <span>View Live Plan</span>
                <span aria-hidden="true">→</span>
              </button>
              <button
                type="button"
                className="mgr-ws__btnSecondary"
                onClick={handleReviewActions}
              >
                Review Pending Actions
              </button>
            </div>
          </div>

          {/* Right illustration: Clipboard with charts and succulent plant */}
          <div className="mgr-ws__art" aria-hidden="true">
            <svg viewBox="0 0 160 140" width="150" height="130" fill="none">
              {/* Clipboard paper */}
              <rect x="25" y="20" width="85" height="105" rx="6" fill="#fff9f0" stroke="#2c1710" strokeWidth="2" />
              <rect x="45" y="12" width="45" height="16" rx="4" fill="#d97757" stroke="#2c1710" strokeWidth="2" />
              <circle cx="67.5" cy="18" r="3" fill="#fff9f0" stroke="#2c1710" strokeWidth="1.5" />

              {/* Chart on clipboard */}
              <line x1="38" y1="95" x2="95" y2="95" stroke="#2c1710" strokeWidth="1.5" />
              <rect x="42" y="70" width="8" height="25" fill="#f87171" rx="1.5" />
              <rect x="54" y="55" width="8" height="40" fill="#fb923c" rx="1.5" />
              <rect x="66" y="42" width="8" height="53" fill="#e05a36" rx="1.5" />
              <rect x="78" y="32" width="8" height="63" fill="#34d399" rx="1.5" />
              {/* Trend line */}
              <polyline points="46 65 58 50 70 38 82 28" stroke="#059669" strokeWidth="2" strokeLinecap="round" />

              {/* Little pencil */}
              <g transform="rotate(35 105 50)">
                <rect x="100" y="30" width="6" height="45" fill="#fbbf24" stroke="#2c1710" strokeWidth="1.2" />
                <polygon points="100,75 106,75 103,82" fill="#e5e7eb" stroke="#2c1710" strokeWidth="1.2" />
                <polygon points="102,80 104,80 103,82" fill="#2c1710" />
              </g>

              {/* Potted succulent plant */}
              <rect x="105" y="90" width="30" height="26" rx="3" fill="#d97757" stroke="#2c1710" strokeWidth="2" />
              {/* Plant leaves */}
              <ellipse cx="120" cy="80" rx="9" ry="14" fill="#10b981" stroke="#2c1710" strokeWidth="1.5" />
              <ellipse cx="112" cy="84" rx="7" ry="12" fill="#34d399" stroke="#2c1710" strokeWidth="1.5" transform="rotate(-25 112 84)" />
              <ellipse cx="128" cy="84" rx="7" ry="12" fill="#34d399" stroke="#2c1710" strokeWidth="1.5" transform="rotate(25 128 84)" />
              <ellipse cx="120" cy="74" rx="5" ry="9" fill="#6ee7b7" stroke="#2c1710" strokeWidth="1.5" />
            </svg>
          </div>
        </div>
      </WindowPanel>

      {/* Right Panel: Key Metrics */}
      <WindowPanel title="key.metrics" className="mgr-metrics-panel">
        <div className="mgr-metrics-grid">
          {/* Card 1: Agents Coordinated */}
          <div className="mgr-metric-card">
            <div className="mgr-metric-card__top">
              <div className="mgr-metric-card__icon mgr-metric-card__icon--coral">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                  <circle cx="9" cy="7" r="4" />
                  <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                  <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                </svg>
              </div>
              {/* Mini vertical bar chart */}
              <div className="mgr-metric-chart" aria-hidden="true">
                <span style={{ height: "40%", background: "#f87171" }} />
                <span style={{ height: "65%", background: "#fb923c" }} />
                <span style={{ height: "80%", background: "#f87171" }} />
                <span style={{ height: "100%", background: "#e05a36" }} />
              </div>
            </div>
            <div className="mgr-metric-card__body">
              <span className="mgr-metric-card__value">{agentsCount}</span>
              <span className="mgr-metric-card__label">Agents Coordinated</span>
              <span className="mgr-metric-card__trend mgr-metric-card__trend--green">
                ↑ +2 this month
              </span>
            </div>
          </div>

          {/* Card 2: Tasks Completed */}
          <div className="mgr-metric-card">
            <div className="mgr-metric-card__top">
              <div className="mgr-metric-card__icon mgr-metric-card__icon--green">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
              {/* Mini vertical bar chart */}
              <div className="mgr-metric-chart" aria-hidden="true">
                <span style={{ height: "35%", background: "#86efac" }} />
                <span style={{ height: "55%", background: "#4ade80" }} />
                <span style={{ height: "75%", background: "#22c55e" }} />
                <span style={{ height: "100%", background: "#16a34a" }} />
              </div>
            </div>
            <div className="mgr-metric-card__body">
              <span className="mgr-metric-card__value">{completedTasksCount}</span>
              <span className="mgr-metric-card__label">Tasks Completed</span>
              <span className="mgr-metric-card__trend mgr-metric-card__trend--green">
                ↑ +18% this month
              </span>
            </div>
          </div>

          {/* Card 3: Awaiting Approval */}
          <div className="mgr-metric-card">
            <div className="mgr-metric-card__top">
              <div className="mgr-metric-card__icon mgr-metric-card__icon--amber">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
              </div>
              {/* Mini vertical bar chart */}
              <div className="mgr-metric-chart" aria-hidden="true">
                <span style={{ height: "50%", background: "#fde68a" }} />
                <span style={{ height: "80%", background: "#fcd34d" }} />
                <span style={{ height: "60%", background: "#fbbf24" }} />
                <span style={{ height: "100%", background: "#d97706" }} />
              </div>
            </div>
            <div className="mgr-metric-card__body">
              <span className="mgr-metric-card__value">{awaitingApprovalCount}</span>
              <span className="mgr-metric-card__label">Awaiting Approval</span>
              <span className="mgr-metric-card__trend mgr-metric-card__trend--amber">
                0 executed automatically
              </span>
            </div>
          </div>

          {/* Card 4: Active Workflows */}
          <div className="mgr-metric-card">
            <div className="mgr-metric-card__top">
              <div className="mgr-metric-card__icon mgr-metric-card__icon--purple">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polygon points="5 3 19 12 5 21 5 3" />
                </svg>
              </div>
              {/* Mini vertical bar chart */}
              <div className="mgr-metric-chart" aria-hidden="true">
                <span style={{ height: "45%", background: "#d8b4fe" }} />
                <span style={{ height: "70%", background: "#c084fc" }} />
                <span style={{ height: "60%", background: "#a855f7" }} />
                <span style={{ height: "100%", background: "#9333ea" }} />
              </div>
            </div>
            <div className="mgr-metric-card__body">
              <span className="mgr-metric-card__value">{activeWorkflowsCount}</span>
              <span className="mgr-metric-card__label">Active Workflows</span>
              <span className="mgr-metric-card__trend mgr-metric-card__trend--green">
                ↑ +1 this month
              </span>
            </div>
          </div>
        </div>
      </WindowPanel>
    </section>
  );
}
