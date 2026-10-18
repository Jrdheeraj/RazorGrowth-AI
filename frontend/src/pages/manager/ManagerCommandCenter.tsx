import { useState, useEffect } from "react";
import { scrollToSection } from "../../lib/scroll";

interface ManagerCommandCenterProps {
  onCreatePlan: (goal: string) => Promise<void>;
  isCreating: boolean;
  statusMessage?: string | null;
  agentStatusOverrides?: Record<string, string>;
  prefilledGoal?: string;
}

interface SpecialistTaskPreview {
  id: string;
  specialistKey: string;
  name: string;
  task: string;
  defaultStatus: "Ready" | "Working" | "Completed" | "Awaiting Approval";
  accentColor: string;
  accentBg: string;
  icon: React.ReactNode;
}

const SPECIALIST_PREVIEWS: SpecialistTaskPreview[] = [
  {
    id: "discovery",
    specialistKey: "DiscoveryAgent",
    name: "Discovery Agent",
    task: "Researching catalog & merchant growth opportunities",
    defaultStatus: "Ready",
    accentColor: "#00897b",
    accentBg: "#e0f2f1",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" fill="currentColor" fillOpacity="0.25" />
      </svg>
    ),
  },
  {
    id: "marketing",
    specialistKey: "MarketingAgent",
    name: "Marketing Agent",
    task: "Preparing campaign strategy & audience cohorts",
    defaultStatus: "Working",
    accentColor: "#e05a36",
    accentBg: "#ffebe5",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="m3 11 18-5v12L3 13v-2z" />
        <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
      </svg>
    ),
  },
  {
    id: "software",
    specialistKey: "SoftwareAgent",
    name: "Software Agent",
    task: "Reviewing technical & checkout constraints",
    defaultStatus: "Ready",
    accentColor: "#0d9488",
    accentBg: "#ccfbf1",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    ),
  },
  {
    id: "revenue",
    specialistKey: "RevenueOptimizationAgent",
    name: "Revenue Optimization",
    task: "Evaluating margin, recovery & pricing opportunities",
    defaultStatus: "Ready",
    accentColor: "#16a34a",
    accentBg: "#dcfce7",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
  },
  {
    id: "experiment",
    specialistKey: "ExperimentAgent",
    name: "Experiment Agent",
    task: "Preparing statistical measurement & test guardrails",
    defaultStatus: "Ready",
    accentColor: "#2563eb",
    accentBg: "#dbeafe",
    icon: (
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M10 2v7.527a2 2 0 0 1-.211.896L4.72 20.55a1 1 0 0 0 .9 1.45h12.76a1 1 0 0 0 .9-1.45l-5.069-10.127A2 2 0 0 1 14 9.527V2" />
        <line x1="8.5" y1="2" x2="15.5" y2="2" />
      </svg>
    ),
  },
];

const SUGGESTED_GOALS = [
  "Increase conversion",
  "Recover failed payments",
  "Launch campaign",
  "Improve retention",
];

