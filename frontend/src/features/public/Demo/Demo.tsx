import { useState } from "react";
import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator, StatusChip } from "../../../components/StatusIndicator";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./Demo.css";

const STAGES = [
  {
    id: "radar",
    tabNumber: "STAGE 1",
    tabLabel: "Signal Discovery",
    title: "Step 1: Signal Detected on Growth Radar",
    badge: "RADAR MONITORING",
    desc: "The Growth Discovery Agent notices a pattern: 48 shoppers dropped out during payment due to a temporary gateway timeout, leaving $3,800 in unfulfilled orders.",
    mockupHeader: "growth-radar — telemetry.log",
    mockupRows: [
      { key: "EVENT", val: "Checkout Payment Dropoff Cluster" },
      { key: "AFFECTED MERCHANDISE", val: "Premium Soundbar & Ergonomic Keyboard" },
      { key: "POTENTIAL REVENUE", val: "$3,800 (48 cart sessions)" },
      { key: "CONFIDENCE SCORE", val: "92% (Recoverable transient failures)" },
    ],
    nextButtonText: "Advance to Manager Agent →",
  },
  {
    id: "manager",
    tabNumber: "STAGE 2",
    tabLabel: "Manager Plan",
    title: "Step 2: Manager Agent Plans Task Graph",
    badge: "WORKFLOW DECOMPOSITION",
    desc: "ManagerAgent consumes the opportunity signal and builds a dependency plan: Marketing drafts tailored messages, Designer creates email banners, and Software checks webhook feasibility.",
    mockupHeader: "manager-agent — execution_graph.json",
    mockupRows: [
      { key: "TASK 1", val: "Marketing Agent: Segment 48 dropoffs (Status: DONE)" },
      { key: "TASK 2", val: "Designer Agent: Draft recovery banner (Status: READY)" },
      { key: "TASK 3", val: "Software Agent: Feasibility check (Status: PASSED)" },
      { key: "SYNTHESIS", val: "Consolidate into 1 reviewable Action" },
    ],
    nextButtonText: "Advance to Agent Debate →",
  },
  {
    id: "debate",
    tabNumber: "STAGE 3",
    tabLabel: "Debate & Bounds",
    title: "Step 3: Specialists Deliberate & Bound the Offer",
    badge: "CONSENSUS BUILDING",
    desc: "Marketing proposes an aggressive 20% discount. Revenue Specialist objects, noting that 10% is sufficient to convert without eroding product margin. Guardrails lock the 10% ceiling.",
    mockupHeader: "agent-debates — live_transcript.txt",
    mockupRows: [
      { key: "MARKETING AGENT", val: "Proposes 20% win-back incentive" },
      { key: "REVENUE AGENT", val: "Counters: Max 10% to protect gross margin" },
      { key: "SAFETY GUARDRAIL", val: "Enforces 10% cap + 1-retry limit" },
      { key: "STATUS", val: "CONSENSUS REACHED (No automated execution)" },
    ],
    nextButtonText: "Advance to Human Gate →",
  },
  {
    id: "actions",
    tabNumber: "STAGE 4",
    tabLabel: "Human Gate",
    title: "Step 4: Human Review & Audited Execution",
    badge: "HUMAN DECISION GATE",
    desc: "The proposed action appears on your Growth Actions Kanban board. You review the exact Will Do / Will Not Do terms and click Approve. Execution runs bounded and permanently logs to audit history.",
    mockupHeader: "actions-console — action_contract.app",
    mockupRows: [
      { key: "PROPOSAL", val: "Targeted Inactive Cart Win-Back Sequence" },
      { key: "BOUNDS", val: "10% coupon, max 48 contacts, $380 budget cap" },
      { key: "DECISION", val: "Merchant Admin clicked APPROVE" },
      { key: "OUTCOME", val: "22 orders recovered · $1,760 lift logged" },
    ],
    nextButtonText: "Replay Walkthrough ↺",
  },
] as const;

export function Demo() {
  const reveal = useReveal<HTMLDivElement>();
  const [activeIdx, setActiveIdx] = useState(0);

  const current = STAGES[activeIdx];

  const handleNext = () => {
    setActiveIdx((prev) => (prev + 1) % STAGES.length);
  };

  const handlePrev = () => {
    setActiveIdx((prev) => (prev === 0 ? STAGES.length - 1 : prev - 1));
  };

  return (
    <section id="demo" className="shell section" aria-labelledby="demo-heading">
      <SectionWindowHeader
        id="demo-heading"
        eyebrow="PRODUCT WALKTHROUGH · REALISTIC SCENARIO"
        title="Explore an end-to-end"
        accentTitle="growth run."
        description="Follow how RazorGrowth AI detects a revenue leakage, coordinates autonomous agents, bounds the offer, and waits for your explicit sign-off."
        windowTitle="razorgrowth — interactive_demo.app"
      />

      <div ref={reveal} className="reveal walkthrough-container" style={{ marginTop: 22 }}>
        <div className="walkthrough-step-tabs" role="tablist" aria-label="Walkthrough stages">
          {STAGES.map((s, idx) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={activeIdx === idx}
              className={`walkthrough-tab-btn${activeIdx === idx ? " walkthrough-tab-btn--active" : ""}`}
              onClick={() => setActiveIdx(idx)}
            >
              <span className="walkthrough-tab-step-num">{s.tabNumber}</span>
              <span className="walkthrough-tab-title">{s.tabLabel}</span>
            </button>
          ))}
        </div>

        <div className="walkthrough-stage-card">
          <div className="walkthrough-stage-header">
            <h3 className="walkthrough-stage-title">{current.title}</h3>
            <StatusChip tone={activeIdx === 3 ? "accent" : "ok"}>
              {current.badge}
            </StatusChip>
          </div>

          <div className="walkthrough-stage-body">
            <div className="walkthrough-stage-narrative">
              <p>{current.desc}</p>
              <div style={{ marginTop: 8 }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.72rem", color: "var(--ink-faint)" }}>
                  HUMAN GATE STATUS: {activeIdx === 3 ? "AWAITING YOUR APPROVAL" : "PREPARATION PHASE"}
                </span>
              </div>
            </div>

            <div className="walkthrough-stage-mockup">
              <div style={{ borderBottom: "1px solid var(--line-soft)", paddingBottom: 6, marginBottom: 8, fontWeight: 700, color: "var(--coral-strong)" }}>
                {current.mockupHeader}
              </div>
              {current.mockupRows.map((r) => (
                <div key={r.key} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "1px dashed rgba(42, 24, 16, 0.1)" }}>
                  <span style={{ color: "var(--ink-faint)" }}>{r.key}:</span>
                  <strong style={{ color: "var(--ink)" }}>{r.val}</strong>
                </div>
              ))}
            </div>
          </div>

          <div className="walkthrough-controls-row">
            <button
              type="button"
              className="walkthrough-nav-btn"
              onClick={handlePrev}
              disabled={activeIdx === 0}
            >
              ← Previous Step
            </button>

            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.74rem", color: "var(--ink-faint)" }}>
              STAGE {activeIdx + 1} OF {STAGES.length}
            </span>

            <button
              type="button"
              className="walkthrough-nav-btn walkthrough-nav-btn--primary"
              onClick={handleNext}
            >
              {current.nextButtonText}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
