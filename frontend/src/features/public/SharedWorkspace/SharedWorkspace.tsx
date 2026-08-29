import { useReveal } from "../../../lib/useReveal";
import { WindowPanel } from "../../../components/WindowPanel";
import { StatusChip, StatusIndicator } from "../../../components/StatusIndicator";
import "./SharedWorkspace.css";

const WORKSPACE_AGENTS = [
  { name: "Marketing Agent", role: "Campaigns & acquisition", status: "ONLINE", activity: "Drafting Q4 festival campaign", tone: "ok" as const },
  { name: "Customer Intelligence Agent", role: "Churn & segments", status: "ONLINE", activity: "Scoring enterprise churn risk", tone: "ok" as const },
  { name: "Growth Analyst", role: "Revenue opportunities", status: "WORKING", activity: "Detecting expansion revenue signals", tone: "accent" as const },
  { name: "Campaign Agent", role: "Multi-channel execution", status: "ONLINE", activity: "Preparing retention sequences", tone: "ok" as const },
] as const;

const SHARED_CONTEXT_ITEMS = [
  { label: "Revenue Signals", items: ["MRR & ARPU trends", "Expansion revenue", "Failed payment clusters", "Plan migration patterns"] },
  { label: "Churn Indicators", items: ["Usage drop detection", "Support ticket spikes", "Contract renewal dates", "Competitor mentions"] },
  { label: "Acquisition Data", items: ["CAC by channel", "Funnel conversion rates", "Trial-to-paid signals", "Referral velocity"] },
  { label: "Experiments", items: ["Active A/B tests", "Winning variants", "Statistical significance", "Learnings archive"] },
] as const;

