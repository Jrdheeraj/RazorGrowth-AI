import { WindowPanel } from "../../../components/WindowPanel";
import { useReveal } from "../../../lib/useReveal";

/** #demo — replay deck teaser (full interactive walkthrough lands later). */
export function Demo() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="demo" className="shell section" aria-labelledby="demo-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">DEMO · REAL SESSION</p>
        <h2 id="demo-heading" className="display-lg" style={{ marginTop: 10 }}>
          Watch a session replay.
        </h2>
      </div>

      <div ref={reveal} className="reveal">
        <WindowPanel title="replay_deck — real session" tone="navy" dark>
          <p style={{ color: "var(--cream-muted)", maxWidth: "60ch" }}>
            A recorded run: agents scan the store, surface a failed-payment
            cluster, draft a bounded recovery plan, and queue it for a human
            decision. Nothing executes until it is approved.
          </p>
          <hr className="meta-rule" style={{ marginBlock: 20 }} />
          <p className="meta-label">WORKSPACE / SIDEBAR / AGENTS / ACTIVITY / APPROVALS</p>
        </WindowPanel>
      </div>
    </section>
  );
}
