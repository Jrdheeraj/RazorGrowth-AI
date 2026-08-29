import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator, StatusChip } from "../../../components/StatusIndicator";

/**
 * HeroFloatingWindows — exactly three small product windows that belong
 * to the scene. Subtle supporting elements; never competing with the
 * main window. No rotations, no clutter.
 */
export function HeroFloatingWindows() {
  return (
    <>
      {/* Upper right of the main window — agent presence */}
      <aside className="hfloat hfloat--log" aria-label="Agent activity example">
        <WindowPanel title="growth-agent.log" flush>
          <div className="hfloat__body">
            <span className="hfloat__label">
              <StatusIndicator tone="ok" pulse label="online" />
              MARKETING AGENT
            </span>
            <span className="hfloat__copy">campaign opportunity detected</span>
          </div>
        </WindowPanel>
      </aside>

      {/* Right side, below the log window */}
      <aside className="hfloat hfloat--queue" aria-label="Opportunity queue example">
        <WindowPanel title="opportunity.queue" flush>
          <div className="hfloat__body">
            <span className="hfloat__label">OPPORTUNITY FOUND</span>
            <span className="hfloat__copy">Retention gap</span>
            <span style={{ marginTop: 2 }}>
              <StatusChip tone="accent">HIGH CONFIDENCE</StatusChip>
            </span>
          </div>
        </WindowPanel>
      </aside>

      {/* Lower left, resting near the ground band of the artwork */}
      <aside className="hfloat hfloat--approval" aria-label="Pending approval example">
        <WindowPanel title="approval.pending" flush>
          <div className="hfloat__body">
            <span className="hfloat__label">
              <StatusIndicator tone="accent" pulse label="awaiting review" />
              HUMAN APPROVAL
            </span>
            <span className="hfloat__copy">Increase retention campaign</span>
          </div>
        </WindowPanel>
      </aside>
    </>
  );
}
