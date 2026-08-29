import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip, StatusIndicator } from "../../../components/StatusIndicator";
import { useReveal } from "../../../lib/useReveal";
import "./Agents.css";

const ROSTER = [
  { id: "growth-analyst", file: "growth-analyst.agent", name: "Growth Analyst", line: "Detecting revenue opportunities", state: "ONLINE", tone: "ok" as const },
  { id: "campaign-agent", file: "campaign-agent.agent", name: "Campaign Agent", line: "Drafting a festival campaign", state: "WORKING", tone: "accent" as const },
  { id: "customer-intel", file: "customer-intel.agent", name: "Customer Intelligence Agent", line: "Scoring churn risk segments", state: "ONLINE", tone: "ok" as const },
];

/** #agents — the team roster (detailed agent cards land with Phase 2 content). */
export function Agents() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="agents" className="shell section" aria-labelledby="agents-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">AI TEAM · ROSTER</p>
        <h2 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>
          Meet the growth team.
        </h2>
      </div>

      <div ref={reveal} className="reveal">
        <div className="agents-grid">
          {ROSTER.map((a) => (
            <WindowPanel key={a.id} title={a.file} className="agent-card">
              <div className="agent-card__header">
                <StatusChip tone={a.tone} pulse={a.tone === "ok"}>
                  {a.state}
                </StatusChip>
                <StatusIndicator tone={a.tone} pulse={a.tone === "ok"} label={a.state.toLowerCase()} />
              </div>
              <h3 className="agent-card__name">{a.name}</h3>
              <p className="agent-card__line">{a.line}</p>
              <hr className="meta-rule" style={{ marginBlock: 14 }} />
              <p className="agent-card__meta">LAST RUN · JUST NOW</p>
            </WindowPanel>
          ))}
        </div>
      </div>
    </section>
  );
}