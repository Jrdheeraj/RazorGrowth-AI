import { WindowPanel } from "../../../components/WindowPanel";
import { ButtonLink } from "../../../components/Button";
import { scrollToSection } from "../../../lib/scroll";

/**
 * HeroMainWindow — the single focal application window.
 * Slightly left of centre per the editorial composition.
 */
export function HeroMainWindow() {
  return (
    <WindowPanel title="razorgrowth — welcome.app" className="hero-win">
      <p className="meta-label">RAZORGROWTH AI · GROWTH OPERATING SYSTEM</p>

      <h1 className="hero-win__headline">
        Run your growth engine with{" "}
        <span className="accent-word">AI employees.</span>
      </h1>

      <p className="hero-win__lede">
        RazorGrowth AI gives your growth team a system of AI employees that
        finds opportunities, plans actions, and executes with human approval.
      </p>

      <div className="hero-win__actions">
        <ButtonLink to="/login" variant="primary">
          Get started
        </ButtonLink>
        <button
          type="button"
          className="btn btn--secondary"
          onClick={() => scrollToSection("how-it-works")}
        >
          See how it works
        </button>
      </div>

      <hr className="meta-rule" style={{ marginBlock: "24px 18px" }} />
      <p className="meta-label">AI GROWTH TEAM · HUMAN APPROVAL · REAL DATA</p>
    </WindowPanel>
  );
}
