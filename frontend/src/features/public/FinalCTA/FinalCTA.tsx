import { WindowPanel } from "../../../components/WindowPanel";
import { ButtonLink } from "../../../components/Button";
import { useReveal } from "../../../lib/useReveal";

/** #cta — final call-to-action band. */
export function FinalCTA() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="cta" className="shell section" aria-labelledby="cta-heading">
      <div ref={reveal} className="reveal" style={{ maxWidth: 760, marginInline: "auto" }}>
        <WindowPanel title="get-started.app" tone="navy" dark>
          <div style={{ textAlign: "center", padding: "8px 4px" }}>
            <p className="meta-label" style={{ justifyContent: "center" }}>
              READY WHEN YOU ARE
            </p>
            <h2 id="cta-heading" className="display-lg" style={{ marginTop: 14, color: "var(--cream-text)" }}>
              Hire your first{" "}
              <span className="accent-word">AI growth agent.</span>
            </h2>
            <div style={{ display: "flex", justifyContent: "center", flexWrap: "wrap", gap: 12, marginTop: 26 }}>
              <ButtonLink to="/login" variant="primary">
                Get started
              </ButtonLink>
              <ButtonLink to="/login" variant="secondary">
                Log in
              </ButtonLink>
            </div>
            <hr className="meta-rule" style={{ marginBlock: 24 }} />
            <p className="meta-label" style={{ justifyContent: "center" }}>
              FREE / HUMAN APPROVAL / FULL AUDIT TRAIL
            </p>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
