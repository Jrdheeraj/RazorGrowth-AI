import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator } from "../../../components/StatusIndicator";
import { useReveal } from "../../../lib/useReveal";

const STEPS = [
  "DATA",
  "AI ANALYSIS",
  "OPPORTUNITY",
  "RECOMMENDATION",
  "BOUNDED ACTION",
  "HUMAN APPROVAL",
  "EXECUTION",
  "RESULT",
  "AUDIT TRAIL",
] as const;

/** #workflow — the pipeline that makes human approval unavoidable. */
export function Workflow() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="workflow" className="shell section" aria-labelledby="wf-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">WORKFLOW · GUARDED PIPELINE</p>
        <h2 id="wf-heading" className="display-lg" style={{ marginTop: 10, maxWidth: "22ch" }}>
          Agents propose. You decide.
        </h2>
      </div>

      <div ref={reveal} className="reveal">
        <WindowPanel title="pipeline.cfg">
          <ol style={{ display: "flex", flexWrap: "wrap", gap: "10px 18px", alignItems: "center" }}>
            {STEPS.map((s, i) => (
              <li key={s} style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                <span className="meta-label" style={{ color: s === "HUMAN APPROVAL" ? "var(--coral-deep)" : undefined }}>
                  <StatusIndicator tone={s === "HUMAN APPROVAL" ? "accent" : "idle"} label="" />
                  {s}
                </span>
                {i < STEPS.length - 1 && (
                  <span aria-hidden="true" style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>
                    →
                  </span>
                )}
              </li>
            ))}
          </ol>
          <hr className="meta-rule" style={{ marginBlock: 18 }} />
          <p style={{ color: "var(--ink-faint)", fontSize: "var(--text-small)" }}>
            Guardrails wrap every step; approval cannot be bypassed by any
            role, token or agent.
          </p>
        </WindowPanel>
      </div>
    </section>
  );
}
