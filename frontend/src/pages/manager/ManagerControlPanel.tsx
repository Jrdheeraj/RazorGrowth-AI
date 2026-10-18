import { useState } from "react";
import { WindowPanel } from "../../components/WindowPanel";
import { scrollToSection } from "../../lib/scroll";

interface ManagerControlPanelProps {
  onCreatePlan: (goal: string) => Promise<void>;
  isCreating: boolean;
  statusMessage?: string | null;
}

const SUGGESTED_GOALS = [
  "Increase conversion",
  "Recover failed payments",
  "Launch campaign",
  "Improve retention",
];

export function ManagerControlPanel({
  onCreatePlan,
  isCreating,
  statusMessage,
}: ManagerControlPanelProps) {
  const [goal, setGoal] = useState("");

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
    <WindowPanel title="manager.control" className="manager-control-panel">
      {/* Header with identity and status */}
      <div className="mgr-ctrl__head">
        <div className="mgr-ctrl__brand">
          <div className="mgr-ctrl__icon" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2c.7 5.5 4.5 9.3 10 10-5.5.7-9.3 4.5-10 10-.7-5.5-4.5-9.3-10-10 5.5-.7 9.3-4.5 10-10z" />
            </svg>
          </div>
          <div>
            <div className="mgr-ctrl__titleRow">
              <h3 className="mgr-ctrl__title">Manager Agent</h3>
              <span className="mgr-ctrl__statusBadge">Active</span>
            </div>
          </div>
        </div>
        <button
          type="button"
          className="mgr-ctrl__helpBtn"
          onClick={handleHowItWorks}
          aria-label="How it works"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          <span>How it works</span>
        </button>
      </div>

      <p className="mgr-ctrl__desc">
        Coordinate all 13 AI agents, create intelligent plans, and drive measurable business growth.
      </p>

      {/* Goal input form */}
      <form onSubmit={handleSubmit} className="mgr-ctrl__form">
        <div className="mgr-ctrl__inputWrapper">
          <input
            type="text"
            className="mgr-ctrl__input"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="What growth goal should we coordinate?"
            aria-label="Growth goal input"
            disabled={isCreating}
          />
          <span className="mgr-ctrl__inputIcon" aria-hidden="true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </span>
        </div>

        <button
          type="submit"
          className="mgr-ctrl__submitBtn"
          disabled={isCreating}
        >
          <span>{isCreating ? "Creating Growth Plan…" : "Create Growth Plan"}</span>
          <span className="mgr-ctrl__btnArrow" aria-hidden="true">→</span>
        </button>

        {statusMessage && (
          <p className="mgr-ctrl__statusMsg" role="status">
            {statusMessage}
          </p>
        )}
      </form>

      {/* Suggested Goal Chips */}
      <div className="mgr-ctrl__chipsSection">
        <span className="mgr-ctrl__chipsLabel">Try these goals:</span>
        <div className="mgr-ctrl__chips">
          {SUGGESTED_GOALS.map((item) => (
            <button
              key={item}
              type="button"
              className="mgr-ctrl__chip"
              onClick={() => handleSelectGoal(item)}
              disabled={isCreating}
            >
              {item}
            </button>
          ))}
        </div>
      </div>
    </WindowPanel>
  );
}
