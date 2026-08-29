import { useReveal } from "../../../lib/useReveal";
import { WindowPanel } from "../../../components/WindowPanel";
import "./Comparison.css";

const COMPARISON_ROWS = [
  {
    category: "FOUNDER / TEAM",
    before: "You wear every hat. Growth is reactive.",
    after: "AI employees handle watching, planning, drafting."
  },
  {
    category: "DATA",
    before: "Scattered across tools. No single source of truth.",
    after: "Unified growth context. All agents read/write to one workspace."
  },
  {
    category: "MONITORING",
    before: "Manual checks. Dashboards you forget to open.",
    after: "Continuous 24/7 monitoring. Agents never sleep."
  },
  {
    category: "OPPORTUNITIES",
    before: "Found by luck or late. No scoring. No priority.",
    after: "Detected, scored, prioritized. High-confidence queue."
  },
  {
    category: "PLANNING",
    before: "Ad-hoc. Scattered docs. No guardrails.",
    after: "Bounded plans. Reason. Impact. Guardrails. Rollback."
  },
  {
    category: "DECISIONS",
    before: "Delayed. Context lost in handoffs. No audit trail.",
    after: "Human approval gate. Shared context. Full audit history."
  },
  {
    category: "EXECUTION",
    before: "Manual. Error-prone. No replay. Drift happens.",
    after: "Bounded actions run exactly as approved. Replayable."
  },
  {
    category: "LEARNING",
    before: "Tribal knowledge. Lost when people leave.",
    after: "Every run recorded. Agents learn. Institutional memory."
  },
] as const;

export function Comparison() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="comparison" className="shell section" aria-labelledby="comparison-heading">
      <div className="page-hero">
        <p className="meta-label">COMPARISON · BEFORE & AFTER</p>
        <h2 id="comparison-heading" className="display-lg" style={{ marginTop: 10, maxWidth: "28ch" }}>
          The difference isn't incremental. It's architectural.
        </h2>
      </div>

      <div ref={reveal} className="reveal">
        <WindowPanel title="before_after.diff" className="comparison-win">
          <div className="comparison-table">
            <div className="comparison-header">
              <div className="comparison-col comparison-col--category">CATEGORY</div>
              <div className="comparison-col comparison-col--before">
                <span className="comparison-col__label">BEFORE RAZORGROWTH</span>
                <span className="comparison-col__badge comparison-col__badge--before">MANUAL</span>
              </div>
              <div className="comparison-col comparison-col--after">
                <span className="comparison-col__label">AFTER RAZORGROWTH</span>
                <span className="comparison-col__badge comparison-col__badge--after">AI EMPLOYEES</span>
              </div>
            </div>

            <div className="comparison-rows">
              {COMPARISON_ROWS.map((row, i) => (
                <div key={row.category} className={`comparison-row ${i % 2 === 0 ? "comparison-row--even" : "comparison-row--odd"}`}>
                  <div className="comparison-col comparison-col--category">
                    <span className="comparison-row__category">{row.category}</span>
                  </div>
                  <div className="comparison-col comparison-col--before">
                    <p className="comparison-row__text">{row.before}</p>
                  </div>
                  <div className="comparison-col comparison-col--after">
                    <p className="comparison-row__text">{row.after}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <hr className="meta-rule" style={{ marginBlock: 22 }} />
          <p className="meta-label" style={{ justifyContent: "center" }}>
            AGENTS PROPOSE · HUMANS DECIDE · EVERYTHING RECORDED
          </p>
        </WindowPanel>
      </div>
    </section>
  );
}