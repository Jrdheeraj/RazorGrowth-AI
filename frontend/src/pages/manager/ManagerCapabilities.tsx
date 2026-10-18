import { useState } from "react";
import { WindowPanel } from "../../components/WindowPanel";

interface CapabilityItem {
  id: string;
  title: string;
  desc: string;
  iconBg: string;
  iconColor: string;
  icon: React.ReactNode;
}

const CAPABILITIES: CapabilityItem[] = [
  {
    id: "goal_understanding",
    title: "Goal Understanding",
    desc: "Analyzes merchant goals, context, constraints and success criteria.",
    iconBg: "#fee2e2",
    iconColor: "#dc2626",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.5" fill="currentColor" />
      </svg>
    ),
  },
  {
    id: "intelligent_delegation",
    title: "Intelligent Delegation",
    desc: "Selects the right agents based on capabilities, data and dependencies.",
    iconBg: "#f3e8ff",
    iconColor: "#9333ea",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    ),
  },
  {
    id: "plan_prioritize",
    title: "Plan & Prioritize",
    desc: "Creates structured, validated plans with clear tasks and outcomes.",
    iconBg: "#ffedd5",
    iconColor: "#ea580c",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="8" y1="6" x2="21" y2="6" />
        <line x1="8" y1="12" x2="21" y2="12" />
        <line x1="8" y1="18" x2="21" y2="18" />
        <line x1="3" y1="6" x2="3.01" y2="6" />
        <line x1="3" y1="12" x2="3.01" y2="12" />
        <line x1="3" y1="18" x2="3.01" y2="18" />
      </svg>
    ),
  },
  {
    id: "safety_approval",
    title: "Safety & Approval",
    desc: "Enforces permissions, guardrails and human approval for sensitive actions.",
    iconBg: "#dcfce7",
    iconColor: "#16a34a",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <polyline points="9 12 11 14 15 10" />
      </svg>
    ),
  },
  {
    id: "result_evaluation",
    title: "Result Evaluation",
    desc: "Reviews agent outputs, verifies evidence and measures progress.",
    iconBg: "#ccfbf1",
    iconColor: "#0d9488",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
  },
  {
    id: "adaptive_replanning",
    title: "Adaptive Replanning",
    desc: "Handles failures, retries and adjusts plans to keep work on track.",
    iconBg: "#ffebe5",
    iconColor: "#e05a36",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="1 4 1 10 7 10" />
        <polyline points="23 20 23 14 17 14" />
        <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" />
      </svg>
    ),
  },
];

export function ManagerCapabilities() {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="mgr-capabilities-section" id="manager-capabilities" aria-label="Manager capabilities">
      <WindowPanel title="manager.capabilities" className="mgr-cap-panel">
        {/* Header */}
        <div className="mgr-cap__head">
          <h2 className="mgr-cap__title">How the Manager Agent leads your growth team</h2>
          <button
            type="button"
            className="mgr-cap__learnMore"
            onClick={() => setExpanded(!expanded)}
          >
            <span>{expanded ? "Show less" : "Learn more"}</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>

        {/* 6 Cards Grid */}
        <div className="mgr-cap__grid">
          {CAPABILITIES.map((cap) => (
            <div key={cap.id} className="mgr-cap-card">
              <div
                className="mgr-cap-card__icon"
                style={{ background: cap.iconBg, color: cap.iconColor }}
                aria-hidden="true"
              >
                {cap.icon}
              </div>

              <div className="mgr-cap-card__body">
                <div className="mgr-cap-card__top">
                  <h3 className="mgr-cap-card__title">{cap.title}</h3>
                  <span className="mgr-cap-card__arrow" aria-hidden="true">→</span>
                </div>
                <p className="mgr-cap-card__desc">{cap.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {expanded && (
          <div className="mgr-cap__expandedNotes">
            <p>
              The Manager Agent operates with strict deterministic guardrails. All sensitive merchant actions
              (e.g., budget adjustments, live customer campaigns, payment capture rules) require human authorization
              in the Actions console before any live execution is dispatched.
            </p>
          </div>
        )}
      </WindowPanel>
    </section>
  );
}