export function ManagerCommandCenter({
  onCreatePlan,
  isCreating,
  statusMessage,
  agentStatusOverrides,
  prefilledGoal,
}: ManagerCommandCenterProps) {
  const [goal, setGoal] = useState("");

  useEffect(() => {
    if (prefilledGoal && prefilledGoal.trim().length > 0) {
      setGoal(prefilledGoal);
    }
  }, [prefilledGoal]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const targetGoal = goal.trim() || "Comprehensive commerce analysis and growth optimization";
    onCreatePlan(targetGoal);
  };

  const handleSelectGoal = (suggested: string) => {
    setGoal(suggested);
  };

  const handleHowItWorks = () => {
    const el = document.getElementById("manager-capabilities");
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    } else {
      scrollToSection("how-it-works");
    }
  };

  return (
    <div className="mgr-cmd-panel" aria-label="Manager Agent AI Command Center">
      {/* 1. Window Title Bar */}
      <div className="mgr-cmd__titleBar">
        <div className="mgr-cmd__windowPips" aria-hidden="true">
          <span className="mgr-cmd__pip mgr-cmd__pip--coral" />
          <span className="mgr-cmd__pip mgr-cmd__pip--amber" />
          <span className="mgr-cmd__pip mgr-cmd__pip--green" />
          <span className="mgr-cmd__windowTitle">manager.control // autonomous_orchestrator</span>
        </div>
        <div className="mgr-cmd__statusBadge" title="Autonomous orchestration active">
          <span className="mgr-cmd__pulseDot" aria-hidden="true" />
          <span>ORCHESTRATING</span>
        </div>
      </div>

      {/* 2. Identity Block */}
      <div className="mgr-cmd__identity">
        <div className="mgr-cmd__identityLeft">
          <div className="mgr-cmd__nexusIcon" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="12 2 22 12 12 22 2 12" />
              <circle cx="12" cy="12" r="3" fill="currentColor" />
            </svg>
          </div>
          <div>
            <div className="mgr-cmd__agentNameRow">
              <h2 className="mgr-cmd__agentName">Manager Agent</h2>
              <span className="mgr-cmd__tag">Autonomous Coordinator</span>
            </div>
            <p className="mgr-cmd__identityMeta">
              13 Specialists Standing By · Real-Time Orchestration
            </p>
          </div>
        </div>

        <button
          type="button"
          className="mgr-cmd__helpLink"
          onClick={handleHowItWorks}
          aria-label="How coordination works"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          <span>How it works</span>
        </button>
      </div>

      {/* 3. Execution Pipeline Progress Bar */}
      <div className="mgr-cmd__progressStrip">
        <div className="mgr-cmd__progressInfo">
          <span className="mgr-cmd__progressLabel">ORCHESTRATION PIPELINE</span>
          <span className="mgr-cmd__progressStatus">4 Stages Ready</span>
        </div>
        <div className="mgr-cmd__progressTrack" aria-hidden="true">
          <div className="mgr-cmd__progressSegment is-complete">
            <span className="mgr-cmd__segNum">01</span>
            <span className="mgr-cmd__segText">Understand</span>
          </div>
          <div className="mgr-cmd__progressSegment is-active">
            <span className="mgr-cmd__segNum">02</span>
            <span className="mgr-cmd__segText">Delegate</span>
          </div>
          <div className="mgr-cmd__progressSegment">
            <span className="mgr-cmd__segNum">03</span>
            <span className="mgr-cmd__segText">Validate</span>
          </div>
          <div className="mgr-cmd__progressSegment">
            <span className="mgr-cmd__segNum">04</span>
            <span className="mgr-cmd__segText">Deliver</span>
          </div>
        </div>
      </div>

      {/* 4. Specialist Task Dispatch Queue (5 structured rows) */}
      <div className="mgr-cmd__queue">
        <div className="mgr-cmd__queueHead">
          <span className="mgr-cmd__queueTitle">Specialist Dispatch Queue</span>
          <span className="mgr-cmd__queueMeta">Active Team Preview</span>
        </div>

        <div className="mgr-cmd__specialistList" role="list">
          {SPECIALIST_PREVIEWS.map((spec) => {
            const liveStatus = agentStatusOverrides?.[spec.specialistKey] || spec.defaultStatus;
            const isWorking = liveStatus === "Working";
            const isCompleted = liveStatus === "Completed";

            return (
              <div key={spec.id} className="mgr-cmd__specRow" role="listitem">
                <div
                  className="mgr-cmd__specIcon"
                  style={{ color: spec.accentColor, backgroundColor: spec.accentBg }}
                  aria-hidden="true"
                >
                  {spec.icon}
                </div>

                <div className="mgr-cmd__specInfo">
                  <div className="mgr-cmd__specName">{spec.name}</div>
                  <div className="mgr-cmd__specTask">{spec.task}</div>
                </div>

                <div className="mgr-cmd__specBadgeWrap">
                  <span
                    className={`mgr-cmd__specBadge ${
                      isWorking
                        ? "mgr-cmd__specBadge--working"
                        : isCompleted
                        ? "mgr-cmd__specBadge--completed"
                        : "mgr-cmd__specBadge--ready"
                    }`}
                  >
                    {liveStatus}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 5. Interactive Goal Dispatch Area */}
      <div className="mgr-cmd__dispatch">
        <div className="mgr-cmd__dispatchHead">
          <span className="mgr-cmd__dispatchLabel">Dispatch Growth Goal</span>
          <span className="mgr-cmd__dispatchHint">Coordinates all specialists</span>
        </div>

        <form onSubmit={handleSubmit} className="mgr-cmd__form">
          <div className="mgr-cmd__inputWrap">
            <span className="mgr-cmd__inputIcon" aria-hidden="true">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            </span>
            <input
              type="text"
              className="mgr-cmd__input"
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              placeholder="What growth goal should we coordinate?"
              aria-label="Growth goal input"
              disabled={isCreating}
            />
          </div>

          <button
            type="submit"
            className="mgr-cmd__submitBtn"
            disabled={isCreating}
          >
            <span>{isCreating ? "Coordinating…" : "Create Growth Plan"}</span>
            <span className="mgr-cmd__btnArrow" aria-hidden="true">→</span>
          </button>
        </form>

        {statusMessage && (
          <div className="mgr-cmd__statusMsg" role="status">
            <span className="mgr-cmd__statusDot" aria-hidden="true" />
            <span>{statusMessage}</span>
          </div>
        )}

        {/* Suggested Quick Goal Chips */}
        <div className="mgr-cmd__chipsRow">
          <span className="mgr-cmd__chipsLabel">Quick goals:</span>
          <div className="mgr-cmd__chips">
            {SUGGESTED_GOALS.map((suggested) => (
              <button
                key={suggested}
                type="button"
                className="mgr-cmd__chip"
                onClick={() => handleSelectGoal(suggested)}
                disabled={isCreating}
              >
                {suggested}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
