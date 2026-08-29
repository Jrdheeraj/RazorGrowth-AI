import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip } from "../../../components/StatusIndicator";

/** #product — embedded product-UI teaser windows (full showcase later). */
export function ProductShowcase() {
  return (
    <section id="product" className="shell section" aria-labelledby="product-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">PRODUCT · EMBEDDED UI</p>
        <h2 id="product-heading" className="display-lg" style={{ marginTop: 10 }}>
          The workspace, in its own words.
        </h2>
      </div>

      <div
        style={{
          display: "grid",
          gap: 18,
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          marginTop: 26,
        }}
      >
        <WindowPanel title="growth-radar.app" tone="navy" flush>
          <div style={{ padding: 20 }}>
            <StatusChip tone="ok" pulse>AGENT ONLINE</StatusChip>
            <h3 style={{ marginTop: 14, fontSize: "var(--text-display-md)" }}>
              Signals before hunches.
            </h3>
            <p style={{ color: "var(--ink-soft)", marginTop: 8, fontSize: "var(--text-small)" }}>
              Agents watch revenue, churn and payment health continuously.
            </p>
          </div>
        </WindowPanel>

        <WindowPanel title="plan.md" flush>
          <div style={{ padding: 20 }}>
            <StatusChip tone="accent">APPROVAL REQUIRED</StatusChip>
            <h3 style={{ marginTop: 14, fontSize: "var(--text-display-md)" }}>
              Nothing moves without you.
            </h3>
            <p style={{ color: "var(--ink-soft)", marginTop: 8, fontSize: "var(--text-small)" }}>
              Every proposed action shows why, impact and guardrails first.
            </p>
          </div>
        </WindowPanel>

        <WindowPanel title="agent-run.log" flush>
          <div style={{ padding: 20 }}>
            <StatusChip>REPLAYABLE</StatusChip>
            <h3 style={{ marginTop: 14, fontSize: "var(--text-display-md)" }}>
              Every run leaves a trail.
            </h3>
            <p style={{ color: "var(--ink-soft)", marginTop: 8, fontSize: "var(--text-small)" }}>
              Full audit history for who approved what, and when.
            </p>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