export function SharedWorkspace() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="shared-workspace" className="shell section" aria-labelledby="shared-workspace-heading">
      <div className="page-hero">
        <p className="meta-label">SHARED WORKSPACE · ONE CONTEXT</p>
        <h2 id="shared-workspace-heading" className="display-lg" style={{ marginTop: 10, maxWidth: "28ch" }}>
          One workspace. Shared context. No context switching.
        </h2>
        <p className="page-lede" style={{ marginTop: 16, maxWidth: "58ch" }}>
          All AI employees operate inside a single shared workspace. They read from
          and write to the same growth context. Opportunities, plans, approvals,
          and results are visible to every agent and every human — no information
          loss, no handoff friction, no tribal knowledge.
        </p>
      </div>

      <div ref={reveal} className="reveal">
        <div className="shared-workspace__layout">
          {/* Left - Workspace visualization */}
          <div className="shared-workspace__visual">
            <WindowPanel title="workspace.live" className="workspace-visual-win">
              <div className="workspace-header">
                <span className="meta-label">SHARED GROWTH WORKSPACE</span>
                <div className="workspace-header__status">
                  <StatusIndicator tone="ok" pulse label="active" />
                  <span className="meta-agent">4 AGENTS · 3 HUMANS · LIVE</span>
                </div>
              </div>

              <div className="workspace-body">
                {/* Agent panel */}
                <div className="workspace-panel">
                  <div className="workspace-panel__header">
                    <span className="meta-label">AGENTS</span>
                  </div>
                  <ul className="workspace-agent-list">
                    {WORKSPACE_AGENTS.map((agent, i) => (
                      <li key={agent.name} className={`workspace-agent ${agent.tone === "accent" ? "workspace-agent--working" : ""}`}>
                        <div className="workspace-agent__main">
                          <StatusIndicator tone={agent.tone} pulse={agent.tone === "accent"} />
                          <div className="workspace-agent__info">
                            <span className="workspace-agent__name">{agent.name}</span>
                            <span className="workspace-agent__role">{agent.role}</span>
                          </div>
                        </div>
                        <div className="workspace-agent__side">
                          <StatusChip tone={agent.tone}>{agent.status}</StatusChip>
                          <span className="workspace-agent__activity">{agent.activity}</span>
                        </div>
                      </li>
                    ))}
                    {/* Human manager */}
                    <li className="workspace-agent workspace-agent--human">
                      <div className="workspace-agent__main">
                        <StatusIndicator tone="accent" pulse />
                        <div className="workspace-agent__info">
                          <span className="workspace-agent__name">Alex Rivera</span>
                          <span className="workspace-agent__role">Growth Lead · reviewing queue</span>
                        </div>
                      </div>
                      <div className="workspace-agent__side">
                        <StatusChip tone="accent">ACTIVE</StatusChip>
                        <span className="workspace-agent__activity">2 approvals pending</span>
                      </div>
                    </li>
                  </ul>
                </div>

                {/* Shared context panel */}
                <div className="workspace-panel">
                  <div className="workspace-panel__header">
                    <span className="meta-label">SHARED CONTEXT</span>
                    <StatusChip tone="ok">SYNCED</StatusChip>
                  </div>
                  <div className="shared-context-grid">
                    {SHARED_CONTEXT_ITEMS.map((section) => (
                      <div key={section.label} className="shared-context-section">
                        <span className="shared-context-section__label">{section.label}</span>
                        <ul className="shared-context-section__items">
                          {section.items.map((item) => (
                            <li key={item}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <hr className="meta-rule" style={{ marginBlock: 16 }} />
              <p className="meta-label" style={{ justifyContent: "center" }}>
                AGENTS SHARE CONTEXT · THEY DON'T INDEPENDENTLY EXECUTE
              </p>
            </WindowPanel>
          </div>

          {/* Right - Architecture principles */}
          <div className="shared-workspace__principles">
            <WindowPanel title="architecture.principles" className="workspace-principles-win">
              <div className="principles-list">
                <article className="principle-card">
                  <div className="principle-card__header">
                    <span className="principle-card__num">01</span>
                    <h3 className="principle-card__title">Single Source of Truth</h3>
                  </div>
                  <p className="principle-card__desc">
                    One growth context object. All agents read from it. All agents
                    write proposals to it. No duplicate state. No sync issues.
                  </p>
                </article>

                <article className="principle-card">
                  <div className="principle-card__header">
                    <span className="principle-card__num">02</span>
                    <h3 className="principle-card__title">Proposals, Not Actions</h3>
                  </div>
                  <p className="principle-card__desc">
                    Agents output bounded proposals — never direct execution.
                    The workspace collects proposals; the approval gate
                    controls what runs.
                  </p>
                </article>

                <article className="principle-card">
                  <div className="principle-card__header">
                    <span className="principle-card__num">03</span>
                    <h3 className="principle-card__title">Visible to All</h3>
                  </div>
                  <p className="principle-card__desc">
                    Every agent sees every other agent's proposals.
                    Every human sees the full queue. No hidden work.
                    No surprise executions.
                  </p>
                </article>

                <article className="principle-card">
                  <div className="principle-card__header">
                    <span className="principle-card__num">04</span>
                    <h3 className="principle-card__title">Audit by Default</h3>
                  </div>
                  <p className="principle-card__desc">
                    Every read. Every write. Every proposal. Every approval.
                    Every execution. Every result. Immutable. Queryable.
                    Replayable.
                  </p>
                </article>

                <article className="principle-card principle-card--highlight">
                  <div className="principle-card__header">
                    <span className="principle-card__num">05</span>
                    <h3 className="principle-card__title">Human at the Gate</h3>
                  </div>
                  <p className="principle-card__desc">
                    The workspace is a collaboration space. The approval gate
                    is the control point. Agents collaborate. Humans decide.
                    This boundary is architectural.
                  </p>
                </article>
              </div>

              <hr className="meta-rule" style={{ marginBlock: 18 }} />
              <p className="meta-label" style={{ justifyContent: "center" }}>
                THIS IS THE CORE PRODUCT ARCHITECTURE
              </p>
            </WindowPanel>
          </div>
        </div>
      </div>
    </section>
  );
}