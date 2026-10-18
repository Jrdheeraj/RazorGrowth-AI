import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./ActivityTrace.css";

const AUDIT_SAMPLE = [
  {
    id: "evt-1",
    actor: "ai",
    actorType: "ai_agent",
    actorLabel: "AI Agent (Growth Discovery)",
    eventType: "ACTION_PROPOSED",
    detail: "Detected 43 abandoned checkouts with high recovery probability. Proposed bounded winback workflow.",
    time: "24m ago",
  },
  {
    id: "evt-2",
    actor: "ai",
    actorType: "ai_agent",
    actorLabel: "AI Agent (Revenue Specialist)",
    eventType: "CONTRACT_BOUNDED",
    detail: "Applied guardrail: discount capped at 12%, single email retry limit, budget ceiling $350.",
    time: "22m ago",
  },
  {
    id: "evt-3",
    actor: "human",
    actorType: "merchant_user",
    actorLabel: "Merchant Admin (You)",
    eventType: "ACTION_APPROVED",
    detail: "Reviewed parameters and approved execution. State transitioned from requested to approved.",
    time: "15m ago",
  },
  {
    id: "evt-4",
    actor: "sys",
    actorType: "system",
    actorLabel: "System Worker",
    eventType: "ACTION_EXECUTED",
    detail: "Dispatched recovery sequence safely. Measured 9 completed checkouts ($1,420 recovered).",
    time: "10m ago",
  },
] as const;

export function ActivityTrace() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="activity" className="shell section" aria-labelledby="activity-heading">
      <SectionWindowHeader
        id="activity-heading"
        eyebrow="AUDIT TRAIL · COMPLETE TRACEABILITY"
        title="Know what happened."
        accentTitle="See what comes next."
        description="Every prompt, proposal, parameter bound, human approval, and execution outcome is permanently recorded in the immutable audit trail. Accountability is never an afterthought."
        windowTitle="razorgrowth — audit_trail.app"
      />

      <div ref={reveal} className="reveal activity-trace-container">
        <WindowPanel title="audit_trail — live.log" flush>
          <div style={{ padding: "clamp(16px, 3vw, 24px)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusChip tone="ok">IMMUTABLE AUDIT LOG</StatusChip>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--ink-faint)" }}>
                  SCHEMA: audit_events
                </span>
              </div>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.70rem", color: "var(--coral-strong)" }}>
                REPRESENTATIVE WORKFLOW TRACE
              </span>
            </div>

            <div className="audit-timeline-preview">
              {AUDIT_SAMPLE.map((evt) => (
                <div key={evt.id} className="audit-entry">
                  <span
                    className={`audit-entry__marker audit-entry__marker--${evt.actor}`}
                    aria-hidden="true"
                  >
                    {evt.actor === "human" ? "YOU" : evt.actor === "ai" ? "AI" : "SYS"}
                  </span>
                  <div className="audit-entry__topline">
                    <span className="audit-entry__title">{evt.eventType}</span>
                    <span className="audit-entry__time">{evt.time}</span>
                  </div>
                  <p className="audit-entry__detail">{evt.detail}</p>
                  <span className="audit-entry__actor-tag">Recorded by {evt.actorLabel}</span>
                </div>
              ))}
            </div>

            <div className="activity-summary-banner">
              <p className="activity-summary-text">
                Every action on your dashboard includes an audit drawer with timestamps, caller identity, and failure diagnostic history.
              </p>
              <Link to="/actions" style={{ fontFamily: "var(--font-mono)", fontSize: "0.76rem", fontWeight: 700, color: "var(--coral-strong)", textDecoration: "none" }}>
                Inspect Full Audit Console →
              </Link>
            </div>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
