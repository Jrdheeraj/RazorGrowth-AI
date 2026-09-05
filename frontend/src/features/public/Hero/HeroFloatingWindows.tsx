import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator } from "../../../components/StatusIndicator";
import { Link } from "react-router-dom";

/**
 * HeroFloatingWindows — exactly three small product windows that belong
 * to the scene. Subtle supporting elements; never competing with the
 * main window. No rotations, no clutter.
 */
export function HeroFloatingWindows() {
  return (
    <>
      {/* Upper right of the main window — agent presence */}
      <aside className="hfloat hfloat--log" aria-label="Growth Radar">
        <WindowPanel title="growth-radar.app" flush>
          <div className="hfloat__body">
            <span className="hfloat__label">
              <StatusIndicator tone="ok" pulse label="online" />
              GROWTH RADAR
            </span>
            <span className="hfloat__copy">See what is happening across your business.</span>
            <Link className="btn btn--primary hfloat__link" to="/growth-radar">Open Growth Radar <span aria-hidden="true">→</span></Link>
          </div>
        </WindowPanel>
      </aside>

      {/* Right side, below the log window */}
      <aside className="hfloat hfloat--queue" aria-label="AI Team">
        <WindowPanel title="ai-team.app" flush>
          <div className="hfloat__body">
            <span className="hfloat__label">AI TEAM</span>
            <span className="hfloat__copy">AI employees find and plan your next opportunities.</span>
            <Link className="btn btn--primary hfloat__link" to="/agents">Meet the AI Team <span aria-hidden="true">→</span></Link>
          </div>
        </WindowPanel>
      </aside>

      {/* Lower left, resting near the ground band of the artwork */}
      <aside className="hfloat hfloat--approval" aria-label="Agent Debates">
        <WindowPanel title="debates.app" flush>
          <div className="hfloat__body">
            <span className="hfloat__label">
              <StatusIndicator tone="accent" pulse label="awaiting review" />
              AGENT DEBATES
            </span>
            <span className="hfloat__copy">See what your AI team found and why.</span>
            <Link className="btn btn--primary hfloat__link" to="/debate">View Agent Debates <span aria-hidden="true">→</span></Link>
          </div>
        </WindowPanel>
      </aside>
    </>
  );
}
