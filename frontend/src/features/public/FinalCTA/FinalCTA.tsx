import { WindowPanel } from "../../../components/WindowPanel";
import { ButtonLink } from "../../../components/Button";
import { useReveal } from "../../../lib/useReveal";

/** #cta — final call-to-action band. */
export function FinalCTA() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="cta" className="shell section" aria-labelledby="cta-heading">
      <div ref={reveal} className="reveal" style={{ maxWidth: 780, marginInline: "auto" }}>
        <WindowPanel title="razorgrowth — get_started.app" tone="navy" dark>
          <div style={{ textAlign: "center", padding: "16px 8px" }}>
            <p className="meta-label" style={{ justifyContent: "center" }}>
              READY WHEN YOU ARE · DEPLOY IN MINUTES
            </p>
            <h2 id="cta-heading" className="display-lg" style={{ marginTop: 14, color: "var(--cream-text)" }}>
              Give your growth team a{" "}
              <span className="accent-word">clearer way to work.</span>
            </h2>
            <p style={{ color: "var(--cream-muted)", maxWidth: "56ch", margin: "14px auto 0", fontSize: "0.95rem", lineHeight: 1.6 }}>
              Explore how RazorGrowth AI connects growth analysis, specialist agents, recommendations, and controlled actions in one unified workspace.
            </p>
            <div style={{ display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 14, marginTop: 26 }}>
              <ButtonLink to="/login" variant="primary">
                Get Started
              </ButtonLink>
              <ButtonLink to="/agents" variant="secondary">
                Explore the AI Team
              </ButtonLink>
            </div>
            <hr className="meta-rule" style={{ marginBlock: 24, borderColor: "var(--line-on-dark-soft)" }} />
            <p className="meta-label" style={{ justifyContent: "center", color: "var(--cream-muted)" }}>
              AI-ASSISTED GROWTH · HUMAN APPROVAL · TRACEABLE WORKFLOWS
            </p>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
