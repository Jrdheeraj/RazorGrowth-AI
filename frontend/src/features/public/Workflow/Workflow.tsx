import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./Workflow.css";

const LIFECYCLE_STAGES = [
  {
    num: "01",
    name: "Proposed",
    sub: "AI agent packages opportunity & parameters",
    highlight: false,
  },
  {
    num: "02",
    name: "Awaiting Approval",
    sub: "Locked in queue; human gate required",
    highlight: true,
  },
  {
    num: "03",
    name: "Approved",
    sub: "Authorized merchant signs off",
    highlight: false,
  },
  {
    num: "04",
    name: "Running",
    sub: "Bounded execution with worker safety",
    highlight: false,
  },
  {
    num: "05",
    name: "Completed",
    sub: "Lift measured & recorded in audit trail",
    highlight: false,
  },
] as const;

export function Workflow() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="workflow" className="shell section" aria-labelledby="wf-heading">
      <SectionWindowHeader
        id="wf-heading"
        eyebrow="SAFETY & HUMAN-IN-THE-LOOP · THE APPROVAL GATE"
        title="AI prepares the action."
        accentTitle="You make the decision."
        description="In RazorGrowth AI, no money moves and no customer is contacted autonomously. Every AI initiative is prepared as a strict contract specifying what it will do and what it will NOT do."
        windowTitle="razorgrowth — approval_gate.app"
      />

      <div ref={reveal} className="reveal workflow-lifecycle-container">
        <WindowPanel title="action-guardrails.contract" flush>
          <div style={{ padding: "clamp(16px, 3vw, 24px)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.74rem", fontWeight: 700, color: "var(--coral-strong)" }}>
                AUTHORITATIVE ACTION LIFECYCLE
              </span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.70rem", color: "var(--ink-faint)" }}>
                IDEMPOTENT & TENANT-ISOLATED
              </span>
            </div>

            <div className="lifecycle-stages-bar">
              {LIFECYCLE_STAGES.map((s) => (
                <div
                  key={s.name}
                  className={`lifecycle-stage-step${s.highlight ? " lifecycle-stage-step--highlight" : ""}`}
                >
                  <span className="lifecycle-stage-num">{s.num}</span>
                  <span className="lifecycle-stage-name">
                    {s.highlight && <StatusIndicator tone="accent" pulse label="gate" />}
                    {s.name}
                  </span>
                  <span className="lifecycle-stage-sub">{s.sub}</span>
                </div>
              ))}
            </div>

            <div className="contract-bounds-grid">
              <div className="contract-bound-box contract-bound-box--will">
                <div className="contract-bound-header">
                  <span aria-hidden="true">✓</span>
                  <span>WILL DO — EXPLICIT BOUNDS</span>
                </div>
                <ul className="contract-bound-list">
                  <li>Execute strictly within the reviewed monetary or discount ceiling.</li>
                  <li>Contact only verified target customers matching engagement criteria.</li>
                  <li>Log every execution step and metric outcome in the immutable audit trail.</li>
                  <li>Stop immediately if safety thresholds or error limits are tripped.</li>
                </ul>
              </div>

              <div className="contract-bound-box contract-bound-box--wont">
                <div className="contract-bound-header">
                  <span aria-hidden="true">✕</span>
                  <span>WILL NOT DO — HARD RESTRICTIONS</span>
                </div>
                <ul className="contract-bound-list">
                  <li>Never exceed allocated budgets, promotional discounts, or retry limits.</li>
                  <li>Never message unverified contacts or spam customers.</li>
                  <li>Never re-run automatically without explicit human sign-off.</li>
                  <li>Never alter merchant workspace settings outside the defined scope.</li>
                </ul>
              </div>
            </div>

            <div className="workflow-bottom-bar">
              <span className="workflow-bottom-meta">
                Enforced server-side with tenant-isolated database constraints and role-based permissions.
              </span>
              <Link to="/actions" className="workflow-bottom-btn">
                View Growth Actions Console →
              </Link>
            </div>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
