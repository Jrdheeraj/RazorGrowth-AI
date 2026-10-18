import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator, StatusChip } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./ProductShowcase.css";

export function ProductShowcase() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="product" className="shell section" aria-labelledby="product-heading">
      <SectionWindowHeader
        id="product-heading"
        eyebrow="PRODUCT WORKSPACE · LIVE CAPABILITIES"
        title="See the work behind"
        accentTitle="every recommendation."
        description="Every opportunity surfaced by RazorGrowth AI is backed by verified business data, multi-agent reasoning, and transparent guardrails before it ever reaches your approval queue."
        windowTitle="razorgrowth — product_showcase.app"
      />

      <div ref={reveal} className="reveal">
        <div className="showcase-grid">
          {/* Panel 1: Growth Radar */}
          <div className="showcase-card">
            <WindowPanel title="growth-radar.app" flush>
              <div className="showcase-content">
                <div className="showcase-topline">
                  <StatusChip tone="ok" pulse>CONTINUOUS TELEMETRY</StatusChip>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.70rem", color: "var(--ink-faint)" }}>
                    LIVE DATA
                  </span>
                </div>
                <h3 className="showcase-title">Growth Radar</h3>
                <p className="showcase-desc">
                  Monitors revenue velocity, abandoned checkout patterns, customer segment shifts, and gateway leakages across your merchant data in real time.
                </p>

                <div className="showcase-preview-frame">
                  <div className="showcase-preview-header">
                    <span>RADAR SIGNAL</span>
                    <span>CONFIDENCE</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Failed Payment Spike (Transient 504)</span>
                    <span className="showcase-badge-pill showcase-badge-pill--amber">88% · High</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>VIP Customer Inactivity (&gt;60 days)</span>
                    <span className="showcase-badge-pill showcase-badge-pill--green">94% · Actionable</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Catalog Pricing Margin Opportunity</span>
                    <span className="showcase-badge-pill showcase-badge-pill--blue">79% · Modeled</span>
                  </div>
                </div>

                <Link to="/growth-radar" className="showcase-action-link">
                  Open Live Growth Radar →
                </Link>
              </div>
            </WindowPanel>
          </div>

          {/* Panel 2: Growth Actions Console */}
          <div className="showcase-card">
            <WindowPanel title="actions-board.app" flush>
              <div className="showcase-content">
                <div className="showcase-topline">
                  <StatusChip tone="accent">HUMAN DECISION GATE</StatusChip>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.70rem", color: "var(--ink-faint)" }}>
                    5 STAGES
                  </span>
                </div>
                <h3 className="showcase-title">Growth Actions Console</h3>
                <p className="showcase-desc">
                  Review proposed initiatives with explicit Will Do / Will Not Do bounds. Approve, reject, or safely delete individual or bulk actions with persistent audit trails.
                </p>

                <div className="showcase-preview-frame">
                  <div className="showcase-preview-header">
                    <span>KANBAN LIFECYCLE</span>
                    <span>ACTIVE COUNT</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Awaiting Human Approval</span>
                    <span className="showcase-badge-pill showcase-badge-pill--amber">3 Pending</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Approved & Ready to Run</span>
                    <span className="showcase-badge-pill showcase-badge-pill--green">2 Queued</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Completed & Verified Lift</span>
                    <span className="showcase-badge-pill showcase-badge-pill--blue">18 Recorded</span>
                  </div>
                </div>

                <Link to="/actions" className="showcase-action-link">
                  Open Actions Console →
                </Link>
              </div>
            </WindowPanel>
          </div>

          {/* Panel 3: Agent Debates */}
          <div className="showcase-card">
            <WindowPanel title="agent-debate.transcript" flush>
              <div className="showcase-content">
                <div className="showcase-topline">
                  <StatusChip tone="ok">TRANSPARENT REASONING</StatusChip>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.70rem", color: "var(--ink-faint)" }}>
                    MULTI-AGENT
                  </span>
                </div>
                <h3 className="showcase-title">Agent Debates</h3>
                <p className="showcase-desc">
                  Inspect the deliberations between competing specialist agents. Watch Growth Analyst, Campaign Strategist, and Risk Guardrails reconcile trade-offs before proposals reach you.
                </p>

                <div className="showcase-preview-frame">
                  <div className="showcase-preview-header">
                    <span>AGENT SPEAKER</span>
                    <span>STANCE / REASONING</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span style={{ fontWeight: 700 }}>Growth Discovery</span>
                    <span style={{ fontSize: "0.70rem", color: "var(--ink-soft)" }}>"Target inactive cohort with 20% promotion."</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span style={{ fontWeight: 700 }}>Revenue Specialist</span>
                    <span style={{ fontSize: "0.70rem", color: "var(--coral-strong)" }}>"Counter-propose 12% cap to protect store margin."</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span style={{ fontWeight: 700 }}>Safety Guardrails</span>
                    <span className="showcase-badge-pill showcase-badge-pill--green">Ceiling Enforced</span>
                  </div>
                </div>

                <Link to="/debate" className="showcase-action-link">
                  Inspect Agent Debates →
                </Link>
              </div>
            </WindowPanel>
          </div>

          {/* Panel 4: Specialist Workstations */}
          <div className="showcase-card">
            <WindowPanel title="workstations.app" flush>
              <div className="showcase-content">
                <div className="showcase-topline">
                  <StatusChip tone="ok" pulse>5 WORKSTATIONS</StatusChip>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.70rem", color: "var(--ink-faint)" }}>
                    INTERACTIVE UI
                  </span>
                </div>
                <h3 className="showcase-title">Specialist Workstations</h3>
                <p className="showcase-desc">
                  Deep-dive into dedicated operational cockpits: Marketing AGI, Product AGI, Designer Agent, Software Agent, and Manager Orchestration.
                </p>

                <div className="showcase-preview-frame">
                  <div className="showcase-preview-header">
                    <span>WORKSTATION</span>
                    <span>PRIMARY LEVER</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Marketing Agent (/marketing-agent)</span>
                    <span className="showcase-badge-pill showcase-badge-pill--green">Re-engagement</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Product Agent (/product-agent)</span>
                    <span className="showcase-badge-pill showcase-badge-pill--blue">Catalog Velocity</span>
                  </div>
                  <div className="showcase-preview-row">
                    <span>Designer Agent (/designer-agent)</span>
                    <span className="showcase-badge-pill showcase-badge-pill--amber">Creative Briefs</span>
                  </div>
                </div>

                <Link to="/agents" className="showcase-action-link">
                  Explore AI Team Command Center →
                </Link>
              </div>
            </WindowPanel>
          </div>
        </div>
      </div>
    </section>
  );
}
